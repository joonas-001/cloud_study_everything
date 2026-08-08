from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.governance import SkillPackage
from cloud_study_api.models import (
    ExperimentActionRecord,
    ExperimentEvent,
    ExperimentFeedbackSuggestion,
    ExperimentIncomeRecord,
    ExperimentIncomeRevision,
    ExperimentIndependentReview,
    ExperimentOutcome,
    ExperimentPolicySnapshot,
    LearningRun,
    MarketResearchRun,
    MasterySnapshot,
    MonetizationExperiment,
    UserGoalSelection,
    utc_now,
)

TERMINAL_STATUSES = {"rejected", "ended", "completed"}
DIMENSIONS = {
    "understanding",
    "operation",
    "transfer",
    "artifact",
    "retention",
    "correction",
}
EVIDENCE_RANK = {
    "none": 0,
    "limited": 1,
    "supported": 2,
    "verified": 3,
    "retained": 4,
}


class ExperimentError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.context = context or {}


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class ExperimentService:
    def __init__(
        self,
        repository_root: Path,
        packages: list[SkillPackage],
        session_factory: sessionmaker[Session],
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository_root = repository_root
        self._packages = {(item.package_id, item.version): item for item in packages}
        self._session_factory = session_factory
        self._now = now
        self._policy = self._load_json(
            repository_root / "readiness" / "policies" / "employment-experiment-v2.json"
        )
        self._plan_validator = self._validator(
            repository_root / "contracts" / "readiness" / "experiment-plan.schema.json"
        )
        self._review_validator = self._validator(
            repository_root / "contracts" / "readiness" / "independent-review.schema.json"
        )
        self._income_validator = self._validator(
            repository_root / "contracts" / "readiness" / "income-revision.schema.json"
        )
        self._feedback_validator = self._validator(
            repository_root / "contracts" / "readiness" / "learning-feedback.schema.json"
        )

    def create_experiment(
        self,
        *,
        goal_selection_id: str,
        learning_run_id: str,
        market_research_run_id: str | None,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate(self._plan_validator, plan, "invalid_experiment_plan")
        if plan["path"] not in self._policy["enabled_paths"]:
            raise ExperimentError(
                422,
                "path_not_enabled",
                "5C 首版只启用就业路径。接单和产品化仍保持关闭。",
            )
        now = self._now()
        with self._session_factory() as database:
            goal = self._active_goal(database, goal_selection_id)
            run = database.get(LearningRun, learning_run_id)
            if run is None:
                raise ExperimentError(404, "learning_run_not_found", "学习记录不存在。")
            if goal.goal_kind != "employment":
                raise ExperimentError(
                    422,
                    "goal_not_employment",
                    "5C 首版只能为用户明确选择的就业目标创建实验。",
                )
            if (
                run.skill_id != goal.skill_id
                or run.skill_version != goal.skill_version
                or goal.capability_scope_id != self._scope_id(run.skill_id, run.skill_version)
            ):
                raise ExperimentError(
                    422,
                    "learning_run_scope_mismatch",
                    "学习记录、目标和受管能力范围不一致。",
                )
            package = self._package(run.skill_id, run.skill_version)
            policy = self._ensure_policy_snapshot(database)
            market = self._market(database, market_research_run_id)
            experiment = MonetizationExperiment(
                id=str(uuid4()),
                goal_selection_id=goal.id,
                learning_run_id=run.id,
                market_research_run_id=market.id if market is not None else None,
                policy_snapshot_id=policy.id,
                skill_id=run.skill_id,
                skill_version=run.skill_version,
                skill_manifest_sha256=package.manifest_sha256,
                capability_scope_id=goal.capability_scope_id,
                path=plan["path"],
                title=plan["title"],
                target_audience=plan["target_audience"],
                hypothesis=plan["hypothesis"],
                planned_action=plan["planned_action"],
                success_metric=plan["success_metric"],
                time_budget_minutes=plan["time_budget_minutes"],
                cost_cap_minor=plan["cost_cap_minor"],
                plan_json=_canonical_json(plan),
                status="draft",
                gate_level="draft_only",
                gate_reasons_json="[]",
                evidence_snapshot_json="{}",
                evidence_sha256=_sha256({}),
                created_at=now,
                updated_at=now,
                approved_at=None,
                started_at=None,
                ended_at=None,
            )
            database.add(experiment)
            database.flush()
            self._refresh_gate(database, experiment, now)
            self._event(
                database,
                experiment.id,
                "experiment_created",
                {
                    "path": experiment.path,
                    "policy_id": policy.policy_id,
                    "policy_version": policy.policy_version,
                    "gate_level": experiment.gate_level,
                    "external_action_mode": "manual_record_only",
                },
                now,
            )
            database.commit()
            return self._payload(database, experiment)

    def list_experiments(self, goal_selection_id: str | None = None) -> list[dict[str, Any]]:
        with self._session_factory() as database:
            query = select(MonetizationExperiment).order_by(
                MonetizationExperiment.created_at.desc()
            )
            if goal_selection_id:
                query = query.where(MonetizationExperiment.goal_selection_id == goal_selection_id)
            return [self._payload(database, item) for item in database.scalars(query).all()]

    def get_experiment(
        self,
        experiment_id: str,
        *,
        reveal_income: bool = False,
    ) -> dict[str, Any]:
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            return self._payload(database, experiment, reveal_income=reveal_income)

    def add_independent_review(
        self,
        experiment_id: str,
        *,
        dimension: str,
        reviewer_relationship: str,
        review_scope: str,
        rubric_id: str,
        rubric_version: str,
        conclusion: str,
        reviewed_at: datetime,
    ) -> dict[str, Any]:
        self._validate(
            self._review_validator,
            {
                "schema_version": "1.0.0",
                "dimension": dimension,
                "reviewer_relationship": reviewer_relationship,
                "review_scope": review_scope,
                "rubric_id": rubric_id,
                "rubric_version": rubric_version,
                "conclusion": conclusion,
                "reviewed_at": reviewed_at.isoformat(),
            },
            "invalid_independent_review",
        )
        now = self._now()
        if self._utc_timestamp(reviewed_at) > self._utc_timestamp(now):
            raise ExperimentError(
                422,
                "independent_review_future_dated",
                "真人评审日期不能晚于当前时间。",
            )
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            self._ensure_not_terminal(experiment)
            expected_rubric = self._policy["external_action_gate"]["independent_review_rubrics"][
                dimension
            ]
            if review_scope != experiment.capability_scope_id:
                raise ExperimentError(
                    422,
                    "independent_review_scope_mismatch",
                    "真人评审必须精确绑定当前实验的受管能力范围。",
                )
            if {
                "rubric_id": rubric_id,
                "rubric_version": rubric_version,
            } != expected_rubric:
                raise ExperimentError(
                    422,
                    "independent_review_rubric_unapproved",
                    "真人评审量表不属于当前策略允许的受管量表。",
                )
            review = ExperimentIndependentReview(
                id=str(uuid4()),
                experiment_id=experiment.id,
                dimension=dimension,
                reviewer_relationship=reviewer_relationship,
                review_scope=review_scope,
                rubric_id=rubric_id,
                rubric_version=rubric_version,
                conclusion=conclusion,
                reviewed_at=reviewed_at,
                created_at=now,
            )
            database.add(review)
            database.flush()
            self._refresh_gate(database, experiment, now)
            self._event(
                database,
                experiment.id,
                "independent_review_recorded",
                {
                    "review_id": review.id,
                    "dimension": dimension,
                    "reviewer_relationship": reviewer_relationship,
                    "rubric_id": rubric_id,
                    "rubric_version": rubric_version,
                    "conclusion": conclusion,
                },
                now,
            )
            database.commit()
            return self._payload(database, experiment)

    def reevaluate_gate(self, experiment_id: str) -> dict[str, Any]:
        now = self._now()
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            old_gate = experiment.gate_level
            old_status = experiment.status
            self._refresh_gate(database, experiment, now)
            if experiment.gate_level in {"draft_only", "blocked"}:
                if experiment.status == "active":
                    experiment.status = "paused"
                elif experiment.status == "approved":
                    experiment.status = "blocked"
            self._event(
                database,
                experiment.id,
                "experiment_gate_reevaluated",
                {
                    "old_gate": old_gate,
                    "new_gate": experiment.gate_level,
                    "old_status": old_status,
                    "new_status": experiment.status,
                    "reason_codes": json.loads(experiment.gate_reasons_json),
                },
                now,
            )
            database.commit()
            return self._payload(database, experiment)

    def transition(
        self,
        experiment_id: str,
        *,
        action: str,
        confirm: bool,
    ) -> dict[str, Any]:
        if not confirm:
            raise ExperimentError(
                422,
                "explicit_confirmation_required",
                "状态变更必须由用户明确确认。",
            )
        now = self._now()
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            old_status = experiment.status
            if action == "approve":
                if old_status not in {"draft", "blocked"}:
                    self._invalid_transition(old_status, action)
                self._refresh_gate(database, experiment, now)
                if experiment.gate_level not in {"local_ready", "action_ready"}:
                    experiment.status = "blocked"
                else:
                    experiment.status = "approved"
                    experiment.approved_at = now
            elif action == "start":
                if old_status != "approved":
                    self._invalid_transition(old_status, action)
                self._refresh_gate(database, experiment, now)
                if experiment.gate_level not in {"local_ready", "action_ready"}:
                    experiment.status = "blocked"
                else:
                    experiment.status = "active"
                    experiment.started_at = now
            elif action == "pause":
                if old_status not in {"approved", "active"}:
                    self._invalid_transition(old_status, action)
                experiment.status = "paused"
            elif action == "resume":
                if old_status != "paused":
                    self._invalid_transition(old_status, action)
                self._refresh_gate(database, experiment, now)
                if experiment.gate_level not in {"local_ready", "action_ready"}:
                    raise ExperimentError(
                        409,
                        "experiment_gate_not_ready",
                        "当前证据门禁不允许恢复实验。",
                        {"reason_codes": json.loads(experiment.gate_reasons_json)},
                    )
                experiment.status = "active"
            elif action == "complete":
                if old_status not in {"active", "paused"}:
                    self._invalid_transition(old_status, action)
                outcome_exists = database.scalar(
                    select(ExperimentOutcome.id)
                    .where(ExperimentOutcome.experiment_id == experiment.id)
                    .limit(1)
                )
                if outcome_exists is None:
                    raise ExperimentError(
                        409,
                        "experiment_outcome_required",
                        "完成实验前必须记录至少一项可观察结果。",
                    )
                experiment.status = "completed"
                experiment.ended_at = now
            elif action == "end":
                if old_status in TERMINAL_STATUSES:
                    self._invalid_transition(old_status, action)
                experiment.status = "ended"
                experiment.ended_at = now
            elif action == "reject":
                if old_status not in {"draft", "blocked"}:
                    self._invalid_transition(old_status, action)
                experiment.status = "rejected"
                experiment.ended_at = now
            else:
                raise ExperimentError(422, "invalid_transition_action", "不支持的状态动作。")
            experiment.updated_at = now
            self._event(
                database,
                experiment.id,
                "experiment_state_changed",
                {
                    "action": action,
                    "old_status": old_status,
                    "new_status": experiment.status,
                    "gate_level": experiment.gate_level,
                },
                now,
            )
            database.commit()
            return self._payload(database, experiment)

    def record_external_action(
        self,
        experiment_id: str,
        *,
        action_kind: str,
        description: str,
        result: str,
        occurred_at: datetime,
        confirm_completed_outside_product: bool,
    ) -> dict[str, Any]:
        if not confirm_completed_outside_product:
            raise ExperimentError(
                422,
                "external_action_confirmation_required",
                "只能记录用户已在产品外手动完成的动作。",
            )
        now = self._now()
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            old_status = experiment.status
            self._refresh_gate(database, experiment, now)
            if experiment.status != "active":
                if experiment.status != old_status:
                    self._event(
                        database,
                        experiment.id,
                        "experiment_paused_after_gate_regression",
                        {
                            "old_status": old_status,
                            "new_status": experiment.status,
                            "gate_level": experiment.gate_level,
                            "reason_codes": json.loads(experiment.gate_reasons_json),
                        },
                        now,
                    )
                    database.commit()
                raise ExperimentError(
                    409,
                    "experiment_not_active",
                    "只有进行中的实验可以记录真实求职动作。",
                )
            if experiment.gate_level != "action_ready":
                raise ExperimentError(
                    409,
                    "external_action_gate_not_ready",
                    "真实求职动作门禁尚未满足。",
                    {"reason_codes": json.loads(experiment.gate_reasons_json)},
                )
            item = ExperimentActionRecord(
                id=str(uuid4()),
                experiment_id=experiment.id,
                action_kind=action_kind,
                description=description,
                result=result,
                user_confirmed_external=True,
                occurred_at=occurred_at,
                created_at=now,
            )
            database.add(item)
            self._event(
                database,
                experiment.id,
                "external_action_recorded",
                {
                    "action_id": item.id,
                    "action_kind": action_kind,
                    "result": result,
                    "execution_mode": "completed_outside_product",
                },
                now,
            )
            database.commit()
            return self._payload(database, experiment)

    def record_outcome(
        self,
        experiment_id: str,
        *,
        hypothesis_result: str,
        observable_result: str,
        learning_gap_dimension: str | None,
    ) -> dict[str, Any]:
        if learning_gap_dimension is not None and learning_gap_dimension not in DIMENSIONS:
            raise ExperimentError(422, "invalid_gap_dimension", "不支持的学习缺口维度。")
        now = self._now()
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            if experiment.status not in {"active", "paused", "completed"}:
                raise ExperimentError(
                    409,
                    "outcome_status_invalid",
                    "实验开始后才能记录可观察结果。",
                )
            item = ExperimentOutcome(
                id=str(uuid4()),
                experiment_id=experiment.id,
                hypothesis_result=hypothesis_result,
                observable_result=observable_result,
                learning_gap_dimension=learning_gap_dimension,
                recorded_at=now,
            )
            database.add(item)
            self._event(
                database,
                experiment.id,
                "experiment_outcome_recorded",
                {
                    "outcome_id": item.id,
                    "hypothesis_result": hypothesis_result,
                    "learning_gap_dimension": learning_gap_dimension,
                },
                now,
            )
            database.commit()
            return self._payload(database, experiment)

    def create_income(
        self,
        experiment_id: str,
        *,
        values: dict[str, Any],
        confirm_manual_record: bool,
    ) -> dict[str, Any]:
        if not confirm_manual_record:
            raise ExperimentError(
                422,
                "income_confirmation_required",
                "收入只能由用户明确确认后手动记录。",
            )
        self._validate(
            self._income_validator,
            {"schema_version": "1.0.0", **values},
            "invalid_income_revision",
        )
        now = self._now()
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            if experiment.status not in {"active", "paused", "completed", "ended"}:
                raise ExperimentError(
                    409,
                    "income_status_invalid",
                    "实验开始后才能记录可选收入。",
                )
            action_exists = database.scalar(
                select(ExperimentActionRecord.id)
                .where(ExperimentActionRecord.experiment_id == experiment.id)
                .limit(1)
            )
            if action_exists is None:
                raise ExperimentError(
                    409,
                    "income_action_record_required",
                    "收入记录必须关联至少一条已在产品外完成的动作记录。",
                )
            record = ExperimentIncomeRecord(
                id=str(uuid4()),
                experiment_id=experiment.id,
                current_revision=1,
                redacted=False,
                created_at=now,
                updated_at=now,
                redacted_at=None,
            )
            database.add(record)
            database.flush()
            revision = self._income_revision(record.id, 1, values, now)
            database.add(revision)
            self._event(
                database,
                experiment.id,
                "income_record_created",
                {
                    "income_record_id": record.id,
                    "revision": 1,
                    "currency": values["currency"],
                    "verification_level": values["verification_level"],
                    "amounts_stored_locally": True,
                },
                now,
            )
            database.commit()
            return self._payload(database, experiment)

    def revise_income(
        self,
        experiment_id: str,
        income_record_id: str,
        *,
        values: dict[str, Any],
        confirm_revision: bool,
    ) -> dict[str, Any]:
        if not confirm_revision:
            raise ExperimentError(
                422,
                "income_revision_confirmation_required",
                "收入修订必须由用户明确确认。",
            )
        self._validate(
            self._income_validator,
            {"schema_version": "1.0.0", **values},
            "invalid_income_revision",
        )
        now = self._now()
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            record = database.get(ExperimentIncomeRecord, income_record_id)
            if record is None or record.experiment_id != experiment.id or record.redacted:
                raise ExperimentError(404, "income_record_not_found", "收入记录不存在。")
            record.current_revision += 1
            record.updated_at = now
            database.add(
                self._income_revision(
                    record.id,
                    record.current_revision,
                    values,
                    now,
                )
            )
            self._event(
                database,
                experiment.id,
                "income_record_revised",
                {
                    "income_record_id": record.id,
                    "revision": record.current_revision,
                    "currency": values["currency"],
                    "verification_level": values["verification_level"],
                },
                now,
            )
            database.commit()
            return self._payload(database, experiment)

    def redact_income(
        self,
        experiment_id: str,
        income_record_id: str,
        *,
        confirm_redaction: bool,
    ) -> dict[str, Any]:
        if not confirm_redaction:
            raise ExperimentError(
                422,
                "income_redaction_confirmation_required",
                "清除收入敏感值必须由用户明确确认。",
            )
        now = self._now()
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            record = database.get(ExperimentIncomeRecord, income_record_id)
            if record is None or record.experiment_id != experiment.id:
                raise ExperimentError(404, "income_record_not_found", "收入记录不存在。")
            if not record.redacted:
                revisions = database.scalars(
                    select(ExperimentIncomeRevision).where(
                        ExperimentIncomeRevision.income_record_id == record.id
                    )
                ).all()
                for revision in revisions:
                    revision.currency = None
                    revision.amount_basis = None
                    revision.gross_amount_minor = None
                    revision.platform_fee_minor = None
                    revision.direct_cost_minor = None
                    revision.received_amount_minor = None
                    revision.verification_level = None
                    revision.note = None
                    revision.occurred_on = None
                record.redacted = True
                record.redacted_at = now
                record.updated_at = now
                self._event(
                    database,
                    experiment.id,
                    "income_record_redacted",
                    {
                        "income_record_id": record.id,
                        "revision_count": len(revisions),
                        "sensitive_values_retained": False,
                    },
                    now,
                )
            database.commit()
            return self._payload(database, experiment)

    def create_feedback(
        self,
        experiment_id: str,
        *,
        outcome_id: str | None,
        suggestion_type: str,
        reason: str,
        evidence_refs: list[str],
        estimated_minutes: int,
        plan_impact: str,
    ) -> dict[str, Any]:
        self._validate(
            self._feedback_validator,
            {
                "schema_version": "1.0.0",
                "suggestion_type": suggestion_type,
                "reason": reason,
                "evidence_refs": evidence_refs,
                "estimated_minutes": estimated_minutes,
                "plan_impact": plan_impact,
            },
            "invalid_learning_feedback",
        )
        now = self._now()
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            if outcome_id is not None:
                outcome = database.get(ExperimentOutcome, outcome_id)
                if outcome is None or outcome.experiment_id != experiment.id:
                    raise ExperimentError(
                        422,
                        "feedback_outcome_mismatch",
                        "回流建议引用的结果不属于当前实验。",
                    )
            item = ExperimentFeedbackSuggestion(
                id=str(uuid4()),
                experiment_id=experiment.id,
                outcome_id=outcome_id,
                suggestion_type=suggestion_type,
                reason=reason,
                evidence_refs_json=_canonical_json(evidence_refs),
                estimated_minutes=estimated_minutes,
                plan_impact=plan_impact,
                status="pending",
                decision_note=None,
                created_at=now,
                decided_at=None,
            )
            database.add(item)
            self._event(
                database,
                experiment.id,
                "learning_feedback_suggested",
                {
                    "feedback_id": item.id,
                    "suggestion_type": suggestion_type,
                    "estimated_minutes": estimated_minutes,
                    "auto_applied": False,
                },
                now,
            )
            database.commit()
            return self._payload(database, experiment)

    def decide_feedback(
        self,
        experiment_id: str,
        feedback_id: str,
        *,
        decision: str,
        note: str | None,
    ) -> dict[str, Any]:
        if decision not in {"accepted", "rejected", "withdrawn"}:
            raise ExperimentError(422, "invalid_feedback_decision", "不支持的回流决定。")
        now = self._now()
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            item = database.get(ExperimentFeedbackSuggestion, feedback_id)
            if item is None or item.experiment_id != experiment.id or item.status != "pending":
                raise ExperimentError(404, "pending_feedback_not_found", "待处理回流建议不存在。")
            item.status = decision
            item.decision_note = note
            item.decided_at = now
            self._event(
                database,
                experiment.id,
                "learning_feedback_decided",
                {
                    "feedback_id": item.id,
                    "decision": decision,
                    "learning_plan_modified": False,
                },
                now,
            )
            database.commit()
            return self._payload(database, experiment)

    def export_experiment(
        self,
        experiment_id: str,
        *,
        export_format: str,
        confirm_sensitive_export: bool,
    ) -> tuple[str, str]:
        if not confirm_sensitive_export:
            raise ExperimentError(
                422,
                "sensitive_export_confirmation_required",
                "导出可能包含本地收入敏感值。必须明确确认。",
            )
        with self._session_factory() as database:
            experiment = self._experiment(database, experiment_id)
            payload = self._payload(database, experiment, reveal_income=True)
            self._event(
                database,
                experiment.id,
                "experiment_exported",
                {
                    "format": export_format,
                    "sensitive_export_confirmed": True,
                },
                self._now(),
            )
            database.commit()
        if export_format == "json":
            return (
                "application/json; charset=utf-8",
                json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            )
        if export_format != "csv":
            raise ExperimentError(422, "invalid_export_format", "只支持 JSON 或 CSV 导出。")
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["section", "id", "field", "value"])
        writer.writerow(["experiment", payload["id"], "status", payload["status"]])
        writer.writerow(["experiment", payload["id"], "gate_level", payload["gate_level"]])
        for action in payload["actions"]:
            writer.writerow(["action", action["id"], "result", action["result"]])
        for outcome in payload["outcomes"]:
            writer.writerow(
                ["outcome", outcome["id"], "hypothesis_result", outcome["hypothesis_result"]]
            )
        for income in payload["income_records"]:
            for revision in income["revisions"]:
                for field in (
                    "currency",
                    "gross_amount_minor",
                    "platform_fee_minor",
                    "direct_cost_minor",
                    "received_amount_minor",
                    "verification_level",
                    "occurred_on",
                ):
                    writer.writerow(
                        [
                            "income",
                            income["id"],
                            f"r{revision['revision']}.{field}",
                            revision[field],
                        ]
                    )
        return ("text/csv; charset=utf-8", output.getvalue())

    def _refresh_gate(
        self,
        database: Session,
        experiment: MonetizationExperiment,
        now: datetime,
    ) -> None:
        snapshot, gate, reasons = self._gate(database, experiment, now)
        experiment.evidence_snapshot_json = _canonical_json(snapshot)
        experiment.evidence_sha256 = _sha256(snapshot)
        experiment.gate_level = gate
        experiment.gate_reasons_json = _canonical_json(reasons)
        if gate in {"draft_only", "blocked"}:
            if experiment.status == "active":
                experiment.status = "paused"
            elif experiment.status == "approved":
                experiment.status = "blocked"
        experiment.updated_at = now

    def _gate(
        self,
        database: Session,
        experiment: MonetizationExperiment,
        now: datetime,
    ) -> tuple[dict[str, Any], str, list[str]]:
        reasons: list[str] = []
        goal = database.get(UserGoalSelection, experiment.goal_selection_id)
        run = database.get(LearningRun, experiment.learning_run_id)
        package = self._packages.get((experiment.skill_id, experiment.skill_version))
        invariant_failed = False
        if experiment.path not in self._policy["enabled_paths"]:
            reasons.append("path_not_enabled")
            invariant_failed = True
        if goal is None or goal.goal_kind != "employment":
            reasons.append("goal_not_employment")
            invariant_failed = True
        elif goal.superseded_at is not None:
            reasons.append("goal_superseded")
            invariant_failed = True
        if (
            run is None
            or run.skill_id != experiment.skill_id
            or run.skill_version != experiment.skill_version
        ):
            reasons.append("skill_version_mismatch")
            invariant_failed = True
        if package is None or package.manifest_sha256 != experiment.skill_manifest_sha256:
            reasons.append("skill_manifest_mismatch")
            invariant_failed = True

        rows = (
            {}
            if run is None
            else {
                item.dimension: item
                for item in database.scalars(
                    select(MasterySnapshot).where(MasterySnapshot.run_id == run.id)
                ).all()
            }
        )
        dimensions = []
        local_ready = True
        temporal_blocked = False
        action_gate = self._policy["external_action_gate"]
        evidence_cutoff = now - timedelta(days=action_gate["evidence_max_age_days"])
        for dimension in self._policy["required_dimensions"]:
            row = rows.get(dimension)
            flags = [] if row is None else json.loads(row.review_flags_json)
            level = "none" if row is None else row.evidence_level
            count = 0 if row is None else row.evidence_count
            dimensions.append(
                {
                    "dimension": dimension,
                    "evidence_level": level,
                    "evidence_count": count,
                    "review_flags": flags,
                    "updated_at": None if row is None else row.updated_at.isoformat(),
                }
            )
            if count < self._policy["local_gate"]["minimum_evidence_count_per_dimension"]:
                reasons.append(f"evidence_dimension_missing:{dimension}")
                local_ready = False
            for flag in flags:
                if flag in self._policy["blocking_review_flags"]:
                    reasons.append(f"review_flag_blocking:{dimension}:{flag}")
                    local_ready = False
            if row is not None:
                evidence_timestamp = self._utc_timestamp(row.updated_at)
                if evidence_timestamp > self._utc_timestamp(now):
                    reasons.append(f"evidence_future_dated:{dimension}")
                    temporal_blocked = True
                elif evidence_timestamp < self._utc_timestamp(evidence_cutoff):
                    reasons.append(f"evidence_expired:{dimension}")
                    temporal_blocked = True

        reviews = database.scalars(
            select(ExperimentIndependentReview).where(
                ExperimentIndependentReview.experiment_id == experiment.id
            )
        ).all()
        latest_reviews: dict[str, ExperimentIndependentReview] = {}
        for item in reviews:
            previous = latest_reviews.get(item.dimension)
            if previous is None or (
                self._utc_timestamp(item.reviewed_at),
                self._utc_timestamp(item.created_at),
                item.id,
            ) > (
                self._utc_timestamp(previous.reviewed_at),
                self._utc_timestamp(previous.created_at),
                previous.id,
            ):
                latest_reviews[item.dimension] = item
        passed_review_dimensions: set[str] = set()
        review_cutoff = now - timedelta(days=action_gate["independent_review_max_age_days"])
        for dimension, item in latest_reviews.items():
            expected_rubric = action_gate["independent_review_rubrics"].get(dimension)
            if self._utc_timestamp(item.reviewed_at) > self._utc_timestamp(now):
                reasons.append(f"independent_review_future_dated:{dimension}")
                temporal_blocked = True
                continue
            if self._utc_timestamp(item.reviewed_at) < self._utc_timestamp(review_cutoff):
                reasons.append(f"independent_review_expired:{dimension}")
                temporal_blocked = True
                continue
            if item.review_scope != experiment.capability_scope_id:
                reasons.append(f"independent_review_scope_mismatch:{dimension}")
                continue
            if (
                expected_rubric is None
                or {
                    "rubric_id": item.rubric_id,
                    "rubric_version": item.rubric_version,
                }
                != expected_rubric
            ):
                reasons.append(f"independent_review_rubric_unapproved:{dimension}")
                continue
            if item.conclusion == "passed":
                passed_review_dimensions.add(dimension)
        operation_level = next(
            item["evidence_level"] for item in dimensions if item["dimension"] == "operation"
        )
        retention_level = next(
            item["evidence_level"] for item in dimensions if item["dimension"] == "retention"
        )
        action_ready = local_ready and not invariant_failed
        if EVIDENCE_RANK.get(operation_level, 0) < EVIDENCE_RANK["verified"]:
            reasons.append("operation_verified_required")
            action_ready = False
        if retention_level != "retained":
            reasons.append("retention_retained_required")
            action_ready = False
        for dimension in action_gate["independent_review_dimensions"]:
            if dimension not in passed_review_dimensions:
                reasons.append(f"independent_{dimension}_review_required")
                action_ready = False

        market = (
            None
            if experiment.market_research_run_id is None
            else database.get(MarketResearchRun, experiment.market_research_run_id)
        )
        market_payload: dict[str, Any] | None = None
        if market is None:
            reasons.append("market_review_missing")
            action_ready = False
        else:
            market_payload = {
                "id": market.id,
                "status": market.status,
                "review_status": market.review_status,
                "synthesis_invalidated": market.synthesis_invalidated_at is not None,
            }
            context_matches = (
                market.goal_selection_id == experiment.goal_selection_id
                and market.skill_id == experiment.skill_id
                and market.skill_version == experiment.skill_version
                and market.capability_scope_id == experiment.capability_scope_id
            )
            if not context_matches:
                reasons.append("market_research_context_mismatch")
                action_ready = False
            if (
                market.status != action_gate["accepted_market_status"]
                or market.review_status != action_gate["accepted_market_review_status"]
                or market.synthesis_invalidated_at is not None
            ):
                reasons.append("market_review_not_accepted")
                action_ready = False
            if market.completed_at is None:
                reasons.append("market_research_timestamp_missing")
                action_ready = False
                temporal_blocked = True
            else:
                market_completed_timestamp = self._utc_timestamp(market.completed_at)
                if market_completed_timestamp > self._utc_timestamp(now):
                    reasons.append("market_research_future_dated")
                    action_ready = False
                    temporal_blocked = True
                elif market_completed_timestamp < self._utc_timestamp(
                    now - timedelta(days=action_gate["market_max_age_days"])
                ):
                    reasons.append("market_research_expired")
                    action_ready = False
                    temporal_blocked = True

        if invariant_failed or temporal_blocked:
            gate = "blocked"
        elif not local_ready:
            gate = "draft_only"
        elif action_ready:
            gate = "action_ready"
            reasons.insert(0, "action_gate_satisfied")
        else:
            gate = "local_ready"
            reasons.insert(0, "local_gate_satisfied")
        snapshot = {
            "schema_version": "1.0.0",
            "learning_run_id": None if run is None else run.id,
            "learning_run_status": None if run is None else run.status,
            "skill_id": experiment.skill_id,
            "skill_version": experiment.skill_version,
            "skill_manifest_sha256": experiment.skill_manifest_sha256,
            "capability_scope_id": experiment.capability_scope_id,
            "dimensions": dimensions,
            "independent_reviews": [
                {
                    "id": item.id,
                    "dimension": item.dimension,
                    "reviewer_relationship": item.reviewer_relationship,
                    "rubric_id": item.rubric_id,
                    "rubric_version": item.rubric_version,
                    "conclusion": item.conclusion,
                    "reviewed_at": item.reviewed_at.isoformat(),
                }
                for item in reviews
            ],
            "market_research": market_payload,
        }
        return snapshot, gate, list(dict.fromkeys(reasons))

    def _payload(
        self,
        database: Session,
        experiment: MonetizationExperiment,
        *,
        reveal_income: bool = False,
    ) -> dict[str, Any]:
        policy = database.get(ExperimentPolicySnapshot, experiment.policy_snapshot_id)
        reviews = database.scalars(
            select(ExperimentIndependentReview)
            .where(ExperimentIndependentReview.experiment_id == experiment.id)
            .order_by(ExperimentIndependentReview.created_at)
        ).all()
        actions = database.scalars(
            select(ExperimentActionRecord)
            .where(ExperimentActionRecord.experiment_id == experiment.id)
            .order_by(ExperimentActionRecord.occurred_at)
        ).all()
        outcomes = database.scalars(
            select(ExperimentOutcome)
            .where(ExperimentOutcome.experiment_id == experiment.id)
            .order_by(ExperimentOutcome.recorded_at)
        ).all()
        income_records = database.scalars(
            select(ExperimentIncomeRecord)
            .where(ExperimentIncomeRecord.experiment_id == experiment.id)
            .order_by(ExperimentIncomeRecord.created_at)
        ).all()
        feedback = database.scalars(
            select(ExperimentFeedbackSuggestion)
            .where(ExperimentFeedbackSuggestion.experiment_id == experiment.id)
            .order_by(ExperimentFeedbackSuggestion.created_at)
        ).all()
        events = database.scalars(
            select(ExperimentEvent)
            .where(ExperimentEvent.experiment_id == experiment.id)
            .order_by(ExperimentEvent.occurred_at, ExperimentEvent.id)
        ).all()
        return {
            "schema_version": "1.0.0",
            "id": experiment.id,
            "goal_selection_id": experiment.goal_selection_id,
            "learning_run_id": experiment.learning_run_id,
            "market_research_run_id": experiment.market_research_run_id,
            "policy_id": "missing" if policy is None else policy.policy_id,
            "policy_version": "missing" if policy is None else policy.policy_version,
            "skill_id": experiment.skill_id,
            "skill_version": experiment.skill_version,
            "skill_manifest_sha256": experiment.skill_manifest_sha256,
            "capability_scope_id": experiment.capability_scope_id,
            "path": experiment.path,
            "plan": json.loads(experiment.plan_json),
            "status": experiment.status,
            "gate_level": experiment.gate_level,
            "gate_reason_codes": json.loads(experiment.gate_reasons_json),
            "evidence_snapshot": json.loads(experiment.evidence_snapshot_json),
            "evidence_sha256": experiment.evidence_sha256,
            "external_action_mode": "manual_record_only",
            "reviews": [
                {
                    "id": item.id,
                    "dimension": item.dimension,
                    "reviewer_relationship": item.reviewer_relationship,
                    "review_scope": item.review_scope,
                    "rubric_id": item.rubric_id,
                    "rubric_version": item.rubric_version,
                    "conclusion": item.conclusion,
                    "reviewed_at": item.reviewed_at,
                    "created_at": item.created_at,
                }
                for item in reviews
            ],
            "actions": [
                {
                    "id": item.id,
                    "action_kind": item.action_kind,
                    "description": item.description,
                    "result": item.result,
                    "occurred_at": item.occurred_at,
                    "created_at": item.created_at,
                    "execution_mode": "completed_outside_product",
                }
                for item in actions
            ],
            "outcomes": [
                {
                    "id": item.id,
                    "hypothesis_result": item.hypothesis_result,
                    "observable_result": item.observable_result,
                    "learning_gap_dimension": item.learning_gap_dimension,
                    "recorded_at": item.recorded_at,
                }
                for item in outcomes
            ],
            "income_records": [
                self._income_payload(database, item, reveal_income=reveal_income)
                for item in income_records
            ],
            "income_amounts_visible": reveal_income,
            "feedback_suggestions": [
                {
                    "id": item.id,
                    "outcome_id": item.outcome_id,
                    "suggestion_type": item.suggestion_type,
                    "reason": item.reason,
                    "evidence_refs": json.loads(item.evidence_refs_json),
                    "estimated_minutes": item.estimated_minutes,
                    "plan_impact": item.plan_impact,
                    "status": item.status,
                    "decision_note": item.decision_note,
                    "created_at": item.created_at,
                    "decided_at": item.decided_at,
                    "auto_applied": False,
                }
                for item in feedback
            ],
            "events": [
                {
                    "id": item.id,
                    "event_type": item.event_type,
                    "payload": json.loads(item.payload_json),
                    "occurred_at": item.occurred_at,
                }
                for item in events
            ],
            "limitations": self._policy["limitations"],
            "created_at": experiment.created_at,
            "updated_at": experiment.updated_at,
            "approved_at": experiment.approved_at,
            "started_at": experiment.started_at,
            "ended_at": experiment.ended_at,
        }

    def _income_payload(
        self,
        database: Session,
        record: ExperimentIncomeRecord,
        *,
        reveal_income: bool,
    ) -> dict[str, Any]:
        revisions = database.scalars(
            select(ExperimentIncomeRevision)
            .where(ExperimentIncomeRevision.income_record_id == record.id)
            .order_by(ExperimentIncomeRevision.revision)
        ).all()
        show = reveal_income and not record.redacted
        return {
            "id": record.id,
            "current_revision": record.current_revision,
            "redacted": record.redacted,
            "amounts_hidden": not show,
            "revisions": [
                {
                    "id": item.id,
                    "revision": item.revision,
                    "currency": item.currency if show else None,
                    "amount_basis": item.amount_basis if show else None,
                    "gross_amount_minor": item.gross_amount_minor if show else None,
                    "platform_fee_minor": item.platform_fee_minor if show else None,
                    "direct_cost_minor": item.direct_cost_minor if show else None,
                    "received_amount_minor": item.received_amount_minor if show else None,
                    "verification_level": item.verification_level if show else None,
                    "note": item.note if show else None,
                    "occurred_on": item.occurred_on if show else None,
                    "created_at": item.created_at,
                }
                for item in revisions
            ],
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "redacted_at": record.redacted_at,
        }

    @staticmethod
    def _income_revision(
        record_id: str,
        revision: int,
        values: dict[str, Any],
        now: datetime,
    ) -> ExperimentIncomeRevision:
        return ExperimentIncomeRevision(
            id=str(uuid4()),
            income_record_id=record_id,
            revision=revision,
            currency=values["currency"],
            amount_basis=values["amount_basis"],
            gross_amount_minor=values["gross_amount_minor"],
            platform_fee_minor=values["platform_fee_minor"],
            direct_cost_minor=values["direct_cost_minor"],
            received_amount_minor=values["received_amount_minor"],
            verification_level=values["verification_level"],
            note=values.get("note"),
            occurred_on=values["occurred_on"],
            created_at=now,
        )

    def _ensure_policy_snapshot(self, database: Session) -> ExperimentPolicySnapshot:
        digest = _sha256(self._policy)
        existing = database.scalar(
            select(ExperimentPolicySnapshot).where(
                ExperimentPolicySnapshot.policy_id == self._policy["id"],
                ExperimentPolicySnapshot.policy_version == self._policy["version"],
            )
        )
        if existing is not None:
            if existing.payload_sha256 != digest:
                raise ExperimentError(
                    409,
                    "experiment_policy_version_conflict",
                    "同一实验策略版本的摘要发生冲突。必须发布新版本。",
                )
            return existing
        item = ExperimentPolicySnapshot(
            id=str(uuid4()),
            policy_id=self._policy["id"],
            policy_version=self._policy["version"],
            payload_sha256=digest,
            payload_json=_canonical_json(self._policy),
            created_at=self._now(),
        )
        database.add(item)
        database.flush()
        return item

    def _active_goal(self, database: Session, goal_id: str) -> UserGoalSelection:
        goal = database.get(UserGoalSelection, goal_id)
        if goal is None or goal.superseded_at is not None:
            raise ExperimentError(404, "active_goal_not_found", "当前就业目标不存在。")
        return goal

    @staticmethod
    def _market(database: Session, market_id: str | None) -> MarketResearchRun | None:
        if market_id is None:
            return None
        market = database.get(MarketResearchRun, market_id)
        if market is None:
            raise ExperimentError(404, "market_research_not_found", "市场研究记录不存在。")
        return market

    def _package(self, skill_id: str, skill_version: str) -> SkillPackage:
        package = self._packages.get((skill_id, skill_version))
        if package is None:
            raise ExperimentError(404, "skill_package_not_found", "技能包版本不存在。")
        return package

    def _scope_id(self, skill_id: str, skill_version: str) -> str:
        package = self._package(skill_id, skill_version)
        content = next(
            (item for item in package.manifest["content_files"] if item["kind"] == "mastery_scope"),
            None,
        )
        if content is None:
            raise ExperimentError(409, "mastery_scope_missing", "技能包缺少受管能力范围。")
        payload = yaml.safe_load((package.path / content["path"]).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
            raise ExperimentError(409, "mastery_scope_invalid", "技能包能力范围无效。")
        return payload["id"]

    @staticmethod
    def _utc_timestamp(value: datetime) -> float:
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).timestamp()

    @staticmethod
    def _experiment(database: Session, experiment_id: str) -> MonetizationExperiment:
        item = database.get(MonetizationExperiment, experiment_id)
        if item is None:
            raise ExperimentError(404, "experiment_not_found", "实验记录不存在。")
        return item

    @staticmethod
    def _ensure_not_terminal(experiment: MonetizationExperiment) -> None:
        if experiment.status in TERMINAL_STATUSES:
            raise ExperimentError(409, "experiment_terminal", "终态实验不可继续修改。")

    @staticmethod
    def _invalid_transition(status: str, action: str) -> None:
        raise ExperimentError(
            409,
            "invalid_experiment_transition",
            "当前实验状态不允许该动作。",
            {"status": status, "action": action},
        )

    @staticmethod
    def _event(
        database: Session,
        experiment_id: str,
        event_type: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        database.add(
            ExperimentEvent(
                experiment_id=experiment_id,
                event_type=event_type,
                payload_json=_canonical_json(payload),
                occurred_at=now,
            )
        )

    @staticmethod
    def _validator(path: Path) -> Draft202012Validator:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())

    @staticmethod
    def _validate(
        validator: Draft202012Validator,
        value: dict[str, Any],
        code: str,
    ) -> None:
        errors = sorted(
            validator.iter_errors(value),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
        if errors:
            raise ExperimentError(
                422,
                code,
                " / ".join(item.message for item in errors),
            )

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"{path}: expected a JSON object")
        return value
