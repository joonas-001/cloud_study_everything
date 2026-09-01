# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.content_locking import (
    canonical_json,
    execution_package_lock,
    sha256_json,
)
from cloud_study_api.governance import RepositoryValidationError, SkillPackage
from cloud_study_api.models import (
    ActivityAttempt,
    ActivityEvaluation,
    DiagnosticAnswer,
    DiagnosticSession,
    LearningActivity,
    LearningEvent,
    LearningIndependentReview,
    LearningRun,
    LearningRunLock,
    LearningUnitInstance,
    MasteryEvidence,
    MasterySnapshot,
    PlanningProposal,
    PlanningUnit,
    ReviewTask,
    RunnerInvocation,
    SourceChangeCandidate,
    utc_now,
)
from cloud_study_api.notifications import NotificationService
from cloud_study_api.runner import (
    RUNNER_PROTOCOL_VERSION,
    DockerRunnerBackend,
    RunnerBackend,
    RunnerCleanupError,
    RunnerProtocolError,
    RuntimeRegistry,
)

ENGINE_PROTOCOL_VERSION = "0.4.0"
DEFAULT_DAILY_MINUTES = 120
EVIDENCE_VALID_DAYS = 90
MASTERY_DIMENSIONS = (
    "understanding",
    "operation",
    "transfer",
    "artifact",
    "retention",
    "correction",
)
EVIDENCE_RANK = {
    "none": 0,
    "limited": 1,
    "retained_limited": 1,
    "supported": 2,
    "verified": 3,
    "retained": 4,
}


class LearningExecutionError(RuntimeError):
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


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class LearningExecutionService:
    def __init__(
        self,
        repository_root: Path,
        packages: list[SkillPackage],
        session_factory: sessionmaker[Session],
        notification_service: NotificationService | None = None,
        runner_backend: RunnerBackend | None = None,
        runner_execution_enabled: bool = True,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository_root = repository_root
        self._package_list = packages
        self._packages = {(package.package_id, package.version): package for package in packages}
        self._session_factory = session_factory
        self._notifications = notification_service
        self._now = now
        self._runner_backend = runner_backend or DockerRunnerBackend(repository_root)
        self._runner_execution_enabled = runner_execution_enabled
        self._runtime_registry = RuntimeRegistry(repository_root)
        self._runner_result_validator = Draft202012Validator(
            json.loads(
                (repository_root / "contracts" / "runner" / "result-v1.1.schema.json").read_text(
                    encoding="utf-8"
                )
            ),
            format_checker=FormatChecker(),
        )
        self._content_cache: dict[tuple[str, str, str], dict[str, Any]] = {}

    def list_planning_options(
        self,
        skill_id: str,
        skill_version: str,
    ) -> list[dict[str, Any]]:
        package = self._package(skill_id, skill_version)
        if package.availability != "available":
            raise LearningExecutionError(
                409,
                "skill_package_suspended",
                "The selected skill package is suspended.",
            )
        with self._session_factory() as database:
            proposals = database.scalars(
                select(PlanningProposal)
                .where(
                    PlanningProposal.skill_id == skill_id,
                    PlanningProposal.skill_version == skill_version,
                    PlanningProposal.status == "saved_preview",
                )
                .order_by(PlanningProposal.created_at.desc())
            ).all()
            latest_diagnostic = database.scalar(
                select(DiagnosticSession)
                .where(
                    DiagnosticSession.skill_id == skill_id,
                    DiagnosticSession.skill_version == skill_version,
                )
                .order_by(DiagnosticSession.created_at.desc())
            )
            latest_proposal = proposals[0] if proposals else None
            return [
                self._planning_option_payload(
                    database,
                    proposal,
                    latest_diagnostic,
                    latest_proposal,
                )
                for proposal in proposals
            ]

    def create_run(
        self,
        *,
        planning_proposal_id: str,
        preview: bool,
        code_execution: bool,
        external_ai: bool,
        confirm_historical_plan: bool,
        reuse_from_run_id: str | None,
        confirm_reuse: bool,
    ) -> dict[str, Any]:
        if not preview:
            raise LearningExecutionError(
                409,
                "learning_requires_preview",
                "The draft package only supports local preview learning runs.",
            )
        if external_ai:
            raise LearningExecutionError(
                409,
                "external_ai_disabled_for_learning",
                "Milestone 4A learning runs cannot call external AI.",
            )
        now = self._now()
        with self._session_factory() as database:
            proposal = database.get(PlanningProposal, planning_proposal_id)
            if proposal is None:
                raise LearningExecutionError(
                    404,
                    "planning_proposal_not_found",
                    "Planning proposal not found.",
                )
            if proposal.status != "saved_preview":
                raise LearningExecutionError(
                    409,
                    "planning_proposal_not_saved",
                    "Only a saved planning preview can create a learning run.",
                )
            package = self._package(proposal.skill_id, proposal.skill_version)
            runner_enabled = bool(package.manifest["runtime_profiles"])
            if runner_enabled and not code_execution:
                raise LearningExecutionError(
                    409,
                    "code_execution_confirmation_required",
                    "Explicitly confirm isolated code execution for this 4B learning run.",
                )
            if code_execution and not runner_enabled:
                raise LearningExecutionError(
                    409,
                    "code_execution_not_supported",
                    "The selected immutable package version does not declare Runner runtimes.",
                )
            if package.availability != "available":
                raise LearningExecutionError(
                    409,
                    "skill_package_suspended",
                    "The selected skill package is suspended.",
                )
            if package.intake != "open":
                raise LearningExecutionError(
                    409,
                    "skill_package_intake_closed",
                    "This package version cannot create new learning runs.",
                )
            if package.state != "draft":
                raise LearningExecutionError(
                    409,
                    "skill_package_not_previewable",
                    "Milestone 4A requires a draft package preview.",
                )
            existing = database.scalar(
                select(LearningRun).where(
                    LearningRun.skill_id == proposal.skill_id,
                    LearningRun.skill_version == proposal.skill_version,
                    LearningRun.status.in_(["active", "paused", "retention_pending"]),
                )
            )
            if existing is not None:
                raise LearningExecutionError(
                    409,
                    "nonterminal_learning_run_exists",
                    "A non-terminal learning run already exists for this exact package version.",
                    {"run_id": existing.id},
                )
            diagnostic = database.get(DiagnosticSession, proposal.diagnostic_session_id)
            if diagnostic is None:
                raise LearningExecutionError(
                    409,
                    "planning_diagnostic_missing",
                    "The planning proposal no longer has its diagnostic record.",
                )
            latest_diagnostic = database.scalar(
                select(DiagnosticSession)
                .where(
                    DiagnosticSession.skill_id == proposal.skill_id,
                    DiagnosticSession.skill_version == proposal.skill_version,
                )
                .order_by(DiagnosticSession.created_at.desc())
            )
            latest_proposal = database.scalar(
                select(PlanningProposal)
                .where(
                    PlanningProposal.skill_id == proposal.skill_id,
                    PlanningProposal.skill_version == proposal.skill_version,
                    PlanningProposal.status == "saved_preview",
                )
                .order_by(PlanningProposal.created_at.desc())
            )
            historical = self._is_historical(proposal, latest_diagnostic, latest_proposal)
            if historical and not confirm_historical_plan:
                raise LearningExecutionError(
                    409,
                    "historical_plan_confirmation_required",
                    "Confirm the stale-plan warning before creating this learning run.",
                )
            reused_from: LearningRun | None = None
            if reuse_from_run_id is not None:
                reused_from = database.get(LearningRun, reuse_from_run_id)
                if (
                    reused_from is None
                    or reused_from.planning_proposal_id != proposal.id
                    or reused_from.status not in {"completed", "ended"}
                ):
                    raise LearningExecutionError(
                        409,
                        "learning_run_not_reusable",
                        "Only a terminal run using the same immutable plan can be reused.",
                    )
                if not confirm_reuse:
                    raise LearningExecutionError(
                        409,
                        "learning_run_reuse_confirmation_required",
                        "Explicit confirmation is required to reuse a terminal run plan.",
                    )
            try:
                package_lock = execution_package_lock(
                    database,
                    package,
                    self._package_list,
                    now,
                )
            except RepositoryValidationError as error:
                raise LearningExecutionError(
                    409,
                    "skill_package_content_changed",
                    str(error),
                ) from error

            learning = self._content(package, "learning_definition")
            assessment = self._content(package, "assessment_definition")
            rubric = self._content(package, "rubric_definition")
            review_policy = self._content(package, "review_policy")
            mastery_scope = self._content(package, "mastery_scope")
            source_catalog = self._content(package, "source_catalog")
            planning_units = database.scalars(
                select(PlanningUnit)
                .where(PlanningUnit.proposal_id == proposal.id)
                .order_by(PlanningUnit.sequence)
            ).all()
            planning_snapshot = [
                {
                    "template_unit_id": unit.template_unit_id,
                    "sequence": unit.sequence,
                    "title": unit.title,
                    "objective": unit.objective,
                    "reason": unit.reason,
                    "estimated_minutes": unit.estimated_minutes,
                    "completion_criteria": json.loads(unit.completion_criteria_json),
                }
                for unit in planning_units
            ]
            lock_payload = {
                "diagnostic_session_id": diagnostic.id,
                "diagnostic_created_at": diagnostic.created_at.isoformat(),
                "planning_proposal_id": proposal.id,
                "planning_saved_at": proposal.updated_at.isoformat(),
                "planning_units": planning_snapshot,
                "packages": package_lock,
                "source_catalog_sha256": sha256_json(source_catalog),
                "learning_definition_sha256": sha256_json(learning),
                "assessment_definition_sha256": sha256_json(assessment),
                "rubric_definition_sha256": sha256_json(rubric),
                "review_policy": review_policy,
                "mastery_scope_sha256": sha256_json(mastery_scope),
                "engine_protocol_version": ENGINE_PROTOCOL_VERSION,
                "runner_protocol_version": RUNNER_PROTOCOL_VERSION,
                "runtime_registry_version": self._runtime_registry.registry["registry_version"],
                "runtime_profiles": [
                    self._runtime_registry.get(item["id"], item["version"])
                    for item in package.manifest["runtime_profiles"]
                ],
                "capabilities": {
                    "code_execution": "enabled" if runner_enabled else "disabled",
                    "external_ai": "disabled",
                    "file_upload": "disabled",
                    "local_path_access": "disabled",
                },
                "is_preview": True,
            }
            run = LearningRun(
                id=str(uuid4()),
                planning_proposal_id=proposal.id,
                diagnostic_session_id=diagnostic.id,
                skill_id=proposal.skill_id,
                skill_version=proposal.skill_version,
                status="active",
                is_preview=True,
                selected_historical_plan=historical,
                reused_from_run_id=reused_from.id if reused_from else None,
                created_at=now,
                updated_at=now,
            )
            database.add(run)
            database.flush()
            database.add(
                LearningRunLock(
                    run_id=run.id,
                    lock_sha256=sha256_json(lock_payload),
                    lock_json=canonical_json(lock_payload),
                    created_at=now,
                )
            )
            unit_instances = self._create_unit_instances(
                database,
                run,
                learning,
                planning_units,
            )
            selected_remediation, remediation_reasons = self._selected_remediation(
                database,
                diagnostic.id,
                learning,
            )
            self._create_initial_activities(
                database,
                run,
                learning,
                unit_instances,
                selected_remediation,
                remediation_reasons,
                now,
            )
            for dimension in MASTERY_DIMENSIONS:
                database.add(
                    MasterySnapshot(
                        id=str(uuid4()),
                        run_id=run.id,
                        dimension=dimension,
                        evidence_level="none",
                        review_flags_json="[]",
                        evidence_count=0,
                        updated_at=now,
                    )
                )
            self._event(
                database,
                run.id,
                "learning_run_created",
                {
                    "planning_proposal_id": proposal.id,
                    "diagnostic_session_id": diagnostic.id,
                    "historical_plan_selected": historical,
                    "reused_from_run_id": reused_from.id if reused_from else None,
                    "code_execution": "enabled" if runner_enabled else "disabled",
                    "external_ai": "disabled",
                },
                now,
            )
            try:
                database.commit()
            except IntegrityError as error:
                database.rollback()
                raise LearningExecutionError(
                    409,
                    "nonterminal_learning_run_exists",
                    "A non-terminal learning run already exists for this exact package version.",
                ) from error
            return self._run_payload(database, run)

    def get_active_run(self, skill_id: str, skill_version: str) -> dict[str, Any]:
        with self._session_factory() as database:
            run = database.scalar(
                select(LearningRun).where(
                    LearningRun.skill_id == skill_id,
                    LearningRun.skill_version == skill_version,
                    LearningRun.status.in_(["active", "paused", "retention_pending"]),
                )
            )
            if run is None:
                raise LearningExecutionError(
                    404,
                    "active_learning_run_not_found",
                    "No non-terminal learning run exists.",
                )
            self._refresh_due_reviews(database, run, self._now())
            database.commit()
            return self._run_payload(database, run)

    def get_latest_run(self, skill_id: str, skill_version: str) -> dict[str, Any]:
        with self._session_factory() as database:
            run = database.scalar(
                select(LearningRun)
                .where(
                    LearningRun.skill_id == skill_id,
                    LearningRun.skill_version == skill_version,
                )
                .order_by(LearningRun.created_at.desc())
            )
            if run is None:
                raise LearningExecutionError(
                    404,
                    "learning_run_not_found",
                    "No learning run exists.",
                )
            self._refresh_due_reviews(database, run, self._now())
            database.commit()
            return self._run_payload(database, run)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._session_factory() as database:
            run = self._run(database, run_id)
            self._refresh_due_reviews(database, run, self._now())
            database.commit()
            return self._run_payload(database, run)

    def today(
        self,
        run_id: str,
        available_minutes: int,
        *,
        allow_overtime: bool = False,
        overtime_reason: str | None = None,
    ) -> dict[str, Any]:
        if not 15 <= available_minutes <= 480:
            raise LearningExecutionError(
                422,
                "invalid_available_minutes",
                "Available minutes must be between 15 and 480.",
            )
        now = self._now()
        with self._session_factory() as database:
            run = self._run(database, run_id)
            package = self._package(run.skill_id, run.skill_version)
            common_core = self._is_common_core(package)
            if common_core and available_minutes > DEFAULT_DAILY_MINUTES:
                if not allow_overtime or not overtime_reason or not overtime_reason.strip():
                    raise LearningExecutionError(
                        422,
                        "daily_overtime_confirmation_required",
                        "超过 120 分钟必须仅对当天明确确认并记录原因。",
                    )
                if len(overtime_reason.strip()) > 500:
                    raise LearningExecutionError(
                        422,
                        "daily_overtime_reason_too_long",
                        "超时原因不能超过 500 个字符。",
                    )
            elif allow_overtime:
                raise LearningExecutionError(
                    422,
                    "daily_overtime_not_needed",
                    "不超过 120 分钟时不需要超时确认。",
                )
            if run.status in {"completed", "ended"}:
                return {
                    "run_id": run.id,
                    "generated_at": now,
                    "available_minutes": available_minutes,
                    "estimated_minutes": 0,
                    "tasks": [],
                    "deferred_tasks": [],
                    "overtime": False,
                    "reason": "学习执行已进入终态，没有可继续的今日任务。",
                }
            if run.status == "paused":
                return {
                    "run_id": run.id,
                    "generated_at": now,
                    "available_minutes": available_minutes,
                    "estimated_minutes": 0,
                    "tasks": [],
                    "deferred_tasks": [],
                    "overtime": False,
                    "reason": "学习执行已暂停；恢复后才会重新生成任务。暂停不表示能力失败。",
                }
            self._refresh_due_reviews(database, run, now)
            activities = database.scalars(
                select(LearningActivity)
                .where(
                    LearningActivity.run_id == run.id,
                    LearningActivity.status.in_(["available", "correction_required"]),
                )
                .order_by(LearningActivity.sequence)
            ).all()
            ordered = sorted(
                activities,
                key=(
                    (lambda item: (*self._daily_priority(item), item.sequence))
                    if common_core
                    else (
                        lambda item: (
                            0
                            if item.activity_type == "review"
                            else 1
                            if item.activity_type == "correction"
                            else 2,
                            item.sequence,
                        )
                    )
                ),
            )
            selected: list[LearningActivity] = []
            deferred: list[dict[str, Any]] = []
            used = 0
            selected_high_load_domains: set[str] = set()
            for activity in ordered:
                definition = cast(dict[str, Any], json.loads(activity.definition_json))
                domain_id = self._activity_domain(definition)
                high_load_new_domain = bool(
                    common_core
                    and self._daily_priority(activity)[0] == 3
                    and definition.get("unit_cognitive_load") == "high"
                    and domain_id
                )
                if (
                    high_load_new_domain
                    and selected_high_load_domains
                    and domain_id not in selected_high_load_domains
                ):
                    deferred.append(self._deferred_task_payload(activity, "high_load_domain_limit"))
                    continue
                if used + activity.estimated_minutes > available_minutes:
                    deferred.append(self._deferred_task_payload(activity, "daily_budget_exhausted"))
                    continue
                selected.append(activity)
                used += activity.estimated_minutes
                if high_load_new_domain:
                    selected_high_load_domains.add(domain_id)
            task_payloads: list[dict[str, Any]] = []
            for activity in selected:
                item = self._activity_payload(database, activity, now)
                if common_core:
                    priority_code, priority_rank = self._daily_priority_label(activity)
                    item["daily_priority"] = priority_code
                    item["daily_priority_rank"] = priority_rank
                task_payloads.append(item)
            self._event(
                database,
                run.id,
                "today_queue_generated",
                {
                    "available_minutes": available_minutes,
                    "activity_ids": [activity.id for activity in selected],
                    "estimated_minutes": used,
                    "deferred": deferred,
                    "overtime": available_minutes > DEFAULT_DAILY_MINUTES,
                    "overtime_reason": (
                        overtime_reason.strip()
                        if available_minutes > DEFAULT_DAILY_MINUTES and overtime_reason
                        else None
                    ),
                },
                now,
            )
            database.commit()
            return {
                "run_id": run.id,
                "generated_at": now,
                "available_minutes": available_minutes,
                "estimated_minutes": used,
                "tasks": task_payloads,
                "deferred_tasks": deferred,
                "overtime": available_minutes > DEFAULT_DAILY_MINUTES,
                "reason": (
                    "按到期复习、阻断纠错和当前核心活动排序；未完成任务顺延，不记为能力失败。"
                ),
            }

    def submit_attempt(
        self,
        activity_id: str,
        *,
        submission: dict[str, str],
        corrects_attempt_id: str | None = None,
        mark_uncertain: bool = False,
    ) -> dict[str, Any]:
        now = self._now()
        with self._session_factory() as database:
            activity = database.get(LearningActivity, activity_id)
            if activity is None:
                raise LearningExecutionError(
                    404,
                    "learning_activity_not_found",
                    "Learning activity not found.",
                )
            run = self._run(database, activity.run_id)
            if run.status not in {"active", "retention_pending"}:
                raise LearningExecutionError(
                    409,
                    "learning_run_read_only",
                    "Terminal learning runs are read-only.",
                )
            self._refresh_due_reviews(database, run, now)
            if activity.status not in {"available", "correction_required"}:
                raise LearningExecutionError(
                    409,
                    "learning_activity_not_available",
                    "This activity is not currently available.",
                )
            definition = cast(dict[str, Any], json.loads(activity.definition_json))
            self._validate_submission(definition, submission)
            previous_attempt = None
            if corrects_attempt_id is not None:
                previous_attempt = database.get(ActivityAttempt, corrects_attempt_id)
                if previous_attempt is None or previous_attempt.activity_id != activity.id:
                    raise LearningExecutionError(
                        409,
                        "invalid_corrected_attempt",
                        "A correction must reference an earlier attempt for the same activity.",
                    )
                latest_attempt = database.scalar(
                    select(ActivityAttempt)
                    .where(ActivityAttempt.activity_id == activity.id)
                    .order_by(ActivityAttempt.revision.desc())
                )
                if latest_attempt is None or latest_attempt.id != previous_attempt.id:
                    raise LearningExecutionError(
                        409,
                        "correction_must_target_latest_attempt",
                        "A correction must reference the latest attempt for this activity.",
                    )
            revision = (
                database.scalar(
                    select(func.max(ActivityAttempt.revision)).where(
                        ActivityAttempt.activity_id == activity.id
                    )
                )
                or 0
            ) + 1
            attempt = ActivityAttempt(
                id=str(uuid4()),
                activity_id=activity.id,
                revision=revision,
                submission_json=canonical_json(submission),
                corrects_attempt_id=previous_attempt.id if previous_attempt else None,
                created_at=now,
            )
            database.add(attempt)
            database.flush()
            if previous_attempt is not None:
                prior_evidence = database.scalars(
                    select(MasteryEvidence).where(
                        MasteryEvidence.attempt_id == previous_attempt.id,
                        MasteryEvidence.superseded_at.is_(None),
                    )
                ).all()
                for evidence in prior_evidence:
                    evidence.superseded_at = now
                    evidence.superseded_by_attempt_id = attempt.id

            method, result, detail = self._evaluate_attempt(
                definition,
                submission,
                mark_uncertain,
            )
            evaluation = ActivityEvaluation(
                id=str(uuid4()),
                attempt_id=attempt.id,
                method=method,
                result=result,
                rubric_id=None,
                detail_json=canonical_json(detail),
                created_at=now,
            )
            database.add(evaluation)
            database.flush()
            evidence_count = self._create_evidence(
                database,
                run,
                activity,
                attempt,
                evaluation,
                now,
            )
            review_task = database.scalar(
                select(ReviewTask).where(ReviewTask.activity_id == activity.id)
            )
            successful = result in {
                "passed",
                "submitted",
                "review_pending",
                "not_executable",
            }
            if (
                activity.activity_type == "review"
                and review_task is not None
                and definition["completion_rule"] == "runner_pass"
            ):
                activity.status = "available"
                activity.completed_at = None
            elif activity.activity_type == "review" and review_task is not None:
                activity.status = "completed"
                activity.completed_at = now
                if successful and result == "passed":
                    self._pass_review(database, run, review_task, now)
                else:
                    self._fail_review(database, run, review_task, definition, now)
            elif activity.activity_type == "correction" and definition.get(
                "retry_checkpoint_index"
            ):
                if result == "passed":
                    activity.status = "completed"
                    activity.completed_at = now
                    self._schedule_retry_after_correction(
                        database,
                        run,
                        definition,
                        now,
                    )
                else:
                    activity.status = "correction_required"
            elif definition["completion_rule"] == "deterministic_pass" and result != "passed":
                activity.status = "correction_required"
            elif definition["completion_rule"] == "runner_pass":
                activity.status = "available"
            else:
                activity.status = "completed"
                activity.completed_at = now
                self._advance_initial_learning(database, run, now)
            run.updated_at = now
            self._rebuild_snapshots(database, run, now)
            self._event(
                database,
                run.id,
                "activity_attempt_recorded",
                {
                    "activity_id": activity.id,
                    "attempt_id": attempt.id,
                    "revision": revision,
                    "corrects_attempt_id": corrects_attempt_id,
                    "evaluation_method": method,
                    "evaluation_result": result,
                },
                now,
            )
            database.commit()
            self._notify_evidence_update(run, activity, attempt, evidence_count)
            return {
                "attempt": self._attempt_payload(database, attempt),
                "activity": self._activity_payload(database, activity, now),
                "run": self._run_payload(database, run),
            }

    def runner_availability(self) -> dict[str, Any]:
        if not self._runner_execution_enabled:
            return {
                "available": False,
                "reason_code": "remote_runner_disabled",
                "docker_path": None,
                "data_root": "disabled",
                "free_gb": None,
                "used_gb": None,
                "server_version": None,
            }
        return self._runner_backend.availability()

    def recover_stale_runner_invocations(self) -> int:
        now = self._now()
        with self._session_factory() as database:
            stale = database.scalars(
                select(RunnerInvocation).where(RunnerInvocation.status.in_(["queued", "running"]))
            ).all()
            if stale and self._runner_execution_enabled:
                self._runner_backend.cleanup_stale()
            for item in stale:
                item.status = "infrastructure_error"
                item.failure_code = (
                    "cleanup_failed" if self._runner_execution_enabled else "remote_runner_disabled"
                )
                item.finished_at = now
                item.result_json = None
                self._event(
                    database,
                    item.run_id,
                    "runner_invocation_recovered",
                    {
                        "invocation_id": item.id,
                        "reason": "api_restart_before_terminal_result",
                    },
                    now,
                )
            database.commit()
        return len(stale)

    def execute_attempt(self, attempt_id: str) -> dict[str, Any]:
        if not self._runner_execution_enabled:
            raise LearningExecutionError(
                409,
                "remote_runner_disabled",
                "Remote Runner is disabled for the private preview.",
            )
        now = self._now()
        with self._session_factory() as database:
            attempt = database.get(ActivityAttempt, attempt_id)
            if attempt is None:
                raise LearningExecutionError(
                    404,
                    "activity_attempt_not_found",
                    "Activity attempt not found.",
                )
            activity = database.get(LearningActivity, attempt.activity_id)
            if activity is None:
                raise LearningExecutionError(
                    409,
                    "learning_activity_not_found",
                    "Learning activity not found.",
                )
            run = self._run(database, activity.run_id)
            if run.status not in {"active", "retention_pending"}:
                raise LearningExecutionError(
                    409,
                    "learning_run_read_only",
                    "Terminal learning runs are read-only.",
                )
            definition = cast(dict[str, Any], json.loads(activity.definition_json))
            task_id = definition.get("runner_task_id")
            if not isinstance(task_id, str):
                raise LearningExecutionError(
                    409,
                    "runner_task_unavailable",
                    "This activity does not declare a governed Runner task.",
                )
            latest = database.scalar(
                select(ActivityAttempt)
                .where(ActivityAttempt.activity_id == activity.id)
                .order_by(ActivityAttempt.revision.desc())
            )
            if latest is None or latest.id != attempt.id:
                raise LearningExecutionError(
                    409,
                    "runner_requires_latest_attempt",
                    "Only the latest append-only attempt can be executed.",
                )
            existing = database.scalar(
                select(RunnerInvocation).where(RunnerInvocation.status.in_(["queued", "running"]))
            )
            if existing is not None:
                raise LearningExecutionError(
                    409,
                    "runner_busy",
                    "Another isolated Runner task is active.",
                    {"invocation_id": existing.id},
                )
            package = self._package(run.skill_id, run.skill_version)
            tasks = self._content(package, "runner_task_definition")
            task = next(
                (item for item in tasks["tasks"] if item["id"] == task_id),
                None,
            )
            if task is None:
                raise LearningExecutionError(
                    409,
                    "runner_task_not_governed",
                    "The Runner task is not present in the immutable package content.",
                )
            profile = self._runtime_registry.get(
                task["runtime_profile_id"],
                task["runtime_profile_version"],
            )
            submission = cast(dict[str, str], json.loads(attempt.submission_json))
            source = submission[task["source_field_id"]]
            artifact_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
            invocation_id = str(uuid4())
            invocation = {
                "protocol_version": RUNNER_PROTOCOL_VERSION,
                "audit_id": invocation_id,
                "artifact_sha256": artifact_sha256,
                "runtime": {
                    "id": profile["id"],
                    "version": profile["version"],
                    "language": profile["language"],
                    "platform": profile["platform"],
                    "image": profile["image"],
                },
                "source": {
                    "filename": "main.cpp" if profile["language"] == "cpp" else "main.py",
                    "content": source,
                },
                "tests": [
                    {
                        "id": item["id"],
                        "stdin": item["stdin"],
                        "expected_stdout": item["expected_stdout"],
                    }
                    for item in task["tests"]
                ],
                "limits": {
                    "compile_wall_seconds": 15,
                    "run_wall_seconds": 3,
                    "compile_memory_mb": 768,
                    "run_memory_mb": 256,
                    "cpus": 1,
                    "compile_pids": 64,
                    "run_pids": 32,
                    "output_bytes": 65536,
                    "tmpfs_mb": 128,
                },
            }
            request_sha256 = hashlib.sha256(canonical_json(invocation).encode("utf-8")).hexdigest()
            record = RunnerInvocation(
                id=invocation_id,
                singleton_key=1,
                run_id=run.id,
                activity_id=activity.id,
                attempt_id=attempt.id,
                protocol_version=RUNNER_PROTOCOL_VERSION,
                task_id=task_id,
                runtime_profile_id=profile["id"],
                runtime_profile_version=profile["version"],
                runtime_image=profile["image"],
                artifact_sha256=artifact_sha256,
                request_sha256=request_sha256,
                status="running",
                created_at=now,
                started_at=now,
            )
            database.add(record)
            self._event(
                database,
                run.id,
                "runner_invocation_started",
                {
                    "invocation_id": invocation_id,
                    "attempt_id": attempt.id,
                    "task_id": task_id,
                    "artifact_sha256": artifact_sha256,
                    "request_sha256": request_sha256,
                    "runtime_profile": f"{profile['id']}@{profile['version']}",
                },
                now,
            )
            try:
                database.commit()
            except IntegrityError as error:
                database.rollback()
                active = database.scalar(
                    select(RunnerInvocation).where(
                        RunnerInvocation.status.in_(["queued", "running"])
                    )
                )
                raise LearningExecutionError(
                    409,
                    "runner_busy",
                    "Another isolated Runner task is active.",
                    {
                        "invocation_id": None if active is None else active.id,
                    },
                ) from error
        execution_failure_code: str | None = None
        try:
            result = self._runner_backend.execute(invocation)
            self._validate_runner_result(invocation, result)
        except RunnerCleanupError:
            execution_failure_code = "cleanup_failed"
        except OSError, RunnerProtocolError, subprocess.SubprocessError:
            execution_failure_code = "protocol_invalid"
        except Exception:
            execution_failure_code = "protocol_invalid"
        if execution_failure_code is not None:
            result = {
                "protocol_version": RUNNER_PROTOCOL_VERSION,
                "audit_id": invocation_id,
                "artifact_sha256": artifact_sha256,
                "status": "infrastructure_error",
                "failure_code": execution_failure_code,
                "runtime": {
                    "id": profile["id"],
                    "version": profile["version"],
                    "image": profile["image"],
                    "observed_image_id": None,
                },
                "tests": [],
                "security": {
                    "network": "none",
                    "root_filesystem": "read_only",
                    "user": "65534:65534",
                    "capabilities": "dropped_all",
                    "no_new_privileges": True,
                    "seccomp": "builtin",
                    "host_mounts": "none",
                    "docker_socket": "not_mounted",
                    "pull_policy": "never",
                },
                "started_at": now.isoformat(),
                "finished_at": self._now().isoformat(),
            }
        finished_at = self._now()
        with self._session_factory() as database:
            record = cast(RunnerInvocation, database.get(RunnerInvocation, invocation_id))
            attempt = cast(ActivityAttempt, database.get(ActivityAttempt, attempt_id))
            activity = cast(LearningActivity, database.get(LearningActivity, record.activity_id))
            run = self._run(database, record.run_id)
            record.status = result["status"]
            record.failure_code = result["failure_code"]
            record.result_json = canonical_json(result)
            record.finished_at = finished_at
            evaluation = ActivityEvaluation(
                id=str(uuid4()),
                attempt_id=attempt.id,
                method="runner",
                result="passed" if result["status"] == "passed" else "failed",
                rubric_id=None,
                detail_json=canonical_json(
                    {
                        "invocation_id": invocation_id,
                        "status": result["status"],
                        "failure_code": result["failure_code"],
                        "tests": result["tests"],
                        "runtime": result["runtime"],
                        "security": result["security"],
                    }
                ),
                created_at=finished_at,
            )
            database.add(evaluation)
            database.flush()
            review_task = database.scalar(
                select(ReviewTask).where(ReviewTask.activity_id == activity.id)
            )
            definition = cast(dict[str, Any], json.loads(activity.definition_json))
            if result["status"] == "passed":
                evidence_count = self._create_evidence(
                    database,
                    run,
                    activity,
                    attempt,
                    evaluation,
                    finished_at,
                )
                activity.status = "completed"
                activity.completed_at = finished_at
                if activity.activity_type == "review" and review_task is not None:
                    self._pass_review(database, run, review_task, finished_at)
                else:
                    self._advance_initial_learning(database, run, finished_at)
            else:
                evidence_count = 0
            if result["status"] in {"failed", "timeout", "output_limit"}:
                if activity.activity_type == "review" and review_task is not None:
                    activity.status = "completed"
                    activity.completed_at = finished_at
                    self._fail_review(database, run, review_task, definition, finished_at)
                else:
                    activity.status = "correction_required"
                    activity.completed_at = None
            self._rebuild_snapshots(database, run, finished_at)
            run.updated_at = finished_at
            self._event(
                database,
                run.id,
                "runner_invocation_finished",
                {
                    "invocation_id": invocation_id,
                    "status": result["status"],
                    "failure_code": result["failure_code"],
                    "test_count": len(result["tests"]),
                },
                finished_at,
            )
            database.commit()
            self._notify_evidence_update(run, activity, attempt, evidence_count)
            return {
                "invocation": self._runner_invocation_payload(record),
                "attempt": self._attempt_payload(database, attempt),
                "activity": self._activity_payload(database, activity, finished_at),
                "run": self._run_payload(database, run),
            }

    def self_review_attempt(
        self,
        attempt_id: str,
        *,
        rubric_id: str,
        result: str,
    ) -> dict[str, Any]:
        if result not in {"not_yet", "uncertain", "meets"}:
            raise LearningExecutionError(
                422,
                "invalid_self_review_result",
                "Self-review result must be not_yet, uncertain, or meets.",
            )
        now = self._now()
        with self._session_factory() as database:
            attempt = database.get(ActivityAttempt, attempt_id)
            if attempt is None:
                raise LearningExecutionError(
                    404,
                    "activity_attempt_not_found",
                    "Activity attempt not found.",
                )
            activity = cast(LearningActivity, database.get(LearningActivity, attempt.activity_id))
            run = self._run(database, activity.run_id)
            if run.status not in {"active", "retention_pending"}:
                raise LearningExecutionError(
                    409,
                    "learning_run_read_only",
                    "Terminal learning runs are read-only.",
                )
            latest_attempt = database.scalar(
                select(ActivityAttempt)
                .where(ActivityAttempt.activity_id == activity.id)
                .order_by(ActivityAttempt.revision.desc())
            )
            if latest_attempt is None or latest_attempt.id != attempt.id:
                raise LearningExecutionError(
                    409,
                    "self_review_requires_latest_attempt",
                    "Only the latest attempt can receive a self-review.",
                )
            prior_self_review = database.scalar(
                select(ActivityEvaluation.id).where(
                    ActivityEvaluation.attempt_id == attempt.id,
                    ActivityEvaluation.method == "self_review",
                )
            )
            if prior_self_review is not None:
                raise LearningExecutionError(
                    409,
                    "attempt_already_self_reviewed",
                    "Submit an appended correction before recording another self-review.",
                )
            package = self._package(run.skill_id, run.skill_version)
            rubric = self._content(package, "rubric_definition")
            known_rubrics = {criterion["id"] for criterion in rubric["criteria"]}
            if rubric_id not in known_rubrics:
                raise LearningExecutionError(
                    422,
                    "rubric_not_found",
                    "The selected rubric is not part of the locked package.",
                )
            assessment = self._content(package, "assessment_definition")
            template_id = activity.template_activity_id.split(":", maxsplit=1)[0]
            allowed_rubrics = {
                criterion["self_review_rubric_id"]
                for criterion in assessment["criteria"]
                if criterion["activity_id"] == template_id
                and criterion.get("self_review_rubric_id")
            }
            if rubric_id not in allowed_rubrics:
                raise LearningExecutionError(
                    422,
                    "rubric_not_allowed_for_activity",
                    "The selected rubric is not assigned to this activity.",
                )
            evaluation = ActivityEvaluation(
                id=str(uuid4()),
                attempt_id=attempt.id,
                method="self_review",
                result=(
                    "submitted"
                    if result == "meets"
                    else "uncertain"
                    if result == "uncertain"
                    else "failed"
                ),
                rubric_id=rubric_id,
                detail_json=canonical_json({"self_review_result": result}),
                created_at=now,
            )
            database.add(evaluation)
            database.flush()
            existing = database.scalars(
                select(MasteryEvidence).where(
                    MasteryEvidence.attempt_id == attempt.id,
                    MasteryEvidence.superseded_at.is_(None),
                )
            ).all()
            for evidence in existing:
                evidence.superseded_at = now
                evidence.superseded_by_attempt_id = attempt.id
            evidence_count = self._create_evidence(
                database,
                run,
                activity,
                attempt,
                evaluation,
                now,
            )
            if result in {"not_yet", "uncertain"}:
                activity.status = "correction_required"
                activity.completed_at = None
                activity.available_at = now
            run.updated_at = now
            self._rebuild_snapshots(database, run, now)
            self._event(
                database,
                run.id,
                "attempt_self_reviewed",
                {
                    "attempt_id": attempt.id,
                    "rubric_id": rubric_id,
                    "result": result,
                    "reviewer_type": "self_review",
                    "next_action": (
                        "append_correction" if result in {"not_yet", "uncertain"} else "none"
                    ),
                },
                now,
            )
            database.commit()
            self._notify_evidence_update(run, activity, attempt, evidence_count)
            return {
                "attempt": self._attempt_payload(database, attempt),
                "activity": self._activity_payload(database, activity, now),
                "run": self._run_payload(database, run),
            }

    def get_evidence(self, run_id: str) -> dict[str, Any]:
        with self._session_factory() as database:
            run = self._run(database, run_id)
            self._rebuild_snapshots(database, run, self._now())
            database.commit()
            evidence = database.scalars(
                select(MasteryEvidence)
                .where(MasteryEvidence.run_id == run.id)
                .order_by(MasteryEvidence.created_at)
            ).all()
            snapshots = database.scalars(
                select(MasterySnapshot)
                .where(MasterySnapshot.run_id == run.id)
                .order_by(MasterySnapshot.dimension)
            ).all()
            return {
                "run_id": run.id,
                "limitations": self._evidence_limitations(run),
                "dimensions": [self._snapshot_payload(snapshot) for snapshot in snapshots],
                "evidence": [
                    {
                        "id": item.id,
                        "activity_id": item.activity_id,
                        "attempt_id": item.attempt_id,
                        "criterion_id": item.criterion_id,
                        "dimension": item.dimension,
                        "method": item.method,
                        "result": item.result,
                        "strength": item.strength,
                        "capability_ids": json.loads(item.capability_ids_json),
                        "language": item.language,
                        "review_flags": json.loads(item.review_flags_json),
                        "created_at": item.created_at,
                        "superseded_at": item.superseded_at,
                    }
                    for item in evidence
                ],
            }

    def get_stage_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as database:
            run = self._run(database, run_id)
            package = self._package(run.skill_id, run.skill_version)
            if not self._is_common_core(package):
                return []
            graph = self._content(package, "capability_graph")
            units = database.scalars(
                select(LearningUnitInstance)
                .where(LearningUnitInstance.run_id == run.id)
                .order_by(LearningUnitInstance.sequence)
            ).all()
            grouped: dict[str, list[LearningUnitInstance]] = {
                domain["id"]: [] for domain in graph["domains"]
            }
            for unit in units:
                definition = cast(dict[str, Any], json.loads(unit.snapshot_json))
                capability_ids = set(definition.get("capability_ids", []))
                domain_ids = {
                    capability["domain_id"]
                    for capability in graph["capabilities"]
                    if capability["id"] in capability_ids
                }
                for domain_id in domain_ids:
                    grouped.setdefault(domain_id, []).append(unit)
            checkpoints: list[dict[str, Any]] = []
            for domain in graph["domains"]:
                domain_units = grouped.get(domain["id"], [])
                completed = sum(item.status == "completed" for item in domain_units)
                if not domain_units or (
                    completed == 0 and all(item.status == "pending" for item in domain_units)
                ):
                    status = "not_started"
                elif completed == len(domain_units):
                    status = "initial_learning_completed"
                else:
                    status = "in_progress"
                checkpoints.append(
                    {
                        "domain_id": domain["id"],
                        "title": domain["title"],
                        "status": status,
                        "completed_units": completed,
                        "total_units": len(domain_units),
                        "meaning": "流程阶段检查，不表示该领域或整门算法掌握。",
                    }
                )
            return checkpoints

    def add_independent_review(
        self,
        run_id: str,
        *,
        activity_id: str | None,
        capability_ids: list[str],
        dimension: str,
        reviewer_relationship: str,
        rubric_id: str,
        rubric_version: str,
        conclusion: str,
        reviewed_at: datetime,
    ) -> dict[str, Any]:
        if dimension not in MASTERY_DIMENSIONS:
            raise LearningExecutionError(422, "invalid_review_dimension", "不支持的评审维度。")
        if conclusion not in {"meets", "needs_work", "uncertain"}:
            raise LearningExecutionError(422, "invalid_review_conclusion", "不支持的评审结论。")
        normalized_relationship = reviewer_relationship.strip()
        if not normalized_relationship:
            raise LearningExecutionError(
                422,
                "independent_review_relationship_required",
                "真人评审必须记录评审者与学习者的关系。",
            )
        now = self._now()
        if _aware_utc(reviewed_at) > _aware_utc(now):
            raise LearningExecutionError(
                422,
                "independent_review_future_dated",
                "真人评审日期不能晚于当前时间。",
            )
        normalized_capabilities = sorted(set(capability_ids))
        if not normalized_capabilities:
            raise LearningExecutionError(
                422,
                "independent_review_scope_required",
                "真人评审必须绑定至少一个精确能力 ID。",
            )
        with self._session_factory() as database:
            run = self._run(database, run_id)
            if run.status == "ended":
                raise LearningExecutionError(
                    409,
                    "learning_run_read_only",
                    "已明确结束的学习执行不可追加评审。",
                )
            package = self._package(run.skill_id, run.skill_version)
            graph = self._content(package, "capability_graph")
            known_capabilities = {item["id"] for item in graph["capabilities"]}
            if not set(normalized_capabilities) <= known_capabilities:
                raise LearningExecutionError(
                    422,
                    "independent_review_scope_unknown",
                    "真人评审包含不属于精确技能版本的能力 ID。",
                )
            if activity_id is not None:
                activity = database.get(LearningActivity, activity_id)
                if activity is None or activity.run_id != run.id:
                    raise LearningExecutionError(
                        422,
                        "independent_review_activity_mismatch",
                        "真人评审活动不属于当前学习执行。",
                    )
                definition = cast(dict[str, Any], json.loads(activity.definition_json))
                if not set(normalized_capabilities) <= set(definition.get("capability_ids", [])):
                    raise LearningExecutionError(
                        422,
                        "independent_review_scope_mismatch",
                        "真人评审范围必须精确落在所绑定活动的能力范围内。",
                    )
            rubric = self._content(package, "rubric_definition")
            expected_rubric_id = f"{dimension}-rubric"
            known_rubrics = {item["id"] for item in rubric["criteria"]}
            if rubric_id != expected_rubric_id or rubric_id not in known_rubrics:
                raise LearningExecutionError(
                    422,
                    "independent_review_rubric_unapproved",
                    "真人评审必须使用当前技能版本和维度的受管独立评审量表。",
                )
            if rubric_version != rubric["schema_version"]:
                raise LearningExecutionError(
                    422,
                    "independent_review_rubric_version_mismatch",
                    "真人评审量表版本与当前技能版本不一致。",
                )
            review = LearningIndependentReview(
                id=str(uuid4()),
                run_id=run.id,
                activity_id=activity_id,
                capability_ids_json=canonical_json(normalized_capabilities),
                dimension=dimension,
                reviewer_relationship=normalized_relationship,
                rubric_id=rubric_id,
                rubric_version=rubric_version,
                conclusion=conclusion,
                reviewed_at=reviewed_at,
                expires_at=_aware_utc(reviewed_at) + timedelta(days=EVIDENCE_VALID_DAYS),
                created_at=now,
            )
            database.add(review)
            self._event(
                database,
                run.id,
                "independent_review_recorded",
                {
                    "review_id": review.id,
                    "activity_id": activity_id,
                    "capability_ids": normalized_capabilities,
                    "dimension": dimension,
                    "reviewer_relationship": normalized_relationship,
                    "rubric_id": rubric_id,
                    "rubric_version": rubric_version,
                    "conclusion": conclusion,
                    "expires_at": review.expires_at.isoformat(),
                    "attachments_stored": False,
                },
                now,
            )
            database.commit()
            return self._independent_review_payload(review, now)

    def get_branch_gates(self, run_id: str) -> dict[str, Any]:
        now = self._now()
        with self._session_factory() as database:
            run = self._run(database, run_id)
            package = self._package(run.skill_id, run.skill_version)
            if not self._is_common_core(package):
                raise LearningExecutionError(
                    409,
                    "branch_gate_policy_unavailable",
                    "该精确技能版本没有四分支门禁策略。",
                )
            policy = self._content(package, "branch_gate_policy")
            graph = self._content(package, "capability_graph")
            capability_titles = {item["id"]: item["title"] for item in graph["capabilities"]}
            evidence = database.scalars(
                select(MasteryEvidence).where(
                    MasteryEvidence.run_id == run.id,
                    MasteryEvidence.superseded_at.is_(None),
                )
            ).all()
            reviews = database.scalars(
                select(LearningIndependentReview).where(LearningIndependentReview.run_id == run.id)
            ).all()
            source_pending = self._source_review_pending(package)
            gates = [
                self._evaluate_branch_gate(
                    gate,
                    evidence,
                    reviews,
                    capability_titles,
                    source_pending,
                    now,
                )
                for gate in policy["gates"]
            ]
            return {
                "run_id": run.id,
                "skill_id": run.skill_id,
                "skill_version": run.skill_version,
                "policy_id": policy["id"],
                "policy_version": policy["version"],
                "evaluated_at": now,
                "selected_branch_id": None,
                "selection_required": True,
                "gates": gates,
                "limitations": [
                    "门禁只计算共同主干后的入口资格，不创建四分支课程。",
                    "学习执行 completed、基础设施探针、自评或 AI 评价均不能自动解锁。",
                    "未选择目标时系统不会代替用户选择工程、面试、竞赛或理论分支。",
                ],
            }

    def get_reviews(self, run_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as database:
            run = self._run(database, run_id)
            self._refresh_due_reviews(database, run, self._now())
            database.commit()
            tasks = database.scalars(
                select(ReviewTask)
                .where(ReviewTask.run_id == run.id)
                .order_by(ReviewTask.checkpoint_index, ReviewTask.attempt_number)
            ).all()
            return [self._review_payload(task, self._now()) for task in tasks]

    def start_review(self, review_id: str) -> dict[str, Any]:
        now = self._now()
        with self._session_factory() as database:
            review = database.get(ReviewTask, review_id)
            if review is None:
                raise LearningExecutionError(
                    404,
                    "review_task_not_found",
                    "Review task not found.",
                )
            run = self._run(database, review.run_id)
            if run.status == "paused":
                raise LearningExecutionError(
                    409,
                    "learning_run_paused",
                    "学习执行已暂停；恢复后才能开始复习。",
                )
            self._refresh_due_reviews(database, run, now)
            if review.status != "available":
                raise LearningExecutionError(
                    409,
                    "review_task_not_available",
                    "The review task is not due yet or is already closed.",
                )
            activity = cast(LearningActivity, database.get(LearningActivity, review.activity_id))
            return {
                "review": self._review_payload(review, now),
                "activity": self._activity_payload(database, activity, now),
            }

    def pause_run(self, run_id: str, reason: str) -> dict[str, Any]:
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 500:
            raise LearningExecutionError(
                422,
                "invalid_pause_reason",
                "暂停原因必须为 1 至 500 个字符。",
            )
        now = self._now()
        with self._session_factory() as database:
            run = self._run(database, run_id)
            if run.status not in {"active", "retention_pending"}:
                raise LearningExecutionError(
                    409,
                    "learning_run_not_pausable",
                    "只有进行中或待复习的学习执行可以暂停。",
                )
            previous_status = run.status
            run.status = "paused"
            run.paused_at = now
            run.pause_reason = normalized_reason
            run.updated_at = now
            self._event(
                database,
                run.id,
                "learning_run_paused",
                {
                    "previous_status": previous_status,
                    "reason": normalized_reason,
                    "meaning": "pause_not_failure",
                },
                now,
            )
            database.commit()
            return self._run_payload(database, run)

    def resume_run(self, run_id: str) -> dict[str, Any]:
        now = self._now()
        with self._session_factory() as database:
            run = self._run(database, run_id)
            if run.status != "paused":
                raise LearningExecutionError(
                    409,
                    "learning_run_not_paused",
                    "只有已暂停的学习执行可以恢复。",
                )
            run.status = "retention_pending" if run.retention_started_at else "active"
            previous_pause_reason = run.pause_reason
            run.paused_at = None
            run.pause_reason = None
            run.updated_at = now
            self._refresh_due_reviews(database, run, now)
            self._event(
                database,
                run.id,
                "learning_run_resumed",
                {
                    "next_status": run.status,
                    "previous_pause_reason": previous_pause_reason,
                    "overdue_tasks_are_not_failures": True,
                },
                now,
            )
            database.commit()
            return self._run_payload(database, run)

    def end_run(self, run_id: str) -> dict[str, Any]:
        now = self._now()
        with self._session_factory() as database:
            run = self._run(database, run_id)
            if run.status not in {"active", "paused", "retention_pending"}:
                raise LearningExecutionError(
                    409,
                    "learning_run_terminal",
                    "This learning run is already terminal.",
                )
            run.status = "ended"
            run.ended_at = now
            run.end_reason = "user_ended"
            run.updated_at = now
            self._event(
                database,
                run.id,
                "learning_run_ended",
                {"reason": "user_ended"},
                now,
            )
            database.commit()
            return self._run_payload(database, run)

    def _package(self, skill_id: str, skill_version: str) -> SkillPackage:
        try:
            return self._packages[(skill_id, skill_version)]
        except KeyError as error:
            raise LearningExecutionError(
                404,
                "skill_package_not_found",
                "The requested skill package version is not registered.",
            ) from error

    def _validate_runner_result(
        self,
        invocation: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        errors = sorted(self._runner_result_validator.iter_errors(result), key=str)
        if errors:
            raise RunnerProtocolError(errors[0].message)
        exact_fields = (
            ("protocol_version", invocation["protocol_version"]),
            ("audit_id", invocation["audit_id"]),
            ("artifact_sha256", invocation["artifact_sha256"]),
        )
        for field, expected in exact_fields:
            if result[field] != expected:
                raise RunnerProtocolError(f"Runner result {field} does not match request")
        for field in ("id", "version", "image"):
            if result["runtime"][field] != invocation["runtime"][field]:
                raise RunnerProtocolError(f"Runner result runtime {field} does not match request")
        expected_image_id = (
            "sha256:" + invocation["runtime"]["image"].rsplit("@sha256:", maxsplit=1)[1]
        )
        observed_image_id = result["runtime"]["observed_image_id"]
        if observed_image_id is not None and observed_image_id != expected_image_id:
            raise RunnerProtocolError(
                "Runner observed image digest does not match the locked image"
            )
        if result["status"] == "passed":
            if result["failure_code"] is not None:
                raise RunnerProtocolError("passed Runner result has a failure code")
            if observed_image_id != expected_image_id:
                raise RunnerProtocolError(
                    "passed Runner result lacks the locked observed image digest"
                )
            expected_tests = invocation["tests"]
            actual_tests = result["tests"]
            if [item["id"] for item in actual_tests] != [item["id"] for item in expected_tests]:
                raise RunnerProtocolError(
                    "passed Runner result does not contain the exact requested test set"
                )
            for expected, actual in zip(expected_tests, actual_tests, strict=True):
                if (
                    actual["status"] != "passed"
                    or actual["exit_code"] != 0
                    or actual["output_truncated"]
                    or self._normalize_runner_output(actual["stdout"])
                    != self._normalize_runner_output(expected["expected_stdout"])
                ):
                    raise RunnerProtocolError("passed Runner result contains an unsuccessful test")
        elif result["failure_code"] is None:
            raise RunnerProtocolError("unsuccessful Runner result lacks a failure code")

    @staticmethod
    def _normalize_runner_output(value: str) -> str:
        return value.replace("\r\n", "\n").rstrip()

    def _evidence_limitations(self, run: LearningRun) -> list[str]:
        package = self._package(run.skill_id, run.skill_version)
        if any(
            item.get("kind") == "runner_task_definition"
            for item in package.manifest.get("content_files", [])
        ):
            return [
                "verified 只适用于锁定 Runner、运行时摘要和确定性测试覆盖的对应操作范围。",
                "retained 只来自延迟的同范围 Runner 复测，不表示永久保持。",
                "Runner 证据不表示整体掌握、scope_criteria_met、分支自动解锁或 5C 门禁解除。",
                "用户自评仍不是独立人工审核。",
            ]
        return [
            "4A 不产生 scope_criteria_met、verified 或不受限 retained。",
            "代码文本未执行，用户自评不是独立人工审核。",
        ]

    def _content(self, package: SkillPackage, kind: str) -> dict[str, Any]:
        key = (package.package_id, package.version, kind)
        if key in self._content_cache:
            return self._content_cache[key]
        entries = [item for item in package.manifest["content_files"] if item["kind"] == kind]
        if len(entries) != 1:
            raise LearningExecutionError(
                409,
                f"{kind}_unavailable",
                f"The package must contain exactly one {kind}.",
            )
        raw = yaml.safe_load((package.path / entries[0]["path"]).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError(f"{kind} must be a YAML object")
        result = cast(dict[str, Any], raw)
        self._content_cache[key] = result
        return result

    def _run(self, database: Session, run_id: str) -> LearningRun:
        run = database.get(LearningRun, run_id)
        if run is None:
            raise LearningExecutionError(
                404,
                "learning_run_not_found",
                "Learning run not found.",
            )
        return run

    @staticmethod
    def _is_common_core(package: SkillPackage) -> bool:
        return any(
            item.get("kind") == "branch_gate_policy"
            for item in package.manifest.get("content_files", [])
        )

    @staticmethod
    def _daily_priority(activity: LearningActivity) -> tuple[int]:
        if activity.activity_type == "review":
            return (0,)
        if activity.activity_type == "correction" or activity.status == "correction_required":
            return (1,)
        if activity.activity_type in {
            "structured_check",
            "code_text",
            "transfer",
            "project_evidence",
        }:
            return (2,)
        return (3,)

    def _daily_priority_label(self, activity: LearningActivity) -> tuple[str, int]:
        rank = self._daily_priority(activity)[0]
        return (
            (
                "due_retention"
                if rank == 0
                else "failed_correction"
                if rank == 1
                else "blocking_prerequisite"
                if rank == 2
                else "new_content"
            ),
            rank + 1,
        )

    @staticmethod
    def _activity_domain(definition: dict[str, Any]) -> str:
        capability_ids = definition.get("capability_ids", [])
        if not capability_ids:
            return ""
        first = str(capability_ids[0])
        return first.split("-", maxsplit=1)[0]

    def _deferred_task_payload(
        self,
        activity: LearningActivity,
        reason_code: str,
    ) -> dict[str, Any]:
        priority, rank = self._daily_priority_label(activity)
        return {
            "activity_id": activity.id,
            "title": activity.title,
            "estimated_minutes": activity.estimated_minutes,
            "daily_priority": priority,
            "daily_priority_rank": rank,
            "reason_code": reason_code,
            "meaning": "追加式顺延，不记为能力失败。",
        }

    def _source_review_pending(self, package: SkillPackage) -> bool:
        catalog = self._content(package, "source_catalog")
        return any(
            "未进行远程实质内容复核" in str(item.get("access_note", ""))
            for item in catalog.get("sources", [])
        )

    @staticmethod
    def _independent_review_payload(
        review: LearningIndependentReview,
        now: datetime,
    ) -> dict[str, Any]:
        return {
            "id": review.id,
            "run_id": review.run_id,
            "activity_id": review.activity_id,
            "capability_ids": json.loads(review.capability_ids_json),
            "dimension": review.dimension,
            "reviewer_relationship": review.reviewer_relationship,
            "rubric_id": review.rubric_id,
            "rubric_version": review.rubric_version,
            "conclusion": review.conclusion,
            "reviewed_at": review.reviewed_at,
            "expires_at": review.expires_at,
            "expired": _aware_utc(review.expires_at) < _aware_utc(now),
            "created_at": review.created_at,
            "attachments_stored": False,
        }

    def _evaluate_branch_gate(
        self,
        gate: dict[str, Any],
        evidence: Sequence[MasteryEvidence],
        reviews: Sequence[LearningIndependentReview],
        capability_titles: dict[str, str],
        source_pending: bool,
        now: datetime,
    ) -> dict[str, Any]:
        required = set(gate["required_capability_ids"])
        valid_after = _aware_utc(now) - timedelta(days=EVIDENCE_VALID_DAYS)
        current_by_capability: dict[str, list[MasteryEvidence]] = {
            capability_id: [] for capability_id in required
        }
        expired_capabilities: set[str] = set()
        future_capabilities: set[str] = set()
        for item in evidence:
            scoped = set(json.loads(item.capability_ids_json)) & required
            if not scoped:
                continue
            created_at = _aware_utc(item.created_at)
            if created_at > _aware_utc(now):
                future_capabilities.update(scoped)
                continue
            if created_at < valid_after:
                expired_capabilities.update(scoped)
                continue
            for capability_id in scoped:
                current_by_capability[capability_id].append(item)

        missing_details: list[dict[str, Any]] = []
        satisfied_capabilities: list[str] = []
        blocking_flags: set[str] = set()
        for capability_id in sorted(required):
            capability_missing = False
            items = current_by_capability[capability_id]
            for dimension, minimum in gate["minimum_levels"].items():
                dimension_items = [item for item in items if item.dimension == dimension]
                actual = max(
                    (dimension_items),
                    key=lambda item: EVIDENCE_RANK[item.strength],
                    default=None,
                )
                actual_level = actual.strength if actual else "none"
                if EVIDENCE_RANK[actual_level] < EVIDENCE_RANK[minimum]:
                    capability_missing = True
                    missing_details.append(
                        {
                            "capability_id": capability_id,
                            "title": capability_titles[capability_id],
                            "dimension": dimension,
                            "required_level": minimum,
                            "actual_level": actual_level,
                            "state": (
                                "future_invalid"
                                if capability_id in future_capabilities
                                else "expired"
                                if capability_id in expired_capabilities
                                else "missing"
                            ),
                        }
                    )
                elif actual is not None:
                    blocking_flags.update(json.loads(actual.review_flags_json))
            if not capability_missing:
                satisfied_capabilities.append(capability_id)

        retained_capabilities = sorted(
            {
                capability_id
                for capability_id, items in current_by_capability.items()
                if any(item.strength == "retained" for item in items)
            }
        )
        retained_shortfall = max(
            0,
            gate["required_retained_count"] - len(retained_capabilities),
        )
        missing_independent_reviews: list[dict[str, str]] = []
        for dimension in gate["independent_review_dimensions"]:
            for capability_id in sorted(required):
                matched = any(
                    item.dimension == dimension
                    and item.conclusion == "meets"
                    and capability_id in json.loads(item.capability_ids_json)
                    and _aware_utc(item.reviewed_at) <= _aware_utc(now)
                    and _aware_utc(item.expires_at) >= _aware_utc(now)
                    for item in reviews
                )
                if not matched:
                    missing_independent_reviews.append(
                        {
                            "capability_id": capability_id,
                            "title": capability_titles[capability_id],
                            "dimension": dimension,
                        }
                    )

        relevant_blocking_flags = blocking_flags & set(gate["blocking_review_flags"])
        if source_pending and "source_review_pending" in gate["blocking_review_flags"]:
            relevant_blocking_flags.add("source_review_pending")
        if future_capabilities and "version_mismatch" in gate["blocking_review_flags"]:
            relevant_blocking_flags.add("version_mismatch")
        eligible = not (
            missing_details
            or retained_shortfall
            or missing_independent_reviews
            or relevant_blocking_flags
        )
        return {
            "id": gate["id"],
            "title": gate["title"],
            "status": "eligible" if eligible else "blocked",
            "selected": False,
            "required_capability_ids": gate["required_capability_ids"],
            "satisfied_capability_ids": satisfied_capabilities,
            "expired_capability_ids": sorted(expired_capabilities & required),
            "future_invalid_capability_ids": sorted(future_capabilities & required),
            "missing_requirements": missing_details,
            "retained_capability_ids": retained_capabilities,
            "required_retained_count": gate["required_retained_count"],
            "retained_shortfall": retained_shortfall,
            "missing_independent_reviews": missing_independent_reviews,
            "blocking_review_flags": sorted(relevant_blocking_flags),
            "limitations": gate["limitations"],
            "meaning": "入口资格仅适用于列出的共同主干能力范围，不表示整门算法掌握。",
        }

    def _is_historical(
        self,
        proposal: PlanningProposal,
        latest_diagnostic: DiagnosticSession | None,
        latest_proposal: PlanningProposal | None,
    ) -> bool:
        return bool(
            (
                latest_diagnostic is not None
                and _aware_utc(proposal.created_at) < _aware_utc(latest_diagnostic.created_at)
            )
            or (
                latest_proposal is not None
                and latest_proposal.id != proposal.id
                and _aware_utc(proposal.created_at) < _aware_utc(latest_proposal.created_at)
            )
        )

    def _planning_option_payload(
        self,
        database: Session,
        proposal: PlanningProposal,
        latest_diagnostic: DiagnosticSession | None,
        latest_proposal: PlanningProposal | None,
    ) -> dict[str, Any]:
        diagnostic = database.get(DiagnosticSession, proposal.diagnostic_session_id)
        source_pending = database.scalar(
            select(func.count(SourceChangeCandidate.id)).where(
                SourceChangeCandidate.skill_id == proposal.skill_id,
                SourceChangeCandidate.skill_version == proposal.skill_version,
                SourceChangeCandidate.status.in_(["pending", "accepted"]),
            )
        )
        return {
            "id": proposal.id,
            "title": proposal.title,
            "diagnostic_session_id": proposal.diagnostic_session_id,
            "diagnostic_created_at": diagnostic.created_at if diagnostic else None,
            "saved_at": proposal.updated_at,
            "is_historical": self._is_historical(
                proposal,
                latest_diagnostic,
                latest_proposal,
            ),
            "has_newer_diagnostic": bool(
                latest_diagnostic
                and diagnostic
                and _aware_utc(diagnostic.created_at) < _aware_utc(latest_diagnostic.created_at)
            ),
            "has_newer_plan": bool(latest_proposal and latest_proposal.id != proposal.id),
            "source_review_pending": bool(source_pending),
        }

    def _create_unit_instances(
        self,
        database: Session,
        run: LearningRun,
        learning: dict[str, Any],
        planning_units: Sequence[PlanningUnit],
    ) -> dict[str, LearningUnitInstance]:
        planning_by_id = {unit.template_unit_id: unit for unit in planning_units}
        instances: dict[str, LearningUnitInstance] = {}
        for sequence, definition in enumerate(learning["units"], start=1):
            planning = planning_by_id.get(definition["id"])
            reason = planning.reason if planning else definition["reason"]
            instance = LearningUnitInstance(
                id=str(uuid4()),
                run_id=run.id,
                template_unit_id=definition["id"],
                sequence=sequence,
                title=planning.title if planning else definition["title"],
                reason=reason,
                snapshot_json=canonical_json(definition),
                status="active" if sequence == 1 else "pending",
            )
            database.add(instance)
            instances[definition["id"]] = instance
        database.flush()
        return instances

    def _latest_diagnostic_signals(
        self,
        database: Session,
        diagnostic_session_id: str,
    ) -> dict[str, str]:
        answers = database.scalars(
            select(DiagnosticAnswer)
            .where(DiagnosticAnswer.session_id == diagnostic_session_id)
            .order_by(DiagnosticAnswer.question_id, DiagnosticAnswer.revision.desc())
        ).all()
        signals: dict[str, str] = {}
        for answer in answers:
            if answer.question_id in signals:
                continue
            signals[answer.question_id] = (
                answer.content
                if answer.response_kind == "answered" and answer.content
                else answer.response_kind
            )
        return signals

    def _selected_remediation(
        self,
        database: Session,
        diagnostic_session_id: str,
        learning: dict[str, Any],
    ) -> tuple[set[str], dict[str, str]]:
        signals = self._latest_diagnostic_signals(database, diagnostic_session_id)
        selected: set[str] = set()
        reasons: dict[str, str] = {}
        for rule in learning["diagnostic_remediation_rules"]:
            if signals.get(rule["question_id"]) not in rule["response_values"]:
                continue
            for activity_id in rule["activity_ids"]:
                selected.add(activity_id)
                reasons[activity_id] = rule["reason"]
        return selected, reasons

    def _create_initial_activities(
        self,
        database: Session,
        run: LearningRun,
        learning: dict[str, Any],
        units: dict[str, LearningUnitInstance],
        selected_remediation: set[str],
        remediation_reasons: dict[str, str],
        now: datetime,
    ) -> None:
        sequence = 0
        for definition in learning["activities"]:
            if definition["type"] == "review":
                continue
            if not definition["required"] and definition["id"] not in selected_remediation:
                continue
            sequence += 1
            unit = units[definition["unit_id"]]
            unit_definition = cast(dict[str, Any], json.loads(unit.snapshot_json))
            stored_definition = {
                **definition,
                "unit_cognitive_load": unit_definition.get("cognitive_load", "medium"),
            }
            reason = definition["reason"]
            if definition["id"] in remediation_reasons:
                reason = f"{reason} 诊断依据：{remediation_reasons[definition['id']]}"
            database.add(
                LearningActivity(
                    id=str(uuid4()),
                    run_id=run.id,
                    unit_instance_id=unit.id,
                    template_activity_id=definition["id"],
                    activity_type=definition["type"],
                    sequence=sequence,
                    title=definition["title"],
                    reason=reason,
                    estimated_minutes=definition["estimated_minutes"],
                    required=definition["required"] or definition["id"] in selected_remediation,
                    status="available" if unit.sequence == 1 else "pending",
                    definition_json=canonical_json(stored_definition),
                    available_at=now if unit.sequence == 1 else None,
                )
            )

    def _validate_submission(
        self,
        definition: dict[str, Any],
        submission: dict[str, str],
    ) -> None:
        field_by_id = {field["id"]: field for field in definition["submission_fields"]}
        unknown = set(submission) - set(field_by_id)
        if unknown:
            raise LearningExecutionError(
                422,
                "unexpected_submission_fields",
                f"Unexpected submission fields: {sorted(unknown)}",
            )
        for field_id, field in field_by_id.items():
            value = submission.get(field_id, "")
            if field["required"] and not value.strip():
                raise LearningExecutionError(
                    422,
                    "required_submission_field_missing",
                    f"Submission field {field_id} is required.",
                )
            if value and not field["min_length"] <= len(value) <= field["max_length"]:
                raise LearningExecutionError(
                    422,
                    "invalid_submission_field_length",
                    f"Submission field {field_id} has an invalid length.",
                )
            if field["kind"] == "choice" and value not in field.get("options", []):
                raise LearningExecutionError(
                    422,
                    "invalid_submission_choice",
                    f"Submission field {field_id} has an invalid choice.",
                )
            if field["kind"] == "confirmation" and value not in {"true", "confirmed"}:
                raise LearningExecutionError(
                    422,
                    "confirmation_required",
                    f"Submission field {field_id} must be confirmed.",
                )

    def _evaluate_attempt(
        self,
        definition: dict[str, Any],
        submission: dict[str, str],
        mark_uncertain: bool,
    ) -> tuple[str, str, dict[str, Any]]:
        if mark_uncertain:
            return "deterministic", "uncertain", {"marked_uncertain": True}
        deterministic = definition.get("deterministic_check")
        if deterministic is not None:
            actual = submission[deterministic["field_id"]]
            passed = actual in deterministic["accepted_values"]
            return (
                "deterministic",
                "passed" if passed else "failed",
                {
                    "passed": passed,
                    "feedback": deterministic["feedback"],
                },
            )
        if definition["type"] == "code_text":
            if definition.get("runner_task_id"):
                return (
                    "review_pending",
                    "review_pending",
                    {"runner_execution": "pending"},
                )
            return (
                "not_executable",
                "not_executable",
                {"code_execution": "disabled"},
            )
        if definition["type"] == "project_evidence":
            return (
                "review_pending",
                "review_pending",
                {"independent_review": "unavailable"},
            )
        if definition["type"] in {"explanation", "transfer", "correction"}:
            return (
                "review_pending",
                "review_pending",
                {"independent_review": "unavailable"},
            )
        return "deterministic", "submitted", {"structure_valid": True}

    def _create_evidence(
        self,
        database: Session,
        run: LearningRun,
        activity: LearningActivity,
        attempt: ActivityAttempt,
        evaluation: ActivityEvaluation,
        now: datetime,
    ) -> int:
        package = self._package(run.skill_id, run.skill_version)
        assessment = self._content(package, "assessment_definition")
        definition = cast(dict[str, Any], json.loads(activity.definition_json))
        template_id = activity.template_activity_id.split(":", maxsplit=1)[0]
        criteria = [
            criterion
            for criterion in assessment["criteria"]
            if criterion["activity_id"] == template_id
        ]
        created = 0
        for criterion in criteria:
            if evaluation.result in {"failed", "uncertain"}:
                continue
            method = evaluation.method
            if criterion["evaluation_method"] == "runner" and method != "runner":
                continue
            if method == "runner" and criterion["evaluation_method"] != "runner":
                continue
            strength = criterion["evidence_strength"]
            dimension = criterion["dimension"]
            flags = set(criterion["review_flags"])
            if method == "self_review":
                strength = "limited"
                flags.add("manual_review_pending")
            if method in {"review_pending", "not_executable"}:
                strength = "limited"
                flags.add("manual_review_pending")
            if (
                dimension == "correction"
                and activity.template_activity_id != "checkpoint-correction"
                and not self._is_common_core(package)
            ):
                strength = "limited"
            if (
                activity.activity_type == "review"
                and method == "runner"
                and definition.get("retention_of_activity_id")
            ):
                dimension = "retention"
                strength = "retained"
            ceiling = definition.get("evidence_ceiling")
            if ceiling == "none":
                continue
            if ceiling in EVIDENCE_RANK and EVIDENCE_RANK[strength] > EVIDENCE_RANK[ceiling]:
                strength = ceiling
            criterion_capabilities = set(criterion.get("capability_ids", []))
            activity_capabilities = set(definition.get("capability_ids", []))
            capability_ids = sorted(
                criterion_capabilities & activity_capabilities
                if criterion_capabilities and activity_capabilities
                else criterion_capabilities or activity_capabilities
            )
            language = str(criterion.get("language", definition.get("language", "none")))
            database.add(
                MasteryEvidence(
                    id=str(uuid4()),
                    run_id=run.id,
                    activity_id=activity.id,
                    attempt_id=attempt.id,
                    evaluation_id=evaluation.id,
                    criterion_id=(
                        f"{criterion['id']}:retention"
                        if dimension == "retention" and method == "runner"
                        else criterion["id"]
                    ),
                    dimension=dimension,
                    method=method,
                    result=evaluation.result,
                    strength=strength,
                    review_flags_json=canonical_json(sorted(flags)),
                    rubric_version="1.0.0",
                    capability_ids_json=canonical_json(capability_ids),
                    language=language,
                    created_at=now,
                )
            )
            created += 1
        return created

    def _notify_evidence_update(
        self,
        run: LearningRun,
        activity: LearningActivity,
        attempt: ActivityAttempt,
        evidence_count: int,
    ) -> None:
        if evidence_count == 0 or self._notifications is None:
            return
        self._notifications.create(
            category="evidence_update",
            severity="info",
            title="学习证据已更新",
            message=(
                f"“{activity.title}”本次提交已为对应能力范围记录 {evidence_count} 条证据。"
                "请核对证据等级和待复核标记；这不表示整门技能已经掌握。"
            ),
            related_type="learning_run",
            related_id=run.id,
            deduplication_key=f"evidence-updated:{attempt.id}",
        )

    def _advance_initial_learning(
        self,
        database: Session,
        run: LearningRun,
        now: datetime,
    ) -> None:
        units = database.scalars(
            select(LearningUnitInstance)
            .where(LearningUnitInstance.run_id == run.id)
            .order_by(LearningUnitInstance.sequence)
        ).all()
        activities = database.scalars(
            select(LearningActivity)
            .where(
                LearningActivity.run_id == run.id,
                LearningActivity.activity_type != "review",
            )
            .order_by(LearningActivity.sequence)
        ).all()
        activities_by_unit: dict[str, list[LearningActivity]] = {}
        for activity in activities:
            activities_by_unit.setdefault(activity.unit_instance_id, []).append(activity)
        for unit in units:
            unit_activities = activities_by_unit.get(unit.id, [])
            if unit_activities and all(item.status == "completed" for item in unit_activities):
                unit.status = "completed"
                unit.completed_at = unit.completed_at or now
                next_unit = next(
                    (candidate for candidate in units if candidate.sequence == unit.sequence + 1),
                    None,
                )
                if next_unit is not None and next_unit.status == "pending":
                    next_unit.status = "active"
                    for activity in activities_by_unit.get(next_unit.id, []):
                        if activity.status == "pending":
                            activity.status = "available"
                            activity.available_at = now
        if (
            run.status == "active"
            and activities
            and all(activity.status == "completed" for activity in activities)
        ):
            run.status = "retention_pending"
            run.retention_started_at = now
            self._schedule_review(database, run, checkpoint_index=1, attempt_number=1, now=now)
            self._event(
                database,
                run.id,
                "initial_learning_completed",
                {"next_status": "retention_pending"},
                now,
            )

    def _schedule_review(
        self,
        database: Session,
        run: LearningRun,
        *,
        checkpoint_index: int,
        attempt_number: int,
        now: datetime,
        retry: bool = False,
    ) -> None:
        package = self._package(run.skill_id, run.skill_version)
        policy = self._content(package, "review_policy")
        learning = self._content(package, "learning_definition")
        template = next(
            (
                activity
                for activity in learning["activities"]
                if activity["id"] == "retention-review-template"
            ),
            None,
        )
        if template is None:
            review_templates = [
                activity for activity in learning["activities"] if activity["type"] == "review"
            ]
            template = {
                "id": "common-core-retention-review",
                "type": "review",
                "title": "共同主干固定延迟复习检查",
                "prompt": "完成到期主动提取后选择 reviewed；若仍不确定请选择 uncertain 并先纠错。",
                "reason": "固定 1、2、4、7、15 天策略的范围化复习检查。",
                "estimated_minutes": 20,
                "required": True,
                "completion_rule": "deterministic_pass",
                "source_ids": sorted(
                    {
                        source_id
                        for item in review_templates
                        for source_id in item.get("source_ids", [])
                    }
                ),
                "capability_ids": sorted(
                    {
                        capability_id
                        for item in review_templates
                        for capability_id in item.get("capability_ids", [])
                    }
                ),
                "activity_roles": ["review"],
                "language": "none",
                "evidence_ceiling": "none",
                "submission_fields": [
                    {
                        "id": "result",
                        "kind": "choice",
                        "label": "延迟复习结果",
                        "required": True,
                        "min_length": 1,
                        "max_length": 20,
                        "options": ["reviewed", "uncertain"],
                    }
                ],
                "deterministic_check": {
                    "field_id": "result",
                    "accepted_values": ["reviewed"],
                    "feedback": "流程通过不表示掌握；Runner 保持证据仍须同范围复测。",
                },
            }
        interval_days = (
            policy["failure_retry_days"] if retry else policy["interval_days"][checkpoint_index - 1]
        )
        due_at = (
            _aware_utc(now) + timedelta(days=interval_days)
            if retry
            else _aware_utc(cast(datetime, run.retention_started_at))
            + timedelta(days=interval_days)
        )
        unit = database.scalar(
            select(LearningUnitInstance)
            .where(LearningUnitInstance.run_id == run.id)
            .order_by(LearningUnitInstance.sequence.desc())
        )
        sequence = (
            database.scalar(
                select(func.max(LearningActivity.sequence)).where(LearningActivity.run_id == run.id)
            )
            or 0
        ) + 1
        definition = {
            **template,
            "checkpoint_index": checkpoint_index,
            "attempt_number": attempt_number,
        }
        if self._is_common_core(package):
            original_runner_activities = database.scalars(
                select(LearningActivity).where(
                    LearningActivity.run_id == run.id,
                    LearningActivity.activity_type == "code_text",
                    LearningActivity.status == "completed",
                )
            ).all()
            for original in original_runner_activities:
                original_definition = cast(dict[str, Any], json.loads(original.definition_json))
                replay_definition = {
                    **original_definition,
                    "type": "review",
                    "title": f"延迟 Runner 复测 · {original.title}",
                    "reason": "只有同语言、同任务、同运行时和完整测试再次通过才产生 retained。",
                    "evidence_ceiling": "retained",
                    "activity_roles": ["review", "runner_retention"],
                    "checkpoint_index": checkpoint_index,
                    "attempt_number": attempt_number,
                    "retention_of_activity_id": original.id,
                }
                database.add(
                    LearningActivity(
                        id=str(uuid4()),
                        run_id=run.id,
                        unit_instance_id=original.unit_instance_id,
                        template_activity_id=(
                            f"{original.template_activity_id}:retention:"
                            f"{checkpoint_index}:{attempt_number}"
                        ),
                        activity_type="review",
                        sequence=sequence,
                        title=replay_definition["title"],
                        reason=replay_definition["reason"],
                        estimated_minutes=original.estimated_minutes,
                        required=True,
                        status="available" if _aware_utc(now) >= due_at else "pending",
                        definition_json=canonical_json(replay_definition),
                        available_at=due_at,
                    )
                )
                database.flush()
                sequence += 1
        activity = LearningActivity(
            id=str(uuid4()),
            run_id=run.id,
            unit_instance_id=cast(LearningUnitInstance, unit).id,
            template_activity_id=f"{template['id']}:{checkpoint_index}:{attempt_number}",
            activity_type="review",
            sequence=sequence,
            title=f"{template['title']} · 第 {checkpoint_index} 个检查点",
            reason=(
                f"锁定复习策略要求在第 {policy['interval_days'][checkpoint_index - 1]} 天"
                "进行主动提取。"
                if not retry
                else "上次复习未通过；完成纠错后按失败规则于次日重测。"
            ),
            estimated_minutes=template["estimated_minutes"],
            required=True,
            status="available" if _aware_utc(now) >= due_at else "pending",
            definition_json=canonical_json(definition),
            available_at=due_at,
        )
        database.add(activity)
        database.flush()
        database.add(
            ReviewTask(
                id=str(uuid4()),
                run_id=run.id,
                activity_id=activity.id,
                checkpoint_index=checkpoint_index,
                attempt_number=attempt_number,
                interval_days=interval_days,
                due_at=due_at,
                status="available" if _aware_utc(now) >= due_at else "scheduled",
                policy_id=policy["id"],
                policy_version=policy["version"],
                created_at=now,
            )
        )
        self._event(
            database,
            run.id,
            "review_scheduled",
            {
                "checkpoint_index": checkpoint_index,
                "attempt_number": attempt_number,
                "interval_days": interval_days,
                "due_at": due_at.isoformat(),
                "retry": retry,
            },
            now,
        )

    def _refresh_due_reviews(
        self,
        database: Session,
        run: LearningRun,
        now: datetime,
    ) -> None:
        if run.status != "retention_pending":
            return
        due_activities = database.scalars(
            select(LearningActivity).where(
                LearningActivity.run_id == run.id,
                LearningActivity.activity_type == "review",
                LearningActivity.status == "pending",
                LearningActivity.available_at.is_not(None),
                LearningActivity.available_at <= now,
            )
        ).all()
        for activity in due_activities:
            activity.status = "available"
        reviews = database.scalars(
            select(ReviewTask).where(
                ReviewTask.run_id == run.id,
                ReviewTask.status == "scheduled",
            )
        ).all()
        for review in reviews:
            if _aware_utc(review.due_at) > _aware_utc(now):
                continue
            review.status = "available"
            review_activity = database.get(LearningActivity, review.activity_id)
            if review_activity is not None and review_activity.status == "pending":
                review_activity.status = "available"
            self._event(
                database,
                run.id,
                "review_became_available",
                {
                    "review_id": review.id,
                    "overdue": _aware_utc(review.due_at).date() < _aware_utc(now).date(),
                },
                now,
            )

    def _pass_review(
        self,
        database: Session,
        run: LearningRun,
        review: ReviewTask,
        now: datetime,
    ) -> None:
        review.status = "passed"
        review.completed_at = now
        package = self._package(run.skill_id, run.skill_version)
        policy = self._content(package, "review_policy")
        if review.checkpoint_index >= policy["completion_checkpoint"]:
            run.status = "completed"
            run.completed_at = now
            run.updated_at = now
            self._event(
                database,
                run.id,
                "learning_run_completed",
                {
                    "meaning": "workflow_completed_not_mastered",
                    "checkpoint_index": review.checkpoint_index,
                },
                now,
            )
        else:
            self._schedule_review(
                database,
                run,
                checkpoint_index=review.checkpoint_index + 1,
                attempt_number=1,
                now=now,
            )

    def _fail_review(
        self,
        database: Session,
        run: LearningRun,
        review: ReviewTask,
        review_definition: dict[str, Any],
        now: datetime,
    ) -> None:
        review.status = "failed"
        review.completed_at = now
        unit = database.scalar(
            select(LearningUnitInstance)
            .where(LearningUnitInstance.run_id == run.id)
            .order_by(LearningUnitInstance.sequence.desc())
        )
        sequence = (
            database.scalar(
                select(func.max(LearningActivity.sequence)).where(LearningActivity.run_id == run.id)
            )
            or 0
        ) + 1
        correction_definition = {
            "id": f"review-correction-{review.id}",
            "type": "correction",
            "title": "复习失败纠错",
            "prompt": "重新判断普通链表按下标访问的复杂度，并确认错误原因。",
            "reason": "复习失败后先完成可确定性验证的纠错，再安排次日重测。",
            "estimated_minutes": 15,
            "required": True,
            "completion_rule": "deterministic_pass",
            "source_ids": review_definition["source_ids"],
            "submission_fields": review_definition["submission_fields"],
            "deterministic_check": review_definition["deterministic_check"],
            "retry_checkpoint_index": review.checkpoint_index,
            "retry_attempt_number": review.attempt_number + 1,
        }
        database.add(
            LearningActivity(
                id=str(uuid4()),
                run_id=run.id,
                unit_instance_id=cast(LearningUnitInstance, unit).id,
                template_activity_id=f"review-correction:{review.id}",
                activity_type="correction",
                sequence=sequence,
                title="复习失败纠错",
                reason="复习未通过或标记不确定；立即纠错，学习执行保持待复习。",
                estimated_minutes=15,
                required=True,
                status="available",
                definition_json=canonical_json(correction_definition),
                available_at=now,
            )
        )
        self._event(
            database,
            run.id,
            "review_failed_correction_added",
            {
                "review_id": review.id,
                "checkpoint_index": review.checkpoint_index,
                "run_status": "retention_pending",
            },
            now,
        )

    def _schedule_retry_after_correction(
        self,
        database: Session,
        run: LearningRun,
        definition: dict[str, Any],
        now: datetime,
    ) -> None:
        self._schedule_review(
            database,
            run,
            checkpoint_index=definition["retry_checkpoint_index"],
            attempt_number=definition["retry_attempt_number"],
            now=now,
            retry=True,
        )

    def _rebuild_snapshots(
        self,
        database: Session,
        run: LearningRun,
        now: datetime,
    ) -> None:
        pending_sources = {
            item.source_id
            for item in database.scalars(
                select(SourceChangeCandidate).where(
                    SourceChangeCandidate.skill_id == run.skill_id,
                    SourceChangeCandidate.skill_version == run.skill_version,
                    SourceChangeCandidate.status.in_(["pending", "accepted"]),
                )
            ).all()
        }
        evidence = database.scalars(
            select(MasteryEvidence).where(
                MasteryEvidence.run_id == run.id,
                MasteryEvidence.superseded_at.is_(None),
            )
        ).all()
        active_by_dimension: dict[str, list[MasteryEvidence]] = {
            dimension: [] for dimension in MASTERY_DIMENSIONS
        }
        for item in evidence:
            active_by_dimension[item.dimension].append(item)
        snapshots = {
            snapshot.dimension: snapshot
            for snapshot in database.scalars(
                select(MasterySnapshot).where(MasterySnapshot.run_id == run.id)
            ).all()
        }
        for dimension in MASTERY_DIMENSIONS:
            items = active_by_dimension[dimension]
            flags: set[str] = set()
            for item in items:
                flags.update(json.loads(item.review_flags_json))
                activity = database.get(LearningActivity, item.activity_id)
                if activity is not None:
                    definition = json.loads(activity.definition_json)
                    if pending_sources & set(definition.get("source_ids", [])):
                        flags.add("source_review_pending")
            if run.status in {"active", "retention_pending"} and dimension in {
                "understanding",
                "transfer",
                "retention",
            }:
                flags.add("retention_due")
            level = "none"
            if items:
                strongest = max(items, key=lambda item: EVIDENCE_RANK[item.strength])
                level = {
                    "supported": "supported",
                    "verified": "verified",
                    "retained": "retained",
                }.get(strongest.strength, "limited")
            snapshot = snapshots[dimension]
            snapshot.evidence_level = level
            snapshot.review_flags_json = canonical_json(sorted(flags))
            snapshot.evidence_count = len(items)
            snapshot.updated_at = now

    def _run_payload(self, database: Session, run: LearningRun) -> dict[str, Any]:
        content_lock = database.get(LearningRunLock, run.id)
        activities = database.scalars(
            select(LearningActivity)
            .where(LearningActivity.run_id == run.id)
            .order_by(LearningActivity.sequence)
        ).all()
        snapshots = database.scalars(
            select(MasterySnapshot)
            .where(MasterySnapshot.run_id == run.id)
            .order_by(MasterySnapshot.dimension)
        ).all()
        reviews = database.scalars(
            select(ReviewTask)
            .where(ReviewTask.run_id == run.id)
            .order_by(ReviewTask.checkpoint_index, ReviewTask.attempt_number)
        ).all()
        next_actions: list[str] = []
        if run.status in {"active", "retention_pending"}:
            if any(item.status in {"available", "correction_required"} for item in activities):
                next_actions.append("generate_today_queue")
            if run.status == "retention_pending":
                next_actions.append("wait_for_or_complete_review")
            next_actions.append("end_run")
            next_actions.append("pause_run")
        elif run.status == "paused":
            next_actions.extend(["resume_run", "end_run"])
        elif run.status in {"completed", "ended"}:
            next_actions.append("reuse_plan_with_confirmation")
        return {
            "id": run.id,
            "planning_proposal_id": run.planning_proposal_id,
            "diagnostic_session_id": run.diagnostic_session_id,
            "skill_id": run.skill_id,
            "skill_version": run.skill_version,
            "status": run.status,
            "is_preview": run.is_preview,
            "code_execution": (
                json.loads(content_lock.lock_json)["capabilities"]["code_execution"]
                if content_lock
                else "disabled"
            ),
            "external_ai": "disabled",
            "selected_historical_plan": run.selected_historical_plan,
            "reused_from_run_id": run.reused_from_run_id,
            "lock_sha256": content_lock.lock_sha256 if content_lock else "",
            "engine_protocol_version": (
                json.loads(content_lock.lock_json).get(
                    "engine_protocol_version", ENGINE_PROTOCOL_VERSION
                )
                if content_lock
                else ENGINE_PROTOCOL_VERSION
            ),
            "runner_protocol_version": (
                json.loads(content_lock.lock_json)["runner_protocol_version"]
                if content_lock
                else self._package(run.skill_id, run.skill_version).manifest["runner_protocol"][
                    "version"
                ]
            ),
            "evidence_limitations": self._evidence_limitations(run),
            "activities": [
                self._activity_payload(database, activity, self._now()) for activity in activities
            ],
            "dimensions": [self._snapshot_payload(snapshot) for snapshot in snapshots],
            "reviews": [self._review_payload(review, self._now()) for review in reviews],
            "next_actions": next_actions,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "retention_started_at": run.retention_started_at,
            "paused_at": run.paused_at,
            "pause_reason": run.pause_reason,
            "completed_at": run.completed_at,
            "ended_at": run.ended_at,
            "end_reason": run.end_reason,
        }

    def _activity_payload(
        self,
        database: Session,
        activity: LearningActivity,
        now: datetime,
    ) -> dict[str, Any]:
        definition = cast(dict[str, Any], json.loads(activity.definition_json))
        attempts = database.scalars(
            select(ActivityAttempt)
            .where(ActivityAttempt.activity_id == activity.id)
            .order_by(ActivityAttempt.revision)
        ).all()
        return {
            "id": activity.id,
            "template_activity_id": activity.template_activity_id,
            "type": activity.activity_type,
            "sequence": activity.sequence,
            "title": activity.title,
            "prompt": definition["prompt"],
            "reason": activity.reason,
            "estimated_minutes": activity.estimated_minutes,
            "required": activity.required,
            "status": activity.status,
            "completion_rule": definition["completion_rule"],
            "submission_fields": definition["submission_fields"],
            "source_ids": definition.get("source_ids", []),
            "capability_ids": definition.get("capability_ids", []),
            "activity_roles": definition.get("activity_roles", []),
            "language": definition.get("language", "none"),
            "evidence_ceiling": definition.get("evidence_ceiling", "limited"),
            "available_at": activity.available_at,
            "overdue": bool(
                activity.available_at
                and activity.status in {"available", "correction_required"}
                and _aware_utc(activity.available_at).date() < _aware_utc(now).date()
            ),
            "attempts": [self._attempt_payload(database, attempt) for attempt in attempts],
            "runner_task_id": definition.get("runner_task_id"),
            "completed_at": activity.completed_at,
        }

    def _attempt_payload(
        self,
        database: Session,
        attempt: ActivityAttempt,
    ) -> dict[str, Any]:
        evaluations = database.scalars(
            select(ActivityEvaluation)
            .where(ActivityEvaluation.attempt_id == attempt.id)
            .order_by(ActivityEvaluation.created_at)
        ).all()
        invocations = database.scalars(
            select(RunnerInvocation)
            .where(RunnerInvocation.attempt_id == attempt.id)
            .order_by(RunnerInvocation.created_at)
        ).all()
        return {
            "id": attempt.id,
            "revision": attempt.revision,
            "submission": json.loads(attempt.submission_json),
            "corrects_attempt_id": attempt.corrects_attempt_id,
            "evaluations": [
                {
                    "id": evaluation.id,
                    "method": evaluation.method,
                    "result": evaluation.result,
                    "rubric_id": evaluation.rubric_id,
                    "detail": json.loads(evaluation.detail_json),
                    "created_at": evaluation.created_at,
                }
                for evaluation in evaluations
            ],
            "runner_invocations": [self._runner_invocation_payload(item) for item in invocations],
            "created_at": attempt.created_at,
        }

    def _runner_invocation_payload(self, item: RunnerInvocation) -> dict[str, Any]:
        result = json.loads(item.result_json) if item.result_json else None
        return {
            "id": item.id,
            "protocol_version": item.protocol_version,
            "task_id": item.task_id,
            "runtime_profile_id": item.runtime_profile_id,
            "runtime_profile_version": item.runtime_profile_version,
            "runtime_image": item.runtime_image,
            "artifact_sha256": item.artifact_sha256,
            "request_sha256": item.request_sha256,
            "status": item.status,
            "failure_code": item.failure_code,
            "result": result,
            "created_at": item.created_at,
            "started_at": item.started_at,
            "finished_at": item.finished_at,
        }

    def _snapshot_payload(self, snapshot: MasterySnapshot) -> dict[str, Any]:
        return {
            "dimension": snapshot.dimension,
            "evidence_level": snapshot.evidence_level,
            "review_flags": json.loads(snapshot.review_flags_json),
            "evidence_count": snapshot.evidence_count,
            "updated_at": snapshot.updated_at,
        }

    def _review_payload(self, review: ReviewTask, now: datetime) -> dict[str, Any]:
        return {
            "id": review.id,
            "activity_id": review.activity_id,
            "checkpoint_index": review.checkpoint_index,
            "attempt_number": review.attempt_number,
            "interval_days": review.interval_days,
            "due_at": review.due_at,
            "status": review.status,
            "overdue": bool(
                review.status in {"scheduled", "available"}
                and _aware_utc(review.due_at).date() < _aware_utc(now).date()
            ),
            "policy_id": review.policy_id,
            "policy_version": review.policy_version,
            "completed_at": review.completed_at,
        }

    def _event(
        self,
        database: Session,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        database.add(
            LearningEvent(
                run_id=run_id,
                event_type=event_type,
                payload_json=canonical_json(payload),
                occurred_at=occurred_at,
            )
        )
