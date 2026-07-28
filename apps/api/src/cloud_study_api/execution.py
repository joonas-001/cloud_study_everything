# ruff: noqa: RUF001

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml
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
    LearningRun,
    LearningRunLock,
    LearningUnitInstance,
    MasteryEvidence,
    MasterySnapshot,
    PlanningProposal,
    PlanningUnit,
    ReviewTask,
    SourceChangeCandidate,
    utc_now,
)

ENGINE_PROTOCOL_VERSION = "0.2.0"
RUNNER_PROTOCOL_VERSION = "1.0.0"
MASTERY_DIMENSIONS = (
    "understanding",
    "operation",
    "transfer",
    "artifact",
    "retention",
    "correction",
)
EVIDENCE_RANK = {"limited": 1, "supported": 2, "retained_limited": 1}


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
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository_root = repository_root
        self._package_list = packages
        self._packages = {(package.package_id, package.version): package for package in packages}
        self._session_factory = session_factory
        self._now = now
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
        if code_execution:
            raise LearningExecutionError(
                409,
                "code_execution_disabled",
                "Code execution is disabled in milestone 4A.",
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
                    LearningRun.status.in_(["active", "retention_pending"]),
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
                "capabilities": {
                    "code_execution": "disabled",
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
                    "code_execution": "disabled",
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
                    LearningRun.status.in_(["active", "retention_pending"]),
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

    def today(self, run_id: str, available_minutes: int) -> dict[str, Any]:
        if not 15 <= available_minutes <= 480:
            raise LearningExecutionError(
                422,
                "invalid_available_minutes",
                "Available minutes must be between 15 and 480.",
            )
        now = self._now()
        with self._session_factory() as database:
            run = self._run(database, run_id)
            if run.status in {"completed", "ended"}:
                return {
                    "run_id": run.id,
                    "generated_at": now,
                    "available_minutes": available_minutes,
                    "estimated_minutes": 0,
                    "tasks": [],
                    "reason": "学习执行已进入终态，没有可继续的今日任务。",
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
                key=lambda item: (
                    0
                    if item.activity_type == "review"
                    else 1
                    if item.activity_type == "correction"
                    else 2,
                    item.sequence,
                ),
            )
            selected: list[LearningActivity] = []
            used = 0
            for activity in ordered:
                if selected and used + activity.estimated_minutes > available_minutes:
                    continue
                selected.append(activity)
                used += activity.estimated_minutes
            self._event(
                database,
                run.id,
                "today_queue_generated",
                {
                    "available_minutes": available_minutes,
                    "activity_ids": [activity.id for activity in selected],
                    "estimated_minutes": used,
                },
                now,
            )
            database.commit()
            return {
                "run_id": run.id,
                "generated_at": now,
                "available_minutes": available_minutes,
                "estimated_minutes": used,
                "tasks": [self._activity_payload(database, activity, now) for activity in selected],
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
            self._create_evidence(
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
            if activity.activity_type == "review" and review_task is not None:
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
            return {
                "attempt": self._attempt_payload(database, attempt),
                "activity": self._activity_payload(database, activity, now),
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
            package = self._package(run.skill_id, run.skill_version)
            rubric = self._content(package, "rubric_definition")
            known_rubrics = {criterion["id"] for criterion in rubric["criteria"]}
            if rubric_id not in known_rubrics:
                raise LearningExecutionError(
                    422,
                    "rubric_not_found",
                    "The selected rubric is not part of the locked package.",
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
            self._create_evidence(
                database,
                run,
                activity,
                attempt,
                evaluation,
                now,
            )
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
                },
                now,
            )
            database.commit()
            return {
                "attempt": self._attempt_payload(database, attempt),
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
                "limitations": [
                    "4A 不产生 scope_criteria_met、verified 或不受限 retained。",
                    "代码文本未执行，用户自评不是独立人工审核。",
                ],
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
                        "review_flags": json.loads(item.review_flags_json),
                        "created_at": item.created_at,
                        "superseded_at": item.superseded_at,
                    }
                    for item in evidence
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

    def end_run(self, run_id: str) -> dict[str, Any]:
        now = self._now()
        with self._session_factory() as database:
            run = self._run(database, run_id)
            if run.status not in {"active", "retention_pending"}:
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
                    definition_json=canonical_json(definition),
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
    ) -> None:
        package = self._package(run.skill_id, run.skill_version)
        assessment = self._content(package, "assessment_definition")
        template_id = activity.template_activity_id.split(":", maxsplit=1)[0]
        criteria = [
            criterion
            for criterion in assessment["criteria"]
            if criterion["activity_id"] == template_id
        ]
        for criterion in criteria:
            if evaluation.result in {"failed", "uncertain"}:
                continue
            method = evaluation.method
            strength = criterion["evidence_strength"]
            flags = set(criterion["review_flags"])
            if method == "self_review":
                strength = "limited"
                flags.add("manual_review_pending")
            if method in {"review_pending", "not_executable"}:
                strength = "limited"
                flags.add("manual_review_pending")
            if (
                criterion["dimension"] == "correction"
                and activity.template_activity_id != "checkpoint-correction"
            ):
                strength = "limited"
            database.add(
                MasteryEvidence(
                    id=str(uuid4()),
                    run_id=run.id,
                    activity_id=activity.id,
                    attempt_id=attempt.id,
                    evaluation_id=evaluation.id,
                    criterion_id=criterion["id"],
                    dimension=criterion["dimension"],
                    method=method,
                    result=evaluation.result,
                    strength=strength,
                    review_flags_json=canonical_json(sorted(flags)),
                    rubric_version="1.0.0",
                    created_at=now,
                )
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
            activity
            for activity in learning["activities"]
            if activity["id"] == "retention-review-template"
        )
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
        activity = LearningActivity(
            id=str(uuid4()),
            run_id=run.id,
            unit_instance_id=cast(LearningUnitInstance, unit).id,
            template_activity_id=f"retention-review-template:{checkpoint_index}:{attempt_number}",
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
            activity = database.get(LearningActivity, review.activity_id)
            if activity is not None and activity.status == "pending":
                activity.status = "available"
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
                level = "supported" if strongest.strength == "supported" else "limited"
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
            "code_execution": "disabled",
            "external_ai": "disabled",
            "selected_historical_plan": run.selected_historical_plan,
            "reused_from_run_id": run.reused_from_run_id,
            "lock_sha256": content_lock.lock_sha256 if content_lock else "",
            "engine_protocol_version": ENGINE_PROTOCOL_VERSION,
            "runner_protocol_version": RUNNER_PROTOCOL_VERSION,
            "evidence_limitations": [
                "4A 不产生整体掌握结论。",
                "代码文本未执行，操作和作品证据受限。",
                "自评不是独立人工审核。",
            ],
            "activities": [
                self._activity_payload(database, activity, self._now()) for activity in activities
            ],
            "dimensions": [self._snapshot_payload(snapshot) for snapshot in snapshots],
            "reviews": [self._review_payload(review, self._now()) for review in reviews],
            "next_actions": next_actions,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "retention_started_at": run.retention_started_at,
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
            "available_at": activity.available_at,
            "overdue": bool(
                activity.available_at
                and activity.status in {"available", "correction_required"}
                and _aware_utc(activity.available_at).date() < _aware_utc(now).date()
            ),
            "attempts": [self._attempt_payload(database, attempt) for attempt in attempts],
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
            "created_at": attempt.created_at,
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
