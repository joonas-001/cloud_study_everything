from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import inspect, select

from cloud_study_api.credentials import MemoryCredentialStore
from cloud_study_api.database import (
    create_database_engine,
    create_database_url,
    create_session_factory,
    read_schema_version,
    upgrade_database,
)
from cloud_study_api.diagnostics import DiagnosticService
from cloud_study_api.execution import LearningExecutionService
from cloud_study_api.experiments import ExperimentError, ExperimentService
from cloud_study_api.governance import validate_repository
from cloud_study_api.learning import LearningService
from cloud_study_api.main import app
from cloud_study_api.models import (
    AiProviderProfile,
    ExperimentEvent,
    MarketResearchRun,
    MasterySnapshot,
)
from cloud_study_api.notifications import NotificationService
from cloud_study_api.readiness import ReadinessService

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DIMENSIONS = (
    "understanding",
    "operation",
    "transfer",
    "artifact",
    "retention",
    "correction",
)
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _services(
    tmp_path: Path,
) -> tuple[
    DiagnosticService,
    LearningService,
    LearningExecutionService,
    ReadinessService,
    ExperimentService,
    Any,
]:
    database_path = tmp_path / "experiments.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    packages = validate_repository(REPOSITORY_ROOT)
    diagnostics = DiagnosticService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        now=lambda: NOW,
    )
    notifications = NotificationService(
        session_factory=session_factory,
        credential_store=MemoryCredentialStore(),
        now=lambda: NOW,
    )
    learning = LearningService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        notification_service=notifications,
        now=lambda: NOW,
    )
    execution = LearningExecutionService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        now=lambda: NOW,
    )
    readiness = ReadinessService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        now=lambda: NOW,
    )
    experiments = ExperimentService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        now=lambda: NOW,
    )
    return diagnostics, learning, execution, readiness, experiments, session_factory


def _run(
    diagnostics: DiagnosticService,
    learning: LearningService,
    execution: LearningExecutionService,
) -> dict[str, Any]:
    diagnostic = diagnostics.create_session(
        skill_id="algorithm",
        skill_version="0.2.2",
        preview=True,
        provider_id="local-deterministic",
        model_id="diagnostic-v1",
        credential_reference=None,
        external_ai_consent=False,
    )
    diagnostics.end_session(diagnostic["id"])
    proposal = learning.create_planning_proposal(
        diagnostic_session_id=diagnostic["id"],
        preview=True,
        provider_id="local-deterministic",
        model_id="planner-sim-v1",
    )
    saved = learning.set_proposal_status(proposal["id"], "saved_preview")
    return execution.create_run(
        planning_proposal_id=saved["id"],
        preview=True,
        code_execution=True,
        external_ai=False,
        confirm_historical_plan=True,
        reuse_from_run_id=None,
        confirm_reuse=False,
    )


def _goal(readiness: ReadinessService, run_id: str) -> dict[str, Any]:
    scope = next(item for item in readiness.list_scopes() if item["learning_run_id"] == run_id)
    return readiness.select_goal(
        skill_id=scope["skill_id"],
        skill_version=scope["skill_version"],
        capability_scope_id=scope["capability_scope_id"],
        goal_kind="employment",
        custom_label=None,
    )


def _plan(path: str = "employment") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "path": path,
        "title": "初级 C++ 后端作品与求职假设验证",
        "target_audience": "中国大陆中文市场中的初级 C++ 后端与算法应用岗位",
        "hypothesis": "限定范围的 Runner 与作品证据足以支持一次低风险求职材料验证。",
        "planned_action": "先在本地整理作品说明。满足真实动作门禁后由用户自行投递。",
        "success_metric": "形成一份可复核作品说明并记录外部动作是否获得回应。",
        "time_budget_minutes": 240,
        "cost_cap_minor": 0,
        "stop_conditions": ["证据门禁失效", "达到时间预算"],
        "non_offerings": ["不承诺超出已验证范围的算法能力", "不自动投递或联系"],
        "compliance_todos": ["投递前人工检查隐私字段"],
        "review_on": "2026-08-08",
    }


def _set_evidence(
    session_factory: Any,
    run_id: str,
    *,
    action_ready: bool,
    blocking_flag: str | None = None,
    updated_at: datetime = NOW,
) -> None:
    with session_factory() as database:
        existing = {
            item.dimension: item
            for item in database.scalars(
                select(MasterySnapshot).where(MasterySnapshot.run_id == run_id)
            ).all()
        }
        for dimension in DIMENSIONS:
            item = existing.get(dimension)
            level = "supported"
            if action_ready and dimension == "operation":
                level = "verified"
            if action_ready and dimension == "retention":
                level = "retained"
            flags = (
                f'["{blocking_flag}"]'
                if blocking_flag is not None and dimension == "artifact"
                else "[]"
            )
            if item is None:
                database.add(
                    MasterySnapshot(
                        id=f"{run_id}-{dimension}",
                        run_id=run_id,
                        dimension=dimension,
                        evidence_level=level,
                        review_flags_json=flags,
                        evidence_count=1,
                        updated_at=updated_at,
                    )
                )
            else:
                item.evidence_level = level
                item.review_flags_json = flags
                item.evidence_count = 1
                item.updated_at = updated_at
        database.commit()


def _market(
    session_factory: Any,
    run: dict[str, Any],
    goal: dict[str, Any],
    *,
    completed_at: datetime | None = NOW,
) -> str:
    market_id = "accepted-market-research"
    registry = json.loads(
        (REPOSITORY_ROOT / "readiness" / "market-research-registry-v1.json").read_text(
            encoding="utf-8"
        )
    )
    matching_catalogs = []
    for registration in registry["registrations"]:
        catalog = json.loads(
            (REPOSITORY_ROOT / registration["catalog_path"]).read_text(encoding="utf-8")
        )
        context = catalog["research_context"]
        if (
            context["skill_id"] == run["skill_id"]
            and context["skill_version"] == run["skill_version"]
            and context["capability_scope_id"] == goal["capability_scope_id"]
        ):
            matching_catalogs.append(catalog)
    assert len(matching_catalogs) == 1
    catalog = matching_catalogs[0]
    catalog_snapshot = json.dumps(
        catalog, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    with session_factory() as database:
        database.add(
            AiProviderProfile(
                id="market-profile",
                provider_id="deepseek",
                display_name="测试市场档案",
                model_id="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                credential_reference="credential:test-only",
                enabled=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        database.add(
            MarketResearchRun(
                id=market_id,
                catalog_id=catalog["catalog_id"],
                catalog_version=catalog["version"],
                catalog_sha256=hashlib.sha256(catalog_snapshot.encode("utf-8")).hexdigest(),
                catalog_snapshot_json=catalog_snapshot,
                skill_id=run["skill_id"],
                skill_version=run["skill_version"],
                capability_scope_id=goal["capability_scope_id"],
                goal_selection_id=goal["id"],
                goal_kind="employment",
                goal_snapshot_json="{}",
                readiness_evaluation_id=None,
                scope_json="{}",
                budget_policy_id="deepseek-v4-flash-market-budget",
                budget_policy_version="1.0.0",
                budget_policy_sha256="b" * 64,
                budget_policy_snapshot_json="{}",
                status="completed",
                provider_profile_id="market-profile",
                provider_id="deepseek",
                model_id="deepseek-v4-flash",
                response_model_id="deepseek-v4-flash",
                credential_reference="credential:test-only",
                external_ai_consent=False,
                source_results_json="[]",
                synthesis_json="{}",
                synthesis_valid=True,
                synthesis_attempt_id=None,
                synthesis_invalidated_at=None,
                cost_accounted_at=NOW,
                review_status="accepted",
                review_note=None,
                estimated_cost_micros=0,
                actual_cost_micros=0,
                accounted_cost_micros=0,
                input_tokens=0,
                cached_input_tokens=0,
                output_tokens=0,
                failure_code=None,
                created_at=completed_at or NOW,
                updated_at=completed_at or NOW,
                completed_at=completed_at,
            )
        )
        database.commit()
    return market_id


def _create_fixture(
    tmp_path: Path,
) -> tuple[ExperimentService, Any, dict[str, Any], dict[str, Any]]:
    diagnostics, learning, execution, readiness, experiments, sessions = _services(tmp_path)
    run = _run(diagnostics, learning, execution)
    goal = _goal(readiness, run["id"])
    return experiments, sessions, run, goal


def test_draft_records_missing_evidence_without_promoting_readiness(tmp_path: Path) -> None:
    experiments, _sessions, run, goal = _create_fixture(tmp_path)

    draft = experiments.create_experiment(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_research_run_id=None,
        plan=_plan(),
    )

    assert draft["status"] == "draft"
    assert draft["gate_level"] == "draft_only"
    assert "operation_verified_required" in draft["gate_reason_codes"]
    assert "market_review_missing" in draft["gate_reason_codes"]
    assert (
        len(
            [
                code
                for code in draft["gate_reason_codes"]
                if code.startswith("evidence_dimension_missing:")
            ]
        )
        == 6
    )
    assert draft["external_action_mode"] == "manual_record_only"
    assert draft["actions"] == []


def test_freelancing_and_productization_remain_disabled(tmp_path: Path) -> None:
    experiments, _sessions, run, goal = _create_fixture(tmp_path)

    with pytest.raises(ExperimentError, match="只启用就业路径") as caught:
        experiments.create_experiment(
            goal_selection_id=goal["id"],
            learning_run_id=run["id"],
            market_research_run_id=None,
            plan=_plan("freelancing"),
        )

    assert caught.value.code == "path_not_enabled"


def test_local_experiment_can_start_but_cannot_record_external_action(
    tmp_path: Path,
) -> None:
    experiments, sessions, run, goal = _create_fixture(tmp_path)
    _set_evidence(sessions, run["id"], action_ready=False)
    experiment = experiments.create_experiment(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_research_run_id=None,
        plan=_plan(),
    )
    assert experiment["gate_level"] == "local_ready"
    experiment = experiments.transition(experiment["id"], action="approve", confirm=True)
    experiment = experiments.transition(experiment["id"], action="start", confirm=True)

    with pytest.raises(ExperimentError) as caught:
        experiments.record_external_action(
            experiment["id"],
            action_kind="application",
            description="用户在外部手动投递",
            result="pending",
            occurred_at=NOW,
            confirm_completed_outside_product=True,
        )

    assert caught.value.code == "external_action_gate_not_ready"
    assert experiment["status"] == "active"


def test_action_ready_requires_runner_human_reviews_and_accepted_market(
    tmp_path: Path,
) -> None:
    experiments, sessions, run, goal = _create_fixture(tmp_path)
    _set_evidence(sessions, run["id"], action_ready=True)
    market_id = _market(sessions, run, goal)
    experiment = experiments.create_experiment(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_research_run_id=market_id,
        plan=_plan(),
    )
    assert experiment["gate_level"] == "local_ready"

    experiment = experiments.add_independent_review(
        experiment["id"],
        dimension="transfer",
        reviewer_relationship="mentor",
        review_scope=goal["capability_scope_id"],
        rubric_id="external-transfer-v1",
        rubric_version="1.0.0",
        conclusion="passed",
        reviewed_at=NOW,
    )
    assert experiment["gate_level"] == "local_ready"
    experiment = experiments.add_independent_review(
        experiment["id"],
        dimension="artifact",
        reviewer_relationship="peer",
        review_scope=goal["capability_scope_id"],
        rubric_id="external-artifact-v1",
        rubric_version="1.0.0",
        conclusion="passed",
        reviewed_at=NOW,
    )
    assert experiment["gate_level"] == "action_ready"
    assert experiment["gate_reason_codes"][0] == "action_gate_satisfied"

    experiment = experiments.transition(experiment["id"], action="approve", confirm=True)
    experiment = experiments.transition(experiment["id"], action="start", confirm=True)
    experiment = experiments.record_external_action(
        experiment["id"],
        action_kind="application",
        description="用户已在产品外手动完成一次岗位投递。",
        result="response",
        occurred_at=NOW,
        confirm_completed_outside_product=True,
    )

    assert experiment["actions"][0]["execution_mode"] == "completed_outside_product"
    assert experiment["actions"][0]["result"] == "response"
    experiments._now = lambda: NOW + timedelta(minutes=1)
    regressed = experiments.add_independent_review(
        experiment["id"],
        dimension="artifact",
        reviewer_relationship="mentor",
        review_scope=goal["capability_scope_id"],
        rubric_id="external-artifact-v1",
        rubric_version="1.0.0",
        conclusion="needs_work",
        reviewed_at=NOW + timedelta(minutes=1),
    )
    assert regressed["gate_level"] == "local_ready"
    assert "independent_artifact_review_required" in regressed["gate_reason_codes"]


def test_action_gate_rejects_unmanaged_or_future_human_reviews(tmp_path: Path) -> None:
    experiments, sessions, run, goal = _create_fixture(tmp_path)
    _set_evidence(sessions, run["id"], action_ready=True)
    experiment = experiments.create_experiment(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_research_run_id=_market(sessions, run, goal),
        plan=_plan(),
    )

    invalid_cases = [
        (
            {
                "review_scope": "free-text-scope",
                "rubric_id": "external-transfer-v1",
                "rubric_version": "1.0.0",
                "reviewed_at": NOW,
            },
            "independent_review_scope_mismatch",
        ),
        (
            {
                "review_scope": goal["capability_scope_id"],
                "rubric_id": "unmanaged-rubric",
                "rubric_version": "1.0.0",
                "reviewed_at": NOW,
            },
            "independent_review_rubric_unapproved",
        ),
        (
            {
                "review_scope": goal["capability_scope_id"],
                "rubric_id": "external-transfer-v1",
                "rubric_version": "1.0.0",
                "reviewed_at": NOW + timedelta(seconds=1),
            },
            "independent_review_future_dated",
        ),
    ]
    for values, expected_code in invalid_cases:
        with pytest.raises(ExperimentError) as caught:
            experiments.add_independent_review(
                experiment["id"],
                dimension="transfer",
                reviewer_relationship="mentor",
                conclusion="passed",
                **values,
            )
        assert caught.value.code == expected_code


@pytest.mark.parametrize(
    ("stale_evidence", "stale_reviews", "stale_market", "reason_prefix"),
    [
        (True, False, False, "evidence_expired:"),
        (False, True, False, "independent_review_expired:"),
        (False, False, True, "market_research_expired"),
    ],
)
def test_action_gate_blocks_expired_inputs(
    tmp_path: Path,
    stale_evidence: bool,
    stale_reviews: bool,
    stale_market: bool,
    reason_prefix: str,
) -> None:
    experiments, sessions, run, goal = _create_fixture(tmp_path)
    _set_evidence(
        sessions,
        run["id"],
        action_ready=True,
        updated_at=NOW - timedelta(days=91) if stale_evidence else NOW,
    )
    market_id = _market(
        sessions,
        run,
        goal,
        completed_at=NOW - timedelta(days=8) if stale_market else NOW,
    )
    experiment = experiments.create_experiment(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_research_run_id=market_id,
        plan=_plan(),
    )
    review_time = NOW - timedelta(days=91) if stale_reviews else NOW
    for dimension in ("transfer", "artifact"):
        experiment = experiments.add_independent_review(
            experiment["id"],
            dimension=dimension,
            reviewer_relationship="mentor",
            review_scope=goal["capability_scope_id"],
            rubric_id=f"external-{dimension}-v1",
            rubric_version="1.0.0",
            conclusion="passed",
            reviewed_at=review_time,
        )

    assert experiment["gate_level"] == "blocked"
    assert any(code.startswith(reason_prefix) for code in experiment["gate_reason_codes"])


def test_action_gate_blocks_future_evidence(tmp_path: Path) -> None:
    experiments, sessions, run, goal = _create_fixture(tmp_path)
    _set_evidence(
        sessions,
        run["id"],
        action_ready=True,
        updated_at=NOW + timedelta(seconds=1),
    )

    experiment = experiments.create_experiment(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_research_run_id=_market(sessions, run, goal),
        plan=_plan(),
    )

    assert experiment["gate_level"] == "blocked"
    assert any(
        code.startswith("evidence_future_dated:") for code in experiment["gate_reason_codes"]
    )


@pytest.mark.parametrize(
    ("completed_at", "expected_reason"),
    [
        (NOW + timedelta(seconds=1), "market_research_future_dated"),
        (None, "market_research_timestamp_missing"),
    ],
)
def test_action_gate_blocks_invalid_market_completion_time(
    tmp_path: Path,
    completed_at: datetime | None,
    expected_reason: str,
) -> None:
    experiments, sessions, run, goal = _create_fixture(tmp_path)
    _set_evidence(sessions, run["id"], action_ready=True)

    experiment = experiments.create_experiment(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_research_run_id=_market(sessions, run, goal, completed_at=completed_at),
        plan=_plan(),
    )

    assert experiment["gate_level"] == "blocked"
    assert expected_reason in experiment["gate_reason_codes"]


def test_expired_active_experiment_is_persistently_paused_before_external_action(
    tmp_path: Path,
) -> None:
    experiments, sessions, run, goal = _create_fixture(tmp_path)
    _set_evidence(sessions, run["id"], action_ready=True)
    experiment = experiments.create_experiment(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_research_run_id=_market(sessions, run, goal),
        plan=_plan(),
    )
    for dimension in ("transfer", "artifact"):
        experiment = experiments.add_independent_review(
            experiment["id"],
            dimension=dimension,
            reviewer_relationship="mentor",
            review_scope=goal["capability_scope_id"],
            rubric_id=f"external-{dimension}-v1",
            rubric_version="1.0.0",
            conclusion="passed",
            reviewed_at=NOW,
        )
    experiment = experiments.transition(experiment["id"], action="approve", confirm=True)
    experiment = experiments.transition(experiment["id"], action="start", confirm=True)
    experiments._now = lambda: NOW + timedelta(days=8)

    with pytest.raises(ExperimentError) as caught:
        experiments.record_external_action(
            experiment["id"],
            action_kind="application",
            description="不应记录的过期市场动作",
            result="pending",
            occurred_at=NOW + timedelta(days=8),
            confirm_completed_outside_product=True,
        )

    assert caught.value.code == "experiment_not_active"
    paused = experiments.get_experiment(experiment["id"])
    assert paused["status"] == "paused"
    assert paused["gate_level"] == "blocked"
    assert "market_research_expired" in paused["gate_reason_codes"]


def test_income_is_hidden_revisioned_exported_only_with_confirmation_and_redacted(
    tmp_path: Path,
) -> None:
    experiments, sessions, run, goal = _create_fixture(tmp_path)
    _set_evidence(sessions, run["id"], action_ready=True)
    experiment = experiments.create_experiment(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_research_run_id=_market(sessions, run, goal),
        plan=_plan(),
    )
    for dimension in ("transfer", "artifact"):
        experiment = experiments.add_independent_review(
            experiment["id"],
            dimension=dimension,
            reviewer_relationship="mentor",
            review_scope=goal["capability_scope_id"],
            rubric_id=f"external-{dimension}-v1",
            rubric_version="1.0.0",
            conclusion="passed",
            reviewed_at=NOW,
        )
    experiment = experiments.transition(experiment["id"], action="approve", confirm=True)
    experiment = experiments.transition(experiment["id"], action="start", confirm=True)
    experiment = experiments.record_external_action(
        experiment["id"],
        action_kind="application",
        description="用户已在产品外完成动作",
        result="offer",
        occurred_at=NOW,
        confirm_completed_outside_product=True,
    )
    values = {
        "currency": "CNY",
        "amount_basis": "pre_tax",
        "gross_amount_minor": 100_000,
        "platform_fee_minor": 0,
        "direct_cost_minor": 2_000,
        "received_amount_minor": 98_000,
        "verification_level": "received",
        "note": "不包含附件",
        "occurred_on": "2026-08-01",
    }
    hidden = experiments.create_income(
        experiment["id"],
        values=values,
        confirm_manual_record=True,
    )
    income_id = hidden["income_records"][0]["id"]
    assert hidden["income_records"][0]["amounts_hidden"] is True
    assert hidden["income_records"][0]["revisions"][0]["gross_amount_minor"] is None

    revealed = experiments.get_experiment(experiment["id"], reveal_income=True)
    assert revealed["income_records"][0]["revisions"][0]["gross_amount_minor"] == 100_000
    with pytest.raises(ExperimentError) as caught:
        experiments.export_experiment(
            experiment["id"],
            export_format="json",
            confirm_sensitive_export=False,
        )
    assert caught.value.code == "sensitive_export_confirmation_required"
    media_type, exported = experiments.export_experiment(
        experiment["id"],
        export_format="json",
        confirm_sensitive_export=True,
    )
    assert media_type.startswith("application/json")
    assert '"gross_amount_minor": 100000' in exported

    revised_values = {**values, "received_amount_minor": 99_000}
    revised = experiments.revise_income(
        experiment["id"],
        income_id,
        values=revised_values,
        confirm_revision=True,
    )
    assert revised["income_records"][0]["current_revision"] == 2
    redacted = experiments.redact_income(
        experiment["id"],
        income_id,
        confirm_redaction=True,
    )
    revealed_after = experiments.get_experiment(experiment["id"], reveal_income=True)
    assert redacted["income_records"][0]["redacted"] is True
    assert all(
        revision["received_amount_minor"] is None
        for revision in revealed_after["income_records"][0]["revisions"]
    )
    with sessions() as database:
        event_payloads = [
            item.payload_json
            for item in database.scalars(
                select(ExperimentEvent).where(ExperimentEvent.experiment_id == experiment["id"])
            ).all()
        ]
    assert all("100000" not in payload for payload in event_payloads)
    assert all("98000" not in payload for payload in event_payloads)


def test_gate_regression_pauses_active_experiment_and_feedback_never_mutates_plan(
    tmp_path: Path,
) -> None:
    experiments, sessions, run, goal = _create_fixture(tmp_path)
    _set_evidence(sessions, run["id"], action_ready=False)
    experiment = experiments.create_experiment(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_research_run_id=None,
        plan=_plan(),
    )
    original_plan = experiment["plan"]
    experiment = experiments.transition(experiment["id"], action="approve", confirm=True)
    experiment = experiments.transition(experiment["id"], action="start", confirm=True)
    with pytest.raises(ExperimentError) as caught:
        experiments.transition(experiment["id"], action="complete", confirm=True)
    assert caught.value.code == "experiment_outcome_required"
    outcome_added = experiments.record_outcome(
        experiment["id"],
        hypothesis_result="inconclusive",
        observable_result="作品说明仍缺少迁移场景的外部反馈。",
        learning_gap_dimension="transfer",
    )
    outcome_id = outcome_added["outcomes"][0]["id"]
    feedback_added = experiments.create_feedback(
        experiment["id"],
        outcome_id=outcome_id,
        suggestion_type="project",
        reason="补充一个陌生需求变化场景并再次取得外部评审。",
        evidence_refs=[f"outcome:{outcome_id}"],
        estimated_minutes=90,
        plan_impact="只生成待确认建议。不自动修改学习计划。",
    )
    feedback_id = feedback_added["feedback_suggestions"][0]["id"]
    decided = experiments.decide_feedback(
        experiment["id"],
        feedback_id,
        decision="accepted",
        note="稍后由用户决定是否调整学习计划。",
    )
    assert decided["feedback_suggestions"][0]["auto_applied"] is False
    assert decided["plan"] == original_plan

    _set_evidence(
        sessions,
        run["id"],
        action_ready=False,
        blocking_flag="source_review_pending",
    )
    paused = experiments.reevaluate_gate(experiment["id"])
    assert paused["status"] == "paused"
    assert paused["gate_level"] == "draft_only"
    assert any(
        code.startswith("review_flag_blocking:artifact") for code in paused["gate_reason_codes"]
    )


def test_0010_migration_upgrades_and_downgrades_cleanly(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(REPOSITORY_ROOT / "apps" / "api" / "migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url",
        create_database_url(database_path).replace("%", "%%"),
    )
    command.upgrade(config, "0009")
    command.upgrade(config, "head")
    assert read_schema_version(database_path) == "0010"
    engine = create_database_engine(database_path)
    try:
        assert "monetization_experiments" in inspect(engine).get_table_names()
        assert "experiment_income_revisions" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.downgrade(config, "0009")
    engine = create_database_engine(database_path)
    try:
        assert "monetization_experiments" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_experiment_api_rejects_disabled_path_before_external_action(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = tmp_path / "experiments-api.db"
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(database_path))
    payload = {
        "goal_selection_id": "not-used",
        "learning_run_id": "not-used",
        "market_research_run_id": None,
        "plan": _plan("freelancing"),
    }
    with TestClient(app) as client:
        response = client.post("/experiments", json=payload)
        listed = client.get("/experiments")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "path_not_enabled"
    assert listed.status_code == 200
    assert listed.json() == []
