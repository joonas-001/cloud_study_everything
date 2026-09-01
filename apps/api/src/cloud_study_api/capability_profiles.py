# ruff: noqa: RUF001

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.content_locking import canonical_json
from cloud_study_api.governance import SkillPackage
from cloud_study_api.models import (
    ActivityAttempt,
    ActivityEvaluation,
    LearningActivity,
    LearningIndependentReview,
    LearningRun,
    LearningRunLock,
    MasteryEvidence,
    ReviewTask,
    RunnerInvocation,
    utc_now,
)

EVIDENCE_VALID_DAYS = 90
EVIDENCE_RANK = {
    "none": 0,
    "limited": 1,
    "retained_limited": 1,
    "supported": 2,
    "verified": 3,
    "retained": 4,
}
EVIDENCE_LEVEL = {
    "limited": "limited",
    "retained_limited": "limited",
    "supported": "supported",
    "verified": "verified",
    "retained": "retained",
}
DIMENSIONS = (
    "understanding",
    "operation",
    "transfer",
    "artifact",
    "retention",
    "correction",
)
SHADOW_MODEL = {
    "id": "review-outcome-candidate",
    "version": "1.0.0",
    "code_version": "milestone-8e-v1",
    "input_schema_version": "1.0.0",
    "parameters": {
        "minimum_samples": 30,
        "minimum_passes": 5,
        "minimum_failures": 5,
        "minimum_checkpoint_positions": 4,
        "cold_start_prediction": "pass",
        "retry_prediction": "fail",
        "prior_failure_prediction": "fail",
        "prior_pass_prediction": "pass",
    },
}
SHADOW_MODEL_SHA256 = hashlib.sha256(canonical_json(SHADOW_MODEL).encode("utf-8")).hexdigest()


class CapabilityProfileError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def evaluate_review_shadow(samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate a frozen candidate without changing the authoritative review policy."""

    ordered = sorted(
        samples,
        key=lambda item: (
            str(item["run_id"]),
            int(item["checkpoint_index"]),
            int(item["attempt_number"]),
        ),
    )
    previous_by_run: dict[str, str] = {}
    predictions: list[tuple[bool, bool]] = []
    checkpoint_positions: set[int] = set()
    pass_count = 0
    failure_count = 0
    for item in ordered:
        outcome = str(item["result"])
        if outcome not in {"passed", "failed"}:
            continue
        run_id = str(item["run_id"])
        attempt_number = int(item["attempt_number"])
        prior = previous_by_run.get(run_id)
        if attempt_number > 1 or prior == "failed":
            predicted_pass = False
        elif prior == "passed":
            predicted_pass = True
        else:
            predicted_pass = True
        actual_pass = outcome == "passed"
        predictions.append((predicted_pass, actual_pass))
        checkpoint_positions.add(int(item["checkpoint_index"]))
        pass_count += int(actual_pass)
        failure_count += int(not actual_pass)
        previous_by_run[run_id] = outcome

    minimums = cast(dict[str, int], SHADOW_MODEL["parameters"])
    reasons: list[str] = []
    if len(predictions) < minimums["minimum_samples"]:
        reasons.append("minimum_samples_not_met")
    if pass_count < minimums["minimum_passes"]:
        reasons.append("minimum_passes_not_met")
    if failure_count < minimums["minimum_failures"]:
        reasons.append("minimum_failures_not_met")
    if len(checkpoint_positions) < minimums["minimum_checkpoint_positions"]:
        reasons.append("minimum_checkpoint_positions_not_met")

    result: dict[str, Any] = {
        "status": "insufficient_data" if reasons else "comparison_available",
        "model_id": SHADOW_MODEL["id"],
        "model_version": SHADOW_MODEL["version"],
        "model_sha256": SHADOW_MODEL_SHA256,
        "code_version": SHADOW_MODEL["code_version"],
        "input_schema_version": SHADOW_MODEL["input_schema_version"],
        "parameters": SHADOW_MODEL["parameters"],
        "sample_count": len(predictions),
        "pass_count": pass_count,
        "failure_count": failure_count,
        "checkpoint_position_count": len(checkpoint_positions),
        "insufficient_reason_codes": reasons,
        "predictions_exposed": False,
        "memory_probability_exposed": False,
        "affects_tasks": False,
        "affects_evidence": False,
        "affects_user_conclusions": False,
        "authoritative_policy": {
            "strategy": "fixed_expanding",
            "interval_days": [1, 2, 4, 7, 15],
            "unchanged": True,
        },
        "comparison": None,
    }
    if not reasons:
        correct = sum(predicted == actual for predicted, actual in predictions)
        result["comparison"] = {
            "metric": "binary_outcome_accuracy_basis_points",
            "candidate_value": round(correct * 10_000 / len(predictions)),
            "meaning": "仅用于离线候选比较，不是记忆概率、学习效率或掌握结论。",
        }
    return result


class CapabilityProfileService:
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

    def get_profile(self, run_id: str) -> dict[str, Any]:
        now = _aware_utc(self._now())
        with self._session_factory() as database:
            run = database.get(LearningRun, run_id)
            if run is None:
                raise CapabilityProfileError(404, "learning_run_not_found", "学习执行不存在。")
            package = self._packages.get((run.skill_id, run.skill_version))
            if package is None:
                raise CapabilityProfileError(
                    409,
                    "skill_package_unavailable",
                    "无法读取该历史执行对应的精确技能包。",
                )
            return self._build_profile(database, run, package, now)

    def export_profile(
        self,
        run_id: str,
        export_format: Literal["json", "csv"],
    ) -> tuple[bytes, str, str]:
        profile = self.get_profile(run_id)
        if export_format == "json":
            content = json.dumps(profile, ensure_ascii=False, indent=2, default=self._json_default)
            return content.encode("utf-8"), "application/json; charset=utf-8", "json"
        if export_format != "csv":
            raise CapabilityProfileError(422, "invalid_export_format", "只支持 JSON 或 CSV 导出。")
        output = io.StringIO(newline="")
        fields = [
            "skill_id",
            "skill_version",
            "run_id",
            "domain_id",
            "domain_title",
            "capability_id",
            "capability_title",
            "dimension",
            "evidence_level",
            "evidence_count",
            "review_flags",
            "attempt_count",
            "passed_count",
            "failed_count",
            "uncertain_count",
            "correction_count",
            "can_prove",
            "cannot_prove",
        ]
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for domain in profile["domains"]:
            for capability in domain["capabilities"]:
                for dimension in capability["dimensions"]:
                    writer.writerow(
                        {
                            "skill_id": profile["skill_id"],
                            "skill_version": profile["skill_version"],
                            "run_id": profile["run_id"],
                            "domain_id": domain["id"],
                            "domain_title": domain["title"],
                            "capability_id": capability["id"],
                            "capability_title": capability["title"],
                            "dimension": dimension["dimension"],
                            "evidence_level": dimension["evidence_level"],
                            "evidence_count": dimension["evidence_count"],
                            "review_flags": "|".join(dimension["review_flags"]),
                            "attempt_count": capability["analytics"]["attempt_count"],
                            "passed_count": capability["analytics"]["passed_count"],
                            "failed_count": capability["analytics"]["failed_count"],
                            "uncertain_count": capability["analytics"]["uncertain_count"],
                            "correction_count": capability["analytics"]["correction_count"],
                            "can_prove": capability["can_prove"],
                            "cannot_prove": "；".join(capability["cannot_prove"]),
                        }
                    )
        return output.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", "csv"

    def _build_profile(
        self,
        database: Session,
        run: LearningRun,
        package: SkillPackage,
        now: datetime,
    ) -> dict[str, Any]:
        activities = database.scalars(
            select(LearningActivity)
            .where(LearningActivity.run_id == run.id)
            .order_by(LearningActivity.sequence)
        ).all()
        definitions = {
            item.id: cast(dict[str, Any], json.loads(item.definition_json)) for item in activities
        }
        attempts = database.scalars(
            select(ActivityAttempt)
            .join(LearningActivity, LearningActivity.id == ActivityAttempt.activity_id)
            .where(LearningActivity.run_id == run.id)
            .order_by(ActivityAttempt.created_at, ActivityAttempt.revision)
        ).all()
        attempt_ids = [item.id for item in attempts]
        evaluations = (
            database.scalars(
                select(ActivityEvaluation)
                .where(ActivityEvaluation.attempt_id.in_(attempt_ids))
                .order_by(ActivityEvaluation.created_at, ActivityEvaluation.id)
            ).all()
            if attempt_ids
            else []
        )
        evidence = database.scalars(
            select(MasteryEvidence)
            .where(MasteryEvidence.run_id == run.id)
            .order_by(MasteryEvidence.created_at, MasteryEvidence.id)
        ).all()
        reviews = database.scalars(
            select(ReviewTask)
            .where(ReviewTask.run_id == run.id)
            .order_by(ReviewTask.checkpoint_index, ReviewTask.attempt_number)
        ).all()
        independent_reviews = database.scalars(
            select(LearningIndependentReview)
            .where(LearningIndependentReview.run_id == run.id)
            .order_by(LearningIndependentReview.reviewed_at)
        ).all()
        invocations = (
            database.scalars(
                select(RunnerInvocation)
                .where(RunnerInvocation.attempt_id.in_(attempt_ids))
                .order_by(RunnerInvocation.created_at)
            ).all()
            if attempt_ids
            else []
        )
        lock = database.get(LearningRunLock, run.id)
        graph = self._content_or_none(package, "capability_graph")
        source_review_pending = self._source_review_pending(package)
        domains, capabilities = self._scope_catalog(graph, definitions, evidence)
        evaluations_by_attempt: dict[str, list[ActivityEvaluation]] = defaultdict(list)
        for evaluation_item in evaluations:
            evaluations_by_attempt[evaluation_item.attempt_id].append(evaluation_item)
        attempts_by_activity: dict[str, list[ActivityAttempt]] = defaultdict(list)
        for attempt_item in attempts:
            attempts_by_activity[attempt_item.activity_id].append(attempt_item)
        evidence_by_capability: dict[str, list[MasteryEvidence]] = defaultdict(list)
        for evidence_item in evidence:
            for capability_id in json.loads(evidence_item.capability_ids_json):
                evidence_by_capability[capability_id].append(evidence_item)
        independent_by_capability: dict[str, list[LearningIndependentReview]] = defaultdict(list)
        for review_item in independent_reviews:
            for capability_id in json.loads(review_item.capability_ids_json):
                independent_by_capability[capability_id].append(review_item)
        invocations_by_attempt: dict[str, list[RunnerInvocation]] = defaultdict(list)
        for invocation_item in invocations:
            invocations_by_attempt[invocation_item.attempt_id].append(invocation_item)

        capability_payloads: dict[str, dict[str, Any]] = {}
        for capability in capabilities:
            capability_id = capability["id"]
            related_activity_ids = [
                activity.id
                for activity in activities
                if capability_id in definitions[activity.id].get("capability_ids", [])
            ]
            related_attempts = [
                attempt
                for activity_id in related_activity_ids
                for attempt in attempts_by_activity[activity_id]
            ]
            related_evidence = evidence_by_capability[capability_id]
            capability_payloads[capability_id] = {
                "id": capability_id,
                "title": capability["title"],
                "domain_id": capability["domain_id"],
                "dimensions": self._dimension_payloads(
                    related_evidence,
                    reviews,
                    definitions,
                    capability_id,
                    source_review_pending,
                    lock is None,
                    now,
                ),
                "analytics": self._analytics(
                    related_attempts,
                    evaluations_by_attempt,
                    reviews,
                    definitions,
                    capability_id,
                    now,
                ),
                "evidence": [
                    self._evidence_payload(item, invocations_by_attempt[item.attempt_id], now)
                    for item in related_evidence
                ],
                "independent_reviews": [
                    self._independent_review_payload(item, now)
                    for item in independent_by_capability[capability_id]
                ],
                "can_prove": self._can_prove(related_evidence, now),
                "cannot_prove": [
                    "不能外推为所属领域、共同主干或整门算法掌握。",
                    "流程完成、页面停留、点击或自评不能替代确定性与独立证据。",
                ],
            }

        shadow = self._shadow_evaluation(database, run.skill_id, run.skill_version, now)
        scheduled_minutes = sum(item.estimated_minutes for item in activities)
        completed_estimated_minutes = sum(
            item.estimated_minutes for item in activities if item.status == "completed"
        )
        evidenced_capabilities = sum(
            bool(evidence_by_capability[item["id"]]) for item in capabilities
        )
        return {
            "schema_version": "1.0.0",
            "run_id": run.id,
            "skill_id": run.skill_id,
            "skill_version": run.skill_version,
            "skill_title": package.manifest["title"],
            "run_status": run.status,
            "is_preview": run.is_preview,
            "generated_at": now,
            "lock_sha256": lock.lock_sha256 if lock else "",
            "scope_status": "scoped" if graph is not None else "legacy_unscoped",
            "summary": {
                "capability_count": len(capabilities),
                "evidenced_capability_count": evidenced_capabilities,
                "attempt_count": len(attempts),
                "active_evidence_count": sum(item.superseded_at is None for item in evidence),
                "independent_review_count": len(independent_reviews),
            },
            "plan_alignment": {
                "scheduled_estimated_minutes": scheduled_minutes,
                "completed_estimated_minutes": completed_estimated_minutes,
                "unfinished_estimated_minutes": scheduled_minutes - completed_estimated_minutes,
                "completed_activity_count": sum(item.status == "completed" for item in activities),
                "scheduled_activity_count": len(activities),
                "actual_minutes_available": False,
                "meaning": "只比较计划估算与已完成任务的估算分钟，不用停留时长推断掌握或惩罚延期。",
            },
            "domains": [
                {
                    "id": domain["id"],
                    "title": domain["title"],
                    "capabilities": [
                        capability_payloads[item["id"]]
                        for item in capabilities
                        if item["domain_id"] == domain["id"]
                    ],
                }
                for domain in domains
            ],
            "shadow_evaluation": shadow,
            "privacy": {
                "local_only": True,
                "public_link_created": False,
                "certificate_created": False,
                "sensitive_submission_content_included": False,
                "credentials_included": False,
                "income_included": False,
            },
            "limitations": [
                "档案按单次执行和精确技能包版本生成，不跨版本静默合并。",
                "档案不生成证书、公开链接、智力评分、学习效率排名或成功概率。",
                "收入、求职结果和外部动作不用于反推掌握。",
                "候选复习影子评估不改变固定 1、2、4、7、15 天任务、证据或用户结论。",
            ],
        }

    def _dimension_payloads(
        self,
        evidence: Sequence[MasteryEvidence],
        reviews: Sequence[ReviewTask],
        definitions: dict[str, dict[str, Any]],
        capability_id: str,
        source_review_pending: bool,
        version_lock_missing: bool,
        now: datetime,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for dimension in DIMENSIONS:
            current = [
                item
                for item in evidence
                if item.dimension == dimension and item.superseded_at is None
            ]
            valid = [
                item
                for item in current
                if _aware_utc(item.created_at) + timedelta(days=EVIDENCE_VALID_DAYS) >= now
            ]
            strongest = max(valid, key=lambda item: EVIDENCE_RANK[item.strength], default=None)
            flags = {flag for item in current for flag in json.loads(item.review_flags_json)}
            relevant_review = any(
                review.status in {"scheduled", "available"}
                and review.activity_id is not None
                and review.activity_id in definitions
                and capability_id in definitions[review.activity_id].get("capability_ids", [])
                for review in reviews
            )
            if dimension == "retention" and relevant_review:
                flags.add("retention_due")
            if source_review_pending:
                flags.add("source_review_pending")
            if version_lock_missing:
                flags.add("version_mismatch")
            result.append(
                {
                    "dimension": dimension,
                    "evidence_level": (
                        EVIDENCE_LEVEL[strongest.strength] if strongest is not None else "none"
                    ),
                    "evidence_count": len(current),
                    "review_flags": sorted(flags),
                    "latest_at": max((item.created_at for item in current), default=None),
                    "expired_count": sum(
                        _aware_utc(item.created_at) + timedelta(days=EVIDENCE_VALID_DAYS) < now
                        for item in current
                    ),
                }
            )
        return result

    def _analytics(
        self,
        attempts: list[ActivityAttempt],
        evaluations_by_attempt: dict[str, list[ActivityEvaluation]],
        reviews: Sequence[ReviewTask],
        definitions: dict[str, dict[str, Any]],
        capability_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        outcomes = {"passed": 0, "failed": 0, "uncertain": 0}
        deterministic_passes: list[datetime] = []
        correction_seconds: list[int] = []
        attempts_by_id = {item.id: item for item in attempts}
        for attempt in attempts:
            evaluations = evaluations_by_attempt[attempt.id]
            final = evaluations[-1] if evaluations else None
            if final is not None and final.result in outcomes:
                outcomes[final.result] += 1
            for evaluation in evaluations:
                if (
                    evaluation.method in {"deterministic", "runner"}
                    and evaluation.result == "passed"
                ):
                    deterministic_passes.append(evaluation.created_at)
            if attempt.corrects_attempt_id and final is not None and final.result == "passed":
                original = attempts_by_id.get(attempt.corrects_attempt_id)
                if original is not None:
                    correction_seconds.append(
                        max(
                            0,
                            round(
                                (
                                    _aware_utc(attempt.created_at) - _aware_utc(original.created_at)
                                ).total_seconds()
                            ),
                        )
                    )
        scoped_reviews = [
            item
            for item in reviews
            if item.activity_id is not None
            and capability_id in definitions.get(item.activity_id, {}).get("capability_ids", [])
        ]
        return {
            "attempt_count": len(attempts),
            "passed_count": outcomes["passed"],
            "failed_count": outcomes["failed"],
            "uncertain_count": outcomes["uncertain"],
            "correction_count": sum(item.corrects_attempt_id is not None for item in attempts),
            "first_attempt_at": min((item.created_at for item in attempts), default=None),
            "first_deterministic_pass_at": min(deterministic_passes, default=None),
            "fastest_correction_seconds": min(correction_seconds, default=None),
            "review_due_count": sum(
                item.status in {"scheduled", "available"} for item in scoped_reviews
            ),
            "review_overdue_count": sum(
                item.status in {"scheduled", "available"} and _aware_utc(item.due_at) < now
                for item in scoped_reviews
            ),
            "review_passed_count": sum(item.status == "passed" for item in scoped_reviews),
            "review_failed_count": sum(item.status == "failed" for item in scoped_reviews),
        }

    def _evidence_payload(
        self,
        evidence: MasteryEvidence,
        invocations: list[RunnerInvocation],
        now: datetime,
    ) -> dict[str, Any]:
        invocation = invocations[-1] if invocations else None
        runner = None
        if invocation is not None:
            result = json.loads(invocation.result_json) if invocation.result_json else {}
            tests = result.get("tests", []) if isinstance(result, dict) else []
            runtime = result.get("runtime", {}) if isinstance(result, dict) else {}
            runner = {
                "protocol_version": invocation.protocol_version,
                "task_id": invocation.task_id,
                "runtime_profile_id": invocation.runtime_profile_id,
                "runtime_profile_version": invocation.runtime_profile_version,
                "runtime_image": invocation.runtime_image,
                "observed_image_id": runtime.get("observed_image_id"),
                "artifact_sha256": invocation.artifact_sha256,
                "status": invocation.status,
                "tests": [
                    {
                        "id": item.get("id"),
                        "status": item.get("status"),
                        "exit_code": item.get("exit_code"),
                        "output_truncated": item.get("output_truncated"),
                    }
                    for item in tests
                    if isinstance(item, dict)
                ],
            }
        expires_at = _aware_utc(evidence.created_at) + timedelta(days=EVIDENCE_VALID_DAYS)
        return {
            "id": evidence.id,
            "activity_id": evidence.activity_id,
            "attempt_id": evidence.attempt_id,
            "criterion_id": evidence.criterion_id,
            "dimension": evidence.dimension,
            "method": evidence.method,
            "result": evidence.result,
            "strength": evidence.strength,
            "language": evidence.language,
            "review_flags": json.loads(evidence.review_flags_json),
            "created_at": evidence.created_at,
            "expires_at": expires_at,
            "expired": expires_at < now,
            "superseded_at": evidence.superseded_at,
            "runner": runner,
        }

    @staticmethod
    def _independent_review_payload(
        review: LearningIndependentReview,
        now: datetime,
    ) -> dict[str, Any]:
        return {
            "id": review.id,
            "dimension": review.dimension,
            "reviewer_relationship": review.reviewer_relationship,
            "rubric_id": review.rubric_id,
            "rubric_version": review.rubric_version,
            "conclusion": review.conclusion,
            "reviewed_at": review.reviewed_at,
            "expires_at": review.expires_at,
            "expired": _aware_utc(review.expires_at) < now,
            "attachments_stored": False,
        }

    def _shadow_evaluation(
        self,
        database: Session,
        skill_id: str,
        skill_version: str,
        now: datetime,
    ) -> dict[str, Any]:
        rows = database.execute(
            select(ReviewTask, LearningRun)
            .join(LearningRun, LearningRun.id == ReviewTask.run_id)
            .where(
                LearningRun.skill_id == skill_id,
                LearningRun.skill_version == skill_version,
                ReviewTask.status.in_(["passed", "failed"]),
            )
            .order_by(
                ReviewTask.run_id,
                ReviewTask.checkpoint_index,
                ReviewTask.attempt_number,
            )
        ).all()
        samples = [
            {
                "run_id": review.run_id,
                "checkpoint_index": review.checkpoint_index,
                "attempt_number": review.attempt_number,
                "interval_days": review.interval_days,
                "result": review.status,
            }
            for review, _run in rows
            if review.completed_at is not None and _aware_utc(review.completed_at) <= now
        ]
        return evaluate_review_shadow(samples)

    @staticmethod
    def _scope_catalog(
        graph: dict[str, Any] | None,
        definitions: dict[str, dict[str, Any]],
        evidence: Sequence[MasteryEvidence],
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        if graph is not None:
            return (
                [{"id": str(item["id"]), "title": str(item["title"])} for item in graph["domains"]],
                [
                    {
                        "id": str(item["id"]),
                        "title": str(item["title"]),
                        "domain_id": str(item["domain_id"]),
                    }
                    for item in graph["capabilities"]
                ],
            )
        capability_ids = {
            capability_id
            for definition in definitions.values()
            for capability_id in definition.get("capability_ids", [])
        }
        capability_ids.update(
            capability_id
            for item in evidence
            for capability_id in json.loads(item.capability_ids_json)
        )
        return (
            [{"id": "legacy", "title": "历史未范围化记录"}],
            [{"id": item, "title": item, "domain_id": "legacy"} for item in sorted(capability_ids)],
        )

    @staticmethod
    def _can_prove(evidence: list[MasteryEvidence], now: datetime) -> str:
        current = [item for item in evidence if item.superseded_at is None]
        active = [
            item
            for item in current
            if _aware_utc(item.created_at) + timedelta(days=EVIDENCE_VALID_DAYS) >= now
        ]
        if not active:
            if current:
                return "该范围只有已过期证据，不能作为当前能力结论。"
            return "当前没有该精确能力范围的有效结构化证据。"
        strongest = max(active, key=lambda item: EVIDENCE_RANK[item.strength])
        messages = {
            "limited": "仅证明本次有限提交已达到继续流程的结构要求。",
            "retained_limited": "仅证明延迟后的有限提交，不等于确定性正确。",
            "supported": "仅证明受管确定性规则覆盖的题目与能力范围。",
            "verified": "仅证明锁定 Runner、运行时和测试覆盖的操作范围。",
            "retained": "仅证明同一精确范围在延迟复测时仍通过。",
        }
        return messages[strongest.strength]

    def _content_or_none(
        self,
        package: SkillPackage,
        kind: str,
    ) -> dict[str, Any] | None:
        entries = [item for item in package.manifest["content_files"] if item["kind"] == kind]
        if len(entries) != 1:
            return None
        value = yaml.safe_load((package.path / entries[0]["path"]).read_text(encoding="utf-8"))
        return cast(dict[str, Any], value) if isinstance(value, dict) else None

    def _source_review_pending(self, package: SkillPackage) -> bool:
        catalog = self._content_or_none(package, "source_catalog")
        return bool(
            catalog
            and any(
                "未进行远程实质内容复核" in str(item.get("access_note", ""))
                for item in catalog.get("sources", [])
            )
        )

    @staticmethod
    def _json_default(value: object) -> str:
        if isinstance(value, datetime):
            return _aware_utc(value).isoformat().replace("+00:00", "Z")
        raise TypeError(f"unsupported JSON value: {type(value)!r}")
