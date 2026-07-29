from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.governance import SkillPackage
from cloud_study_api.models import (
    LearningRun,
    MarketEvidenceSnapshot,
    MasterySnapshot,
    PathComparison,
    PathComparisonDecision,
    ReadinessEvaluation,
    ReadinessEvent,
    ReadinessPolicySnapshot,
    UserGoalSelection,
    utc_now,
)

MONETIZATION_GOALS = {"employment", "freelancing", "productization"}
GOAL_KINDS = {
    "learning",
    "exam",
    "employment",
    "freelancing",
    "productization",
    "other",
}


class ReadinessError(RuntimeError):
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
    if isinstance(value, datetime):
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


class ReadinessService:
    def __init__(
        self,
        repository_root: Path,
        packages: list[SkillPackage],
        session_factory: sessionmaker[Session],
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository_root = repository_root
        self._packages = {(package.package_id, package.version): package for package in packages}
        self._session_factory = session_factory
        self._now = now
        self._policy = self._load_json(
            repository_root / "readiness" / "policies" / "local-comparison-v1.json"
        )
        self._fixtures = [
            self._load_json(path)
            for path in sorted((repository_root / "readiness" / "fixtures").glob("*.json"))
        ]

    def list_scopes(self) -> list[dict[str, Any]]:
        with self._session_factory() as database:
            runs = database.scalars(
                select(LearningRun).order_by(LearningRun.created_at.desc())
            ).all()
            return [self._scope_payload(run) for run in runs]

    def select_goal(
        self,
        *,
        skill_id: str,
        skill_version: str,
        capability_scope_id: str,
        goal_kind: str,
        custom_label: str | None,
    ) -> dict[str, Any]:
        if goal_kind not in GOAL_KINDS:
            raise ReadinessError(422, "invalid_goal_kind", "不支持的目标类型。")
        if goal_kind == "other" and not custom_label:
            raise ReadinessError(
                422,
                "custom_goal_label_required",
                "选择其他目标时需要填写目标说明。",
            )
        if goal_kind != "other" and custom_label:
            raise ReadinessError(
                422,
                "custom_goal_label_not_allowed",
                "只有其他目标可以填写自定义说明。",
            )
        scope = self._scope_definition(skill_id, skill_version)
        if scope["id"] != capability_scope_id:
            raise ReadinessError(
                422,
                "capability_scope_mismatch",
                "能力范围不属于所选技能包版本。",
                {
                    "expected_scope_id": scope["id"],
                    "provided_scope_id": capability_scope_id,
                },
            )

        now = self._now()
        with self._session_factory() as database:
            active = database.scalar(
                select(UserGoalSelection).where(
                    UserGoalSelection.skill_id == skill_id,
                    UserGoalSelection.skill_version == skill_version,
                    UserGoalSelection.capability_scope_id == capability_scope_id,
                    UserGoalSelection.superseded_at.is_(None),
                )
            )
            if active is not None:
                active.superseded_at = now
            goal = UserGoalSelection(
                id=str(uuid4()),
                skill_id=skill_id,
                skill_version=skill_version,
                capability_scope_id=capability_scope_id,
                goal_kind=goal_kind,
                custom_label=custom_label,
                created_at=now,
                superseded_at=None,
            )
            database.add(goal)
            self._event(
                database,
                "goal_selected",
                {"goal_kind": goal_kind, "capability_scope_id": capability_scope_id},
                now,
                goal_selection_id=goal.id,
            )
            database.commit()
            return self._goal_payload(goal)

    def get_current_goal(
        self,
        skill_id: str,
        skill_version: str,
        capability_scope_id: str,
    ) -> dict[str, Any] | None:
        with self._session_factory() as database:
            goal = database.scalar(
                select(UserGoalSelection).where(
                    UserGoalSelection.skill_id == skill_id,
                    UserGoalSelection.skill_version == skill_version,
                    UserGoalSelection.capability_scope_id == capability_scope_id,
                    UserGoalSelection.superseded_at.is_(None),
                )
            )
            return None if goal is None else self._goal_payload(goal)

    def list_market_snapshots(self) -> list[dict[str, Any]]:
        with self._session_factory() as database:
            snapshots = self._ensure_market_snapshots(database)
            database.commit()
            return [self._market_snapshot_payload(snapshot) for snapshot in snapshots]

    def evaluate(
        self,
        *,
        goal_selection_id: str,
        learning_run_id: str | None,
        market_snapshot_id: str | None,
    ) -> dict[str, Any]:
        now = self._now()
        with self._session_factory() as database:
            goal = database.get(UserGoalSelection, goal_selection_id)
            if goal is None or goal.superseded_at is not None:
                raise ReadinessError(404, "active_goal_not_found", "当前目标不存在。")

            policy = self._ensure_policy_snapshot(database)
            evidence = self._evidence_snapshot(database, goal, learning_run_id)
            market = None
            status = "not_ready"
            reasons: list[str] = []

            if goal.goal_kind not in MONETIZATION_GOALS:
                status = "not_applicable"
                reasons = ["goal_not_monetization"]
                market_snapshot_id = None
            else:
                if market_snapshot_id is None:
                    raise ReadinessError(
                        422,
                        "market_snapshot_required",
                        "变现相关目标必须明确选择一个合成市场快照。",
                    )
                market = database.get(MarketEvidenceSnapshot, market_snapshot_id)
                if market is None:
                    self._ensure_market_snapshots(database)
                    market = database.get(MarketEvidenceSnapshot, market_snapshot_id)
                if market is None or not market.synthetic:
                    raise ReadinessError(
                        404,
                        "synthetic_market_snapshot_not_found",
                        "合成市场快照不存在。",
                    )

                if evidence["learning_run_id"] is None:
                    reasons.append("learning_run_missing")
                missing = [
                    item["dimension"]
                    for item in evidence["dimensions"]
                    if item["evidence_count"] == 0
                ]
                if missing:
                    reasons.extend(
                        f"evidence_dimension_missing:{dimension}" for dimension in missing
                    )
                if reasons:
                    status = "not_ready"
                else:
                    blocking_flags = sorted(
                        {
                            flag
                            for item in evidence["dimensions"]
                            for flag in item["review_flags"]
                            if flag in self._policy["blocking_review_flags"]
                        }
                    )
                    if blocking_flags:
                        status = "review_required"
                        reasons.extend(f"review_flag_blocking:{flag}" for flag in blocking_flags)
                    elif market.freshness_status != "current":
                        status = "review_required"
                        reasons.append(f"market_snapshot_{market.freshness_status}")
                    else:
                        status = "comparison_ready"
                        reasons.extend(["comparison_allowed", "experiment_threshold_unconfirmed"])

            limitations = list(self._policy["limitations"])
            if market is not None:
                limitations.extend(json.loads(market.payload_json)["limitations"])
            inputs = {
                "goal": self._goal_payload(goal),
                "learning_run_id": evidence["learning_run_id"],
                "policy_sha256": policy.payload_sha256,
                "market_snapshot_sha256": (market.payload_sha256 if market is not None else None),
                "evidence": evidence,
                "status": status,
                "reasons": reasons,
            }
            evaluation = ReadinessEvaluation(
                id=str(uuid4()),
                goal_selection_id=goal.id,
                learning_run_id=evidence["learning_run_id"],
                policy_snapshot_id=policy.id,
                market_snapshot_id=market.id if market is not None else None,
                status=status,
                reason_codes_json=_canonical_json(reasons),
                evidence_snapshot_json=_canonical_json(evidence),
                limitations_json=_canonical_json(limitations),
                input_sha256=_sha256(inputs),
                created_at=now,
            )
            database.add(evaluation)
            self._event(
                database,
                "readiness_evaluated",
                {"status": status, "reason_codes": reasons},
                now,
                goal_selection_id=goal.id,
                evaluation_id=evaluation.id,
            )
            database.commit()
            return self._evaluation_payload(database, evaluation)

    def create_comparison(self, evaluation_id: str) -> dict[str, Any]:
        now = self._now()
        with self._session_factory() as database:
            evaluation = database.get(ReadinessEvaluation, evaluation_id)
            if evaluation is None:
                raise ReadinessError(404, "evaluation_not_found", "准备度评估不存在。")
            if evaluation.status != "comparison_ready":
                raise ReadinessError(
                    409,
                    "comparison_not_allowed",
                    "当前准备度状态不允许生成路径比较。",
                    {"status": evaluation.status},
                )
            existing = database.scalar(
                select(PathComparison).where(PathComparison.evaluation_id == evaluation.id)
            )
            if existing is not None:
                return self._comparison_payload(database, existing)
            if evaluation.market_snapshot_id is None:
                raise ReadinessError(
                    409,
                    "market_snapshot_missing",
                    "评估没有锁定合成市场快照。",
                )
            market = database.get(MarketEvidenceSnapshot, evaluation.market_snapshot_id)
            goal = database.get(UserGoalSelection, evaluation.goal_selection_id)
            if market is None or goal is None:
                raise ReadinessError(
                    409,
                    "comparison_inputs_missing",
                    "比较所需的不可变输入缺失。",
                )

            market_payload = json.loads(market.payload_json)
            evidence = json.loads(evaluation.evidence_snapshot_json)
            gaps = [
                item["dimension"]
                for item in evidence["dimensions"]
                if item["evidence_level"] != "supported"
            ]
            paths = [
                {
                    "path": item["path"],
                    "selected_goal": item["path"] == goal.goal_kind,
                    "evidence_gaps": [
                        *gaps,
                        "verified_operation_unavailable",
                        "independent_artifact_review_unavailable",
                    ],
                    "factors": item["factors"],
                    "source_ids": item["source_ids"],
                    "uncertainties": item["uncertainties"],
                }
                for item in market_payload["paths"]
            ]
            payload = {
                "schema_version": "1.0.0",
                "id": "",
                "evaluation_id": evaluation.id,
                "market_snapshot_id": market.id,
                "synthetic": True,
                "paths": paths,
                "limitations": [
                    *json.loads(evaluation.limitations_json),
                    "比较不保证工作、订单、需求或收入。",
                    "5A 不创建真实实验。系统也不进行任何对外动作。",
                ],
                "created_at": now.isoformat(),
            }
            comparison = PathComparison(
                id=str(uuid4()),
                evaluation_id=evaluation.id,
                market_snapshot_id=market.id,
                synthetic=True,
                comparison_json="",
                payload_sha256="",
                created_at=now,
            )
            payload["id"] = comparison.id
            comparison.comparison_json = _canonical_json(payload)
            comparison.payload_sha256 = _sha256(payload)
            database.add(comparison)
            self._event(
                database,
                "path_comparison_created",
                {"synthetic": True, "market_snapshot_id": market.id},
                now,
                goal_selection_id=goal.id,
                evaluation_id=evaluation.id,
                comparison_id=comparison.id,
            )
            database.commit()
            return self._comparison_payload(database, comparison)

    def decide_comparison(
        self,
        comparison_id: str,
        *,
        decision: str,
        reason: str | None,
    ) -> dict[str, Any]:
        if decision not in {"accepted", "rejected", "deferred"}:
            raise ReadinessError(422, "invalid_decision", "不支持的比较决定。")
        now = self._now()
        with self._session_factory() as database:
            comparison = database.get(PathComparison, comparison_id)
            if comparison is None:
                raise ReadinessError(404, "comparison_not_found", "路径比较不存在。")
            revision = (
                database.scalar(
                    select(func.max(PathComparisonDecision.revision)).where(
                        PathComparisonDecision.comparison_id == comparison.id
                    )
                )
                or 0
            ) + 1
            item = PathComparisonDecision(
                id=str(uuid4()),
                comparison_id=comparison.id,
                revision=revision,
                decision=decision,
                reason=reason,
                created_at=now,
            )
            database.add(item)
            evaluation = database.get(ReadinessEvaluation, comparison.evaluation_id)
            self._event(
                database,
                "path_comparison_decided",
                {"decision": decision, "revision": revision, "reason": reason},
                now,
                goal_selection_id=(
                    evaluation.goal_selection_id if evaluation is not None else None
                ),
                evaluation_id=comparison.evaluation_id,
                comparison_id=comparison.id,
            )
            database.commit()
            return self._decision_payload(item)

    def get_history(self, goal_selection_id: str) -> dict[str, Any]:
        with self._session_factory() as database:
            goal = database.get(UserGoalSelection, goal_selection_id)
            if goal is None:
                raise ReadinessError(404, "goal_not_found", "目标记录不存在。")
            evaluations = database.scalars(
                select(ReadinessEvaluation)
                .where(ReadinessEvaluation.goal_selection_id == goal.id)
                .order_by(ReadinessEvaluation.created_at)
            ).all()
            comparisons = database.scalars(
                select(PathComparison)
                .join(
                    ReadinessEvaluation,
                    ReadinessEvaluation.id == PathComparison.evaluation_id,
                )
                .where(ReadinessEvaluation.goal_selection_id == goal.id)
                .order_by(PathComparison.created_at)
            ).all()
            events = database.scalars(
                select(ReadinessEvent)
                .where(ReadinessEvent.goal_selection_id == goal.id)
                .order_by(ReadinessEvent.occurred_at, ReadinessEvent.id)
            ).all()
            return {
                "goal": self._goal_payload(goal),
                "evaluations": [self._evaluation_payload(database, item) for item in evaluations],
                "comparisons": [self._comparison_payload(database, item) for item in comparisons],
                "events": [
                    {
                        "id": event.id,
                        "event_type": event.event_type,
                        "payload": json.loads(event.payload_json),
                        "occurred_at": event.occurred_at,
                    }
                    for event in events
                ],
            }

    def _scope_payload(self, run: LearningRun) -> dict[str, Any]:
        scope = self._scope_definition(run.skill_id, run.skill_version)
        return {
            "learning_run_id": run.id,
            "learning_run_status": run.status,
            "skill_id": run.skill_id,
            "skill_version": run.skill_version,
            "capability_scope_id": scope["id"],
            "scope_statement": scope["scope_statement"],
            "dimensions": scope["dimensions"],
            "created_at": run.created_at,
        }

    def _scope_definition(self, skill_id: str, skill_version: str) -> dict[str, Any]:
        package = self._packages.get((skill_id, skill_version))
        if package is None:
            raise ReadinessError(
                404,
                "skill_package_not_found",
                "技能包版本不存在。",
                {"skill_id": skill_id, "skill_version": skill_version},
            )
        content = next(
            (item for item in package.manifest["content_files"] if item["kind"] == "mastery_scope"),
            None,
        )
        if content is None:
            raise ReadinessError(
                409,
                "mastery_scope_missing",
                "技能包没有受管能力范围。",
            )
        value = yaml.safe_load((package.path / content["path"]).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ReadinessError(
                409,
                "mastery_scope_invalid",
                "受管能力范围格式无效。",
            )
        return value

    def _evidence_snapshot(
        self,
        database: Session,
        goal: UserGoalSelection,
        learning_run_id: str | None,
    ) -> dict[str, Any]:
        required = list(self._policy["required_dimensions"])
        if learning_run_id is None:
            return {
                "learning_run_id": None,
                "skill_id": goal.skill_id,
                "skill_version": goal.skill_version,
                "capability_scope_id": goal.capability_scope_id,
                "dimensions": [
                    {
                        "dimension": dimension,
                        "evidence_level": "none",
                        "review_flags": [],
                        "evidence_count": 0,
                        "updated_at": None,
                    }
                    for dimension in required
                ],
            }
        run = database.get(LearningRun, learning_run_id)
        if run is None or run.skill_id != goal.skill_id or run.skill_version != goal.skill_version:
            raise ReadinessError(
                422,
                "learning_run_scope_mismatch",
                "学习记录不属于当前目标的技能包版本。",
            )
        rows = {
            row.dimension: row
            for row in database.scalars(
                select(MasterySnapshot).where(MasterySnapshot.run_id == run.id)
            ).all()
        }
        return {
            "learning_run_id": run.id,
            "learning_run_status": run.status,
            "skill_id": run.skill_id,
            "skill_version": run.skill_version,
            "capability_scope_id": goal.capability_scope_id,
            "dimensions": [
                {
                    "dimension": dimension,
                    "evidence_level": (
                        rows[dimension].evidence_level if dimension in rows else "none"
                    ),
                    "review_flags": (
                        json.loads(rows[dimension].review_flags_json) if dimension in rows else []
                    ),
                    "evidence_count": (rows[dimension].evidence_count if dimension in rows else 0),
                    "updated_at": (
                        rows[dimension].updated_at.isoformat() if dimension in rows else None
                    ),
                }
                for dimension in required
            ],
        }

    def _ensure_policy_snapshot(self, database: Session) -> ReadinessPolicySnapshot:
        digest = _sha256(self._policy)
        existing = database.scalar(
            select(ReadinessPolicySnapshot).where(
                ReadinessPolicySnapshot.policy_id == self._policy["id"],
                ReadinessPolicySnapshot.policy_version == self._policy["version"],
            )
        )
        if existing is not None:
            if existing.payload_sha256 != digest:
                raise ReadinessError(
                    409,
                    "readiness_policy_version_conflict",
                    "同一准备度策略版本的内容摘要发生冲突。必须发布新版本。",
                )
            return existing
        snapshot = ReadinessPolicySnapshot(
            id=str(uuid4()),
            policy_id=self._policy["id"],
            policy_version=self._policy["version"],
            payload_sha256=digest,
            payload_json=_canonical_json(self._policy),
            created_at=self._now(),
        )
        database.add(snapshot)
        database.flush()
        return snapshot

    def _ensure_market_snapshots(
        self,
        database: Session,
    ) -> list[MarketEvidenceSnapshot]:
        result: list[MarketEvidenceSnapshot] = []
        for fixture in self._fixtures:
            digest = _sha256(fixture)
            existing = database.scalar(
                select(MarketEvidenceSnapshot).where(
                    MarketEvidenceSnapshot.fixture_id == fixture["id"],
                    MarketEvidenceSnapshot.fixture_version == fixture["version"],
                )
            )
            if existing is not None:
                if existing.payload_sha256 != digest:
                    raise ReadinessError(
                        409,
                        "market_fixture_version_conflict",
                        "同一合成市场夹具版本的内容摘要发生冲突。必须发布新版本。",
                        {"fixture_id": fixture["id"]},
                    )
            else:
                existing = MarketEvidenceSnapshot(
                    id=str(uuid4()),
                    fixture_id=fixture["id"],
                    fixture_version=fixture["version"],
                    label=fixture["label"],
                    synthetic=True,
                    freshness_status=fixture["freshness_status"],
                    payload_sha256=digest,
                    payload_json=_canonical_json(fixture),
                    created_at=self._now(),
                )
                database.add(existing)
                database.flush()
            result.append(existing)
        return result

    def _goal_payload(self, goal: UserGoalSelection) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "id": goal.id,
            "skill_id": goal.skill_id,
            "skill_version": goal.skill_version,
            "capability_scope_id": goal.capability_scope_id,
            "goal_kind": goal.goal_kind,
            "custom_label": goal.custom_label,
            "market_comparison_applicable": goal.goal_kind in MONETIZATION_GOALS,
            "created_at": goal.created_at,
            "superseded_at": goal.superseded_at,
        }

    def _market_snapshot_payload(
        self,
        snapshot: MarketEvidenceSnapshot,
    ) -> dict[str, Any]:
        payload = json.loads(snapshot.payload_json)
        return {
            "id": snapshot.id,
            "fixture_id": snapshot.fixture_id,
            "fixture_version": snapshot.fixture_version,
            "label": snapshot.label,
            "synthetic": snapshot.synthetic,
            "freshness_status": snapshot.freshness_status,
            "as_of": payload["as_of"],
            "limitations": payload["limitations"],
            "source_count": len(payload["sources"]),
            "created_at": snapshot.created_at,
        }

    def _evaluation_payload(
        self,
        database: Session,
        evaluation: ReadinessEvaluation,
    ) -> dict[str, Any]:
        policy = database.get(ReadinessPolicySnapshot, evaluation.policy_snapshot_id)
        return {
            "schema_version": "1.0.0",
            "id": evaluation.id,
            "goal_selection_id": evaluation.goal_selection_id,
            "learning_run_id": evaluation.learning_run_id,
            "policy_id": policy.policy_id if policy is not None else "missing",
            "policy_version": (policy.policy_version if policy is not None else "missing"),
            "market_snapshot_id": evaluation.market_snapshot_id,
            "status": evaluation.status,
            "reason_codes": json.loads(evaluation.reason_codes_json),
            "evidence_snapshot": json.loads(evaluation.evidence_snapshot_json),
            "limitations": json.loads(evaluation.limitations_json),
            "input_sha256": evaluation.input_sha256,
            "created_at": evaluation.created_at,
        }

    def _comparison_payload(
        self,
        database: Session,
        comparison: PathComparison,
    ) -> dict[str, Any]:
        payload = json.loads(comparison.comparison_json)
        decisions = database.scalars(
            select(PathComparisonDecision)
            .where(PathComparisonDecision.comparison_id == comparison.id)
            .order_by(PathComparisonDecision.revision)
        ).all()
        return {
            **payload,
            "payload_sha256": comparison.payload_sha256,
            "decisions": [self._decision_payload(item) for item in decisions],
        }

    @staticmethod
    def _decision_payload(item: PathComparisonDecision) -> dict[str, Any]:
        return {
            "id": item.id,
            "comparison_id": item.comparison_id,
            "revision": item.revision,
            "decision": item.decision,
            "reason": item.reason,
            "created_at": item.created_at,
        }

    def _event(
        self,
        database: Session,
        event_type: str,
        payload: dict[str, Any],
        now: datetime,
        *,
        goal_selection_id: str | None = None,
        evaluation_id: str | None = None,
        comparison_id: str | None = None,
    ) -> None:
        database.add(
            ReadinessEvent(
                goal_selection_id=goal_selection_id,
                evaluation_id=evaluation_id,
                comparison_id=comparison_id,
                event_type=event_type,
                payload_json=_canonical_json(payload),
                occurred_at=now,
            )
        )

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"{path}: expected a JSON object")
        return value
