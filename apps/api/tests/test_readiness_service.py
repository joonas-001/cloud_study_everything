import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pytest import MonkeyPatch
from sqlalchemy import select

from cloud_study_api.credentials import MemoryCredentialStore
from cloud_study_api.database import create_session_factory, upgrade_database
from cloud_study_api.diagnostics import DiagnosticService
from cloud_study_api.execution import LearningExecutionService
from cloud_study_api.governance import validate_repository
from cloud_study_api.learning import LearningService
from cloud_study_api.main import app
from cloud_study_api.models import MasterySnapshot, PathComparison
from cloud_study_api.notifications import NotificationService
from cloud_study_api.readiness import ReadinessError, ReadinessService

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DIMENSIONS = (
    "understanding",
    "operation",
    "transfer",
    "artifact",
    "retention",
    "correction",
)


def _contract_errors(name: str, value: dict[str, Any]) -> list[str]:
    schema = json.loads(
        (REPOSITORY_ROOT / "contracts" / "readiness" / name).read_text(encoding="utf-8")
    )
    serialized = json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
        )
    )
    return [error.message for error in Draft202012Validator(schema).iter_errors(serialized)]


def _assert_contract(name: str, value: dict[str, Any]) -> None:
    assert _contract_errors(name, value) == []


def _services(
    tmp_path: Path,
) -> tuple[
    DiagnosticService,
    LearningService,
    LearningExecutionService,
    ReadinessService,
    Any,
]:
    database_path = tmp_path / "readiness.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    packages = [
        replace(package, intake="open") if package.version == "0.2.0" else package
        for package in validate_repository(REPOSITORY_ROOT)
    ]

    def now() -> datetime:
        return datetime(2026, 7, 29, 8, 0, tzinfo=UTC)

    diagnostics = DiagnosticService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        now=now,
    )
    notifications = NotificationService(
        session_factory=session_factory,
        credential_store=MemoryCredentialStore(),
        now=now,
    )
    learning = LearningService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        notification_service=notifications,
        now=now,
    )
    execution = LearningExecutionService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        now=now,
    )
    readiness = ReadinessService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        now=now,
    )
    return diagnostics, learning, execution, readiness, session_factory


def _create_run(
    diagnostics: DiagnosticService,
    learning: LearningService,
    execution: LearningExecutionService,
) -> dict[str, Any]:
    diagnostic = diagnostics.create_session(
        skill_id="algorithm",
        skill_version="0.2.0",
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
        code_execution=False,
        external_ai=False,
        confirm_historical_plan=True,
        reuse_from_run_id=None,
        confirm_reuse=False,
    )


def _set_complete_evidence(session_factory: Any, run_id: str, flag: str | None = None) -> None:
    now = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
    with session_factory() as database:
        rows = {
            row.dimension: row
            for row in database.scalars(
                select(MasterySnapshot).where(MasterySnapshot.run_id == run_id)
            ).all()
        }
        for dimension in DIMENSIONS:
            row = rows.get(dimension)
            if row is None:
                row = MasterySnapshot(
                    id=f"snapshot-{dimension}",
                    run_id=run_id,
                    dimension=dimension,
                    evidence_level="supported",
                    review_flags_json="[]",
                    evidence_count=1,
                    updated_at=now,
                )
                database.add(row)
            else:
                row.evidence_level = "supported"
                row.evidence_count = 1
                row.review_flags_json = f'["{flag}"]' if flag else "[]"
                row.updated_at = now
        database.commit()


def _goal(readiness: ReadinessService, run_id: str, goal_kind: str) -> dict[str, Any]:
    scope = next(item for item in readiness.list_scopes() if item["learning_run_id"] == run_id)
    return readiness.select_goal(
        skill_id=scope["skill_id"],
        skill_version=scope["skill_version"],
        capability_scope_id=scope["capability_scope_id"],
        goal_kind=goal_kind,
        custom_label=None,
    )


def _snapshot(readiness: ReadinessService, freshness: str) -> dict[str, Any]:
    return next(
        item for item in readiness.list_market_snapshots() if item["freshness_status"] == freshness
    )


def test_non_monetization_goal_is_not_forced_into_market_comparison(
    tmp_path: Path,
) -> None:
    diagnostics, learning, execution, readiness, _session_factory = _services(tmp_path)
    run = _create_run(diagnostics, learning, execution)
    goal = _goal(readiness, run["id"], "exam")

    evaluation = readiness.evaluate(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_snapshot_id=None,
    )

    assert goal["market_comparison_applicable"] is False
    assert evaluation["status"] == "not_applicable"
    assert evaluation["reason_codes"] == ["goal_not_monetization"]
    assert evaluation["market_snapshot_id"] is None
    _assert_contract("user-goal.schema.json", goal)
    _assert_contract("readiness-evaluation.schema.json", evaluation)
    invalid_goal = {**goal, "market_comparison_applicable": True}
    assert _contract_errors("user-goal.schema.json", invalid_goal)
    try:
        readiness.create_comparison(evaluation["id"])
    except ReadinessError as error:
        assert error.code == "comparison_not_allowed"
    else:
        raise AssertionError("non-monetization goal unexpectedly created a comparison")


def test_replacing_current_goal_releases_partial_unique_index_before_insert(
    tmp_path: Path,
) -> None:
    diagnostics, learning, execution, readiness, _session_factory = _services(tmp_path)
    run = _create_run(diagnostics, learning, execution)
    scope = readiness.list_scopes()[0]
    first = readiness.select_goal(
        skill_id=run["skill_id"],
        skill_version=run["skill_version"],
        capability_scope_id=scope["capability_scope_id"],
        goal_kind="employment",
        custom_label=None,
    )

    replacement = readiness.select_goal(
        skill_id=run["skill_id"],
        skill_version=run["skill_version"],
        capability_scope_id=scope["capability_scope_id"],
        goal_kind="exam",
        custom_label=None,
    )

    current = readiness.get_current_goal(
        run["skill_id"],
        run["skill_version"],
        scope["capability_scope_id"],
    )
    assert replacement["id"] != first["id"]
    assert replacement["goal_kind"] == "exam"
    assert current is not None
    assert current["id"] == replacement["id"]


def test_real_evidence_can_only_create_a_synthetic_local_comparison(
    tmp_path: Path,
) -> None:
    diagnostics, learning, execution, readiness, session_factory = _services(tmp_path)
    run = _create_run(diagnostics, learning, execution)
    _set_complete_evidence(session_factory, run["id"])
    goal = _goal(readiness, run["id"], "employment")
    snapshot = _snapshot(readiness, "current")

    first = readiness.evaluate(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_snapshot_id=snapshot["id"],
    )
    second = readiness.evaluate(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_snapshot_id=snapshot["id"],
    )
    comparison = readiness.create_comparison(first["id"])
    accepted = readiness.decide_comparison(
        comparison["id"],
        decision="accepted",
        reason="仅接受本地比较。不代表投递或交易。",
    )
    deferred = readiness.decide_comparison(
        comparison["id"],
        decision="deferred",
        reason=None,
    )
    history = readiness.get_history(goal["id"])

    assert first["status"] == "comparison_ready"
    assert first["status"] != "experiment_ready"
    assert first["input_sha256"] == second["input_sha256"]
    assert first["id"] != second["id"]
    assert comparison["synthetic"] is True
    assert len(comparison["paths"]) == 3
    assert comparison["paths"][0]["evidence_gaps"]
    assert accepted["revision"] == 1
    assert deferred["revision"] == 2
    assert len(history["evaluations"]) == 2
    assert len(history["comparisons"]) == 1
    assert [item["decision"] for item in history["comparisons"][0]["decisions"]] == [
        "accepted",
        "deferred",
    ]
    _assert_contract("readiness-evaluation.schema.json", first)
    with session_factory() as database:
        stored_comparison = database.get(PathComparison, comparison["id"])
        assert stored_comparison is not None
        _assert_contract(
            "path-comparison.schema.json",
            json.loads(stored_comparison.comparison_json),
        )


def test_missing_evidence_and_review_inputs_block_comparison(tmp_path: Path) -> None:
    diagnostics, learning, execution, readiness, session_factory = _services(tmp_path)
    run = _create_run(diagnostics, learning, execution)
    goal = _goal(readiness, run["id"], "freelancing")
    current = _snapshot(readiness, "current")

    insufficient = readiness.evaluate(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_snapshot_id=current["id"],
    )
    assert insufficient["status"] == "not_ready"
    assert any(
        code.startswith("evidence_dimension_missing:") for code in insufficient["reason_codes"]
    )

    _set_complete_evidence(session_factory, run["id"], "source_review_pending")
    review_required = readiness.evaluate(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_snapshot_id=current["id"],
    )
    assert review_required["status"] == "review_required"
    assert "review_flag_blocking:source_review_pending" in review_required["reason_codes"]

    _set_complete_evidence(session_factory, run["id"])
    stale = _snapshot(readiness, "stale")
    stale_result = readiness.evaluate(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_snapshot_id=stale["id"],
    )
    assert stale_result["status"] == "review_required"
    assert stale_result["reason_codes"] == ["market_snapshot_stale"]


def test_policy_and_fixture_versions_reject_in_place_content_changes(tmp_path: Path) -> None:
    diagnostics, learning, execution, readiness, _session_factory = _services(tmp_path)
    run = _create_run(diagnostics, learning, execution)
    goal = _goal(readiness, run["id"], "learning")
    readiness.evaluate(
        goal_selection_id=goal["id"],
        learning_run_id=run["id"],
        market_snapshot_id=None,
    )
    readiness.list_market_snapshots()

    readiness._policy["limitations"].append("同版本策略内容不应被原地修改。")
    try:
        readiness.evaluate(
            goal_selection_id=goal["id"],
            learning_run_id=run["id"],
            market_snapshot_id=None,
        )
    except ReadinessError as error:
        assert error.code == "readiness_policy_version_conflict"
    else:
        raise AssertionError("changed policy content unexpectedly reused the same version")

    readiness._fixtures[0]["label"] = "同版本夹具内容不应被原地修改"
    try:
        readiness.list_market_snapshots()
    except ReadinessError as error:
        assert error.code == "market_fixture_version_conflict"
    else:
        raise AssertionError("changed fixture content unexpectedly reused the same version")


def test_readiness_api_exposes_only_local_deterministic_5a(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = tmp_path / "readiness-api.db"
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(database_path))

    with TestClient(app) as client:
        snapshots = client.get("/readiness/market-snapshots")
        goal = client.post(
            "/readiness/goals",
            json={
                "skill_id": "algorithm",
                "skill_version": "0.2.0",
                "capability_scope_id": "algorithm-entry-mastery-scope",
                "goal_kind": "learning",
                "custom_label": None,
            },
        )
        evaluation = client.post(
            "/readiness/evaluations",
            json={
                "goal_selection_id": goal.json()["id"],
                "learning_run_id": None,
                "market_snapshot_id": None,
            },
        )

    assert snapshots.status_code == 200
    assert len(snapshots.json()) == 4
    assert all(item["synthetic"] is True for item in snapshots.json())
    assert goal.status_code == 201
    assert evaluation.status_code == 201
    assert evaluation.json()["status"] == "not_applicable"
