# ruff: noqa: RUF001

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.governance import SkillPackage
from cloud_study_api.models import (
    DiagnosticSession,
    PlanningChangeEvent,
    PlanningProposal,
    PlanningUnit,
    PlanningUnitSource,
    SourceChangeCandidate,
    SourceCheckResult,
    SourceCheckRun,
    utc_now,
)
from cloud_study_api.notifications import NotificationService


class LearningError(RuntimeError):
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


@dataclass(frozen=True, slots=True)
class SourceObservation:
    http_status: int
    etag: str | None
    last_modified: str | None
    final_url: str


class SourceFetcher(Protocol):
    def fetch(self, source: dict[str, Any]) -> SourceObservation: ...


class HttpSourceFetcher:
    def fetch(self, source: dict[str, Any]) -> SourceObservation:
        request = urllib.request.Request(
            source["url"],
            headers={
                "User-Agent": (
                    "CloudStudy/0.1 local-source-monitor (metadata check; contact repository owner)"
                ),
                "Range": "bytes=0-0",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=6) as response:
                response.read(1)
                return SourceObservation(
                    http_status=int(response.status),
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    final_url=response.geturl(),
                )
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"HTTP {error.code}") from error
        except urllib.error.URLError as error:
            reason = type(error.reason).__name__
            raise RuntimeError(f"network error ({reason})") from error
        except TimeoutError as error:
            raise RuntimeError("network timeout") from error


class LearningService:
    def __init__(
        self,
        repository_root: Path,
        packages: list[SkillPackage],
        session_factory: sessionmaker[Session],
        notification_service: NotificationService,
        source_fetcher: SourceFetcher | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository_root = repository_root
        self._packages = {(package.package_id, package.version): package for package in packages}
        self._session_factory = session_factory
        self._notifications = notification_service
        self._source_fetcher = source_fetcher or HttpSourceFetcher()
        self._now = now
        self._catalogs: dict[tuple[str, str], dict[str, Any]] = {}
        self._templates: dict[tuple[str, str], dict[str, Any]] = {}

    def create_planning_proposal(
        self,
        *,
        diagnostic_session_id: str,
        preview: bool,
        provider_id: str,
        model_id: str,
    ) -> dict[str, Any]:
        if not preview:
            raise LearningError(
                409,
                "draft_requires_preview",
                "The draft algorithm package can only create planning previews.",
            )
        if provider_id != "local-deterministic" or model_id != "planner-sim-v1":
            raise LearningError(
                409,
                "preview_requires_local_planner",
                "Planning preview requires the local deterministic planner.",
            )
        with self._session_factory() as database:
            diagnostic = database.get(DiagnosticSession, diagnostic_session_id)
            if diagnostic is None:
                raise LearningError(
                    404,
                    "diagnostic_session_not_found",
                    "Diagnostic session not found.",
                )
            if diagnostic.status != "ended":
                raise LearningError(
                    409,
                    "diagnostic_session_not_ended",
                    "End the diagnostic session before creating a planning preview.",
                )
            package = self._package(diagnostic.skill_id, diagnostic.skill_version)
            if package.state != "draft" or package.availability != "available":
                raise LearningError(
                    409,
                    "skill_package_not_previewable",
                    "The skill package cannot create a local planning preview.",
                )
            existing = database.scalar(
                select(PlanningProposal)
                .where(
                    PlanningProposal.diagnostic_session_id == diagnostic.id,
                    PlanningProposal.status != "rejected",
                )
                .order_by(PlanningProposal.created_at.desc())
            )
            if existing is not None:
                return self._proposal_payload(database, existing)

            template = self._template(package)
            proposal_id = str(uuid4())
            now = self._now()
            proposal = PlanningProposal(
                id=proposal_id,
                diagnostic_session_id=diagnostic.id,
                skill_id=package.package_id,
                skill_version=package.version,
                template_id=template["id"],
                provider_id=provider_id,
                model_id=model_id,
                is_preview=True,
                status="draft",
                title=template["title"],
                rationale=template["rationale"],
                limitations_json=json.dumps(
                    template["limitations"],
                    ensure_ascii=False,
                ),
                created_at=now,
                updated_at=now,
            )
            database.add(proposal)
            for sequence, item in enumerate(template["units"], start=1):
                unit = PlanningUnit(
                    id=str(uuid4()),
                    proposal_id=proposal_id,
                    template_unit_id=item["id"],
                    sequence=sequence,
                    title=item["title"],
                    objective=item["objective"],
                    reason=item["reason"],
                    estimated_minutes=item["estimated_minutes"],
                    completion_criteria_json=json.dumps(
                        item["completion_criteria"],
                        ensure_ascii=False,
                    ),
                )
                database.add(unit)
                for source_id in item["source_ids"]:
                    database.add(
                        PlanningUnitSource(
                            planning_unit_id=unit.id,
                            source_id=source_id,
                        )
                    )
            self._planning_event(
                database,
                proposal_id,
                "planning_preview_created",
                {
                    "diagnostic_session_id": diagnostic.id,
                    "template_id": template["id"],
                    "provider_id": provider_id,
                    "model_id": model_id,
                },
                now,
            )
            database.commit()
            self._notifications.create(
                category="planning",
                severity="info",
                title="规划预览已生成",
                message="本地确定性规划预览已生成，请检查安排原因、完成标准和来源。",
                related_type="planning_proposal",
                related_id=proposal.id,
                deduplication_key=f"planning-created:{proposal.id}",
            )
            return self._proposal_payload(database, proposal)

    def get_latest_proposal(
        self,
        skill_id: str,
        skill_version: str,
    ) -> dict[str, Any]:
        with self._session_factory() as database:
            proposal = database.scalar(
                select(PlanningProposal)
                .where(
                    PlanningProposal.skill_id == skill_id,
                    PlanningProposal.skill_version == skill_version,
                    PlanningProposal.status != "rejected",
                )
                .order_by(PlanningProposal.created_at.desc())
            )
            if proposal is None:
                raise LearningError(
                    404,
                    "planning_proposal_not_found",
                    "No planning proposal exists.",
                )
            return self._proposal_payload(database, proposal)

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self._session_factory() as database:
            return self._proposal_payload(
                database,
                self._proposal(database, proposal_id),
            )

    def update_planning_unit(
        self,
        proposal_id: str,
        unit_id: str,
        *,
        title: str,
        objective: str,
        reason: str,
        estimated_minutes: int,
        completion_criteria: list[str],
    ) -> dict[str, Any]:
        if not 15 <= estimated_minutes <= 180:
            raise LearningError(
                422,
                "invalid_estimated_minutes",
                "Estimated minutes must be between 15 and 180.",
            )
        if not completion_criteria or any(not item.strip() for item in completion_criteria):
            raise LearningError(
                422,
                "completion_criteria_required",
                "At least one non-empty completion criterion is required.",
            )
        with self._session_factory() as database:
            proposal = self._writable_proposal(database, proposal_id)
            unit = database.get(PlanningUnit, unit_id)
            if unit is None or unit.proposal_id != proposal.id:
                raise LearningError(404, "planning_unit_not_found", "Planning unit not found.")
            previous = {
                "title": unit.title,
                "objective": unit.objective,
                "reason": unit.reason,
                "estimated_minutes": unit.estimated_minutes,
                "completion_criteria": json.loads(unit.completion_criteria_json),
            }
            unit.title = title.strip()
            unit.objective = objective.strip()
            unit.reason = reason.strip()
            unit.estimated_minutes = estimated_minutes
            unit.completion_criteria_json = json.dumps(
                [item.strip() for item in completion_criteria],
                ensure_ascii=False,
            )
            proposal.updated_at = self._now()
            self._planning_event(
                database,
                proposal.id,
                "planning_unit_edited",
                {"unit_id": unit.id, "previous": previous},
                proposal.updated_at,
            )
            database.commit()
            return self._proposal_payload(database, proposal)

    def set_proposal_status(self, proposal_id: str, status: str) -> dict[str, Any]:
        if status not in {"saved_preview", "rejected"}:
            raise LearningError(
                422,
                "invalid_planning_status",
                "Planning preview can only be saved or rejected.",
            )
        with self._session_factory() as database:
            proposal = self._writable_proposal(database, proposal_id)
            proposal.status = status
            proposal.updated_at = self._now()
            self._planning_event(
                database,
                proposal.id,
                f"planning_preview_{status}",
                {"status": status},
                proposal.updated_at,
            )
            database.commit()
            return self._proposal_payload(database, proposal)

    def check_sources(
        self,
        *,
        skill_id: str,
        skill_version: str,
        manual: bool,
    ) -> dict[str, Any]:
        package = self._package(skill_id, skill_version)
        catalog = self._catalog(package)
        now = self._now()
        local_date = now.astimezone().date().isoformat()
        trigger = "manual" if manual else "automatic"
        with self._session_factory() as database:
            if not manual:
                existing = database.scalar(
                    select(SourceCheckRun).where(
                        SourceCheckRun.skill_id == skill_id,
                        SourceCheckRun.skill_version == skill_version,
                        SourceCheckRun.local_date == local_date,
                        SourceCheckRun.trigger == "automatic",
                    )
                )
                if existing is not None:
                    return self._source_run_payload(database, existing, reused=True)
            run = SourceCheckRun(
                id=str(uuid4()),
                skill_id=skill_id,
                skill_version=skill_version,
                local_date=local_date,
                trigger=trigger,
                status="running",
                checked_count=0,
                changed_count=0,
                failed_count=0,
                started_at=now,
            )
            database.add(run)
            database.commit()

        failed: list[tuple[dict[str, Any], SourceCheckResult]] = []
        indeterminate: list[tuple[dict[str, Any], SourceCheckResult]] = []
        changed: list[SourceChangeCandidate] = []
        recovered: list[str] = []
        with self._session_factory() as database:
            run = cast(SourceCheckRun, database.get(SourceCheckRun, run.id))
            for source in catalog["sources"]:
                previous = self._latest_result(
                    database,
                    source["id"],
                    skill_id=skill_id,
                    skill_version=skill_version,
                    successful_only=True,
                )
                latest_any = self._latest_result(
                    database,
                    source["id"],
                    skill_id=skill_id,
                    skill_version=skill_version,
                    successful_only=False,
                )
                result = self._check_one_source(run.id, source, previous, now)
                database.add(result)
                run.checked_count += 1
                if result.status == "failed":
                    run.failed_count += 1
                    failed.append((source, result))
                elif result.status == "indeterminate":
                    indeterminate.append((source, result))
                elif result.status == "changed":
                    run.changed_count += 1
                    candidate = self._change_candidate(
                        database,
                        package,
                        source,
                        previous,
                        result,
                        now,
                    )
                    if candidate is not None:
                        changed.append(candidate)
                elif latest_any is not None and latest_any.status == "failed":
                    recovered.append(source["title"])
            run.status = "completed_with_failures" if run.failed_count else "completed"
            run.completed_at = self._now()
            database.commit()
            payload = self._source_run_payload(database, run, reused=False)

        if failed:
            failure_lines = []
            for source, result in failed:
                last_success = (
                    result.last_success_at.isoformat()
                    if result.last_success_at is not None
                    else "尚无成功记录"
                )
                failure_lines.append(
                    f"{source['title']}：{result.error_message}；最近成功：{last_success}"
                )
            self._notifications.create(
                category="source_check",
                severity="warning",
                title="部分远程来源无法检查",
                message=(
                    "本次失败不会阻止学习，但相关内容可能未完成最新复核。"
                    + "；".join(failure_lines)
                ),
                related_type="source_check_run",
                related_id=run.id,
                deduplication_key=(f"source-failure:{skill_id}:{skill_version}:{local_date}"),
            )
        if indeterminate:
            titles = "、".join(source["title"] for source, _result in indeterminate)
            self._notifications.create(
                category="source_check",
                severity="warning",
                title="部分来源无法自动判断是否变化",
                message=(
                    f"{titles} 没有提供可比较的 ETag 或 Last-Modified，"
                    "系统不会将其记录为“未变化”，请人工复核。"
                ),
                related_type="source_check_run",
                related_id=run.id,
                deduplication_key=(f"source-indeterminate:{skill_id}:{skill_version}:{local_date}"),
            )
        if changed:
            titles = "、".join(candidate.source_title for candidate in changed)
            self._notifications.create(
                category="source_update",
                severity="action_required",
                title="发现需要审查的来源变化",
                message=(
                    f"{titles} 的远程元数据发生变化。系统只创建候选，不会自动废弃技能包或修改计划。"
                ),
                related_type="source_check_run",
                related_id=run.id,
                deduplication_key=(f"source-change:{skill_id}:{skill_version}:{local_date}"),
            )
        if recovered:
            self._notifications.create(
                category="source_check",
                severity="info",
                title="远程来源检查已恢复",
                message=f"以下来源已恢复：{'、'.join(recovered)}。",
                related_type="source_check_run",
                related_id=run.id,
                deduplication_key=(f"source-recovered:{skill_id}:{skill_version}:{local_date}"),
            )
        self._notifications.process_outbox()
        return payload

    def list_change_candidates(
        self,
        skill_id: str,
        skill_version: str,
    ) -> list[dict[str, Any]]:
        with self._session_factory() as database:
            candidates = database.scalars(
                select(SourceChangeCandidate)
                .where(
                    SourceChangeCandidate.skill_id == skill_id,
                    SourceChangeCandidate.skill_version == skill_version,
                )
                .order_by(SourceChangeCandidate.created_at.desc())
            ).all()
            return [self._candidate_payload(candidate) for candidate in candidates]

    def resolve_change_candidate(
        self,
        candidate_id: str,
        decision: str,
    ) -> dict[str, Any]:
        if decision not in {"dismissed", "accepted"}:
            raise LearningError(
                422,
                "invalid_candidate_decision",
                "Candidate decision must be dismissed or accepted.",
            )
        with self._session_factory() as database:
            candidate = database.get(SourceChangeCandidate, candidate_id)
            if candidate is None:
                raise LearningError(
                    404,
                    "source_change_candidate_not_found",
                    "Source change candidate not found.",
                )
            if candidate.status != "pending":
                raise LearningError(
                    409,
                    "source_change_candidate_resolved",
                    "The source change candidate is already resolved.",
                )
            candidate.status = decision
            candidate.resolved_at = self._now()
            database.commit()
            if decision == "accepted":
                self._notifications.create(
                    category="source_update",
                    severity="action_required",
                    title="来源变化已接受，等待版本化处理",
                    message=(
                        "接受候选不会自动修改技能包。下一步需要生成影响报告、"
                        "候选版本并再次获得明确批准。"
                    ),
                    related_type="source_change_candidate",
                    related_id=candidate.id,
                    deduplication_key=f"candidate-accepted:{candidate.id}",
                )
            return self._candidate_payload(candidate)

    def _package(self, skill_id: str, skill_version: str) -> SkillPackage:
        try:
            return self._packages[(skill_id, skill_version)]
        except KeyError as error:
            raise LearningError(
                404,
                "skill_package_not_found",
                "The requested skill package version is not registered.",
            ) from error

    def _content(
        self,
        package: SkillPackage,
        kind: str,
    ) -> dict[str, Any]:
        entries = [item for item in package.manifest["content_files"] if item["kind"] == kind]
        if len(entries) != 1:
            raise LearningError(
                409,
                f"{kind}_unavailable",
                f"The skill package must contain exactly one {kind}.",
            )
        value = yaml.safe_load((package.path / entries[0]["path"]).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"{kind} must be a YAML object")
        return cast(dict[str, Any], value)

    def _catalog(self, package: SkillPackage) -> dict[str, Any]:
        identity = (package.package_id, package.version)
        if identity not in self._catalogs:
            self._catalogs[identity] = self._content(package, "source_catalog")
        return self._catalogs[identity]

    def _template(self, package: SkillPackage) -> dict[str, Any]:
        identity = (package.package_id, package.version)
        if identity not in self._templates:
            self._templates[identity] = self._content(package, "planning_template")
        return self._templates[identity]

    def _proposal(self, database: Session, proposal_id: str) -> PlanningProposal:
        proposal = database.get(PlanningProposal, proposal_id)
        if proposal is None:
            raise LearningError(404, "planning_proposal_not_found", "Planning proposal not found.")
        return proposal

    def _writable_proposal(
        self,
        database: Session,
        proposal_id: str,
    ) -> PlanningProposal:
        proposal = self._proposal(database, proposal_id)
        if proposal.status != "draft":
            raise LearningError(
                409,
                "planning_proposal_read_only",
                "Saved or rejected planning previews are read-only.",
            )
        return proposal

    def _proposal_payload(
        self,
        database: Session,
        proposal: PlanningProposal,
    ) -> dict[str, Any]:
        package = self._package(proposal.skill_id, proposal.skill_version)
        source_by_id = {source["id"]: source for source in self._catalog(package)["sources"]}
        units = database.scalars(
            select(PlanningUnit)
            .where(PlanningUnit.proposal_id == proposal.id)
            .order_by(PlanningUnit.sequence)
        ).all()
        unit_payloads = []
        for unit in units:
            source_links = database.scalars(
                select(PlanningUnitSource).where(PlanningUnitSource.planning_unit_id == unit.id)
            ).all()
            unit_payloads.append(
                {
                    "id": unit.id,
                    "template_unit_id": unit.template_unit_id,
                    "sequence": unit.sequence,
                    "title": unit.title,
                    "objective": unit.objective,
                    "reason": unit.reason,
                    "estimated_minutes": unit.estimated_minutes,
                    "completion_criteria": json.loads(unit.completion_criteria_json),
                    "sources": [
                        {
                            "id": source_by_id[link.source_id]["id"],
                            "title": source_by_id[link.source_id]["title"],
                            "publisher": source_by_id[link.source_id]["publisher"],
                            "url": source_by_id[link.source_id]["url"],
                            "authority_tier": source_by_id[link.source_id]["authority_tier"],
                            "retrieved_at": source_by_id[link.source_id]["retrieved_at"],
                        }
                        for link in source_links
                    ],
                }
            )
        return {
            "id": proposal.id,
            "diagnostic_session_id": proposal.diagnostic_session_id,
            "skill_id": proposal.skill_id,
            "skill_version": proposal.skill_version,
            "template_id": proposal.template_id,
            "provider_id": proposal.provider_id,
            "model_id": proposal.model_id,
            "is_preview": proposal.is_preview,
            "status": proposal.status,
            "title": proposal.title,
            "rationale": proposal.rationale,
            "limitations": json.loads(proposal.limitations_json),
            "units": unit_payloads,
            "created_at": proposal.created_at,
            "updated_at": proposal.updated_at,
        }

    def _planning_event(
        self,
        database: Session,
        proposal_id: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        database.add(
            PlanningChangeEvent(
                proposal_id=proposal_id,
                event_type=event_type,
                payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                occurred_at=occurred_at,
            )
        )

    def _latest_result(
        self,
        database: Session,
        source_id: str,
        *,
        skill_id: str,
        skill_version: str,
        successful_only: bool,
    ) -> SourceCheckResult | None:
        statement = (
            select(SourceCheckResult)
            .join(SourceCheckRun, SourceCheckResult.run_id == SourceCheckRun.id)
            .where(
                SourceCheckResult.source_id == source_id,
                SourceCheckRun.skill_id == skill_id,
                SourceCheckRun.skill_version == skill_version,
            )
            .order_by(SourceCheckResult.checked_at.desc())
        )
        if successful_only:
            statement = statement.where(
                SourceCheckResult.status.in_(["baseline_created", "unchanged", "changed"])
            )
        return database.scalar(statement)

    def _check_one_source(
        self,
        run_id: str,
        source: dict[str, Any],
        previous: SourceCheckResult | None,
        checked_at: datetime,
    ) -> SourceCheckResult:
        if source["check_mode"] == "manual":
            return SourceCheckResult(
                id=str(uuid4()),
                run_id=run_id,
                source_id=source["id"],
                source_title=source["title"],
                status="manual",
                error_message="该来源按访问或版权条件需要人工复核。",
                checked_at=checked_at,
                last_success_at=previous.checked_at if previous else None,
            )
        try:
            observation = self._source_fetcher.fetch(source)
        except RuntimeError as error:
            return SourceCheckResult(
                id=str(uuid4()),
                run_id=run_id,
                source_id=source["id"],
                source_title=source["title"],
                status="failed",
                error_message=str(error),
                checked_at=checked_at,
                last_success_at=previous.checked_at if previous else None,
            )
        status = "baseline_created"
        if previous is not None:
            before = (previous.etag, previous.last_modified, previous.final_url)
            after = (
                observation.etag,
                observation.last_modified,
                observation.final_url,
            )
            has_validator = any(
                (
                    previous.etag,
                    previous.last_modified,
                    observation.etag,
                    observation.last_modified,
                )
            )
            if previous.final_url != observation.final_url or has_validator:
                status = "unchanged" if before == after else "changed"
            else:
                status = "indeterminate"
        return SourceCheckResult(
            id=str(uuid4()),
            run_id=run_id,
            source_id=source["id"],
            source_title=source["title"],
            status=status,
            http_status=observation.http_status,
            etag=observation.etag,
            last_modified=observation.last_modified,
            final_url=observation.final_url,
            error_message=(
                "来源可访问，但未提供可比较的 ETag 或 Last-Modified，需要人工复核。"
                if status == "indeterminate"
                else None
            ),
            checked_at=checked_at,
            last_success_at=checked_at,
        )

    def _change_candidate(
        self,
        database: Session,
        package: SkillPackage,
        source: dict[str, Any],
        previous: SourceCheckResult | None,
        current: SourceCheckResult,
        created_at: datetime,
    ) -> SourceChangeCandidate | None:
        existing = database.scalar(
            select(SourceChangeCandidate).where(
                SourceChangeCandidate.skill_id == package.package_id,
                SourceChangeCandidate.skill_version == package.version,
                SourceChangeCandidate.source_id == source["id"],
                SourceChangeCandidate.status == "pending",
            )
        )
        if existing is not None:
            return None
        evidence = {
            "previous": {
                "etag": previous.etag if previous else None,
                "last_modified": previous.last_modified if previous else None,
                "final_url": previous.final_url if previous else None,
            },
            "current": {
                "etag": current.etag,
                "last_modified": current.last_modified,
                "final_url": current.final_url,
            },
        }
        candidate = SourceChangeCandidate(
            id=str(uuid4()),
            skill_id=package.package_id,
            skill_version=package.version,
            source_id=source["id"],
            source_title=source["title"],
            status="pending",
            change_kind="remote_metadata_changed",
            summary=(
                "远程响应元数据发生变化，需要人工判断是否影响教学内容。"
                "当前技能包和学习计划均未自动修改。"
            ),
            evidence_json=json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            created_at=created_at,
        )
        database.add(candidate)
        return candidate

    def _source_run_payload(
        self,
        database: Session,
        run: SourceCheckRun,
        *,
        reused: bool,
    ) -> dict[str, Any]:
        results = database.scalars(
            select(SourceCheckResult)
            .where(SourceCheckResult.run_id == run.id)
            .order_by(SourceCheckResult.source_id)
        ).all()
        return {
            "id": run.id,
            "skill_id": run.skill_id,
            "skill_version": run.skill_version,
            "local_date": run.local_date,
            "trigger": run.trigger,
            "status": run.status,
            "checked_count": run.checked_count,
            "changed_count": run.changed_count,
            "failed_count": run.failed_count,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "reused": reused,
            "results": [
                {
                    "source_id": result.source_id,
                    "source_title": result.source_title,
                    "status": result.status,
                    "http_status": result.http_status,
                    "error_message": result.error_message,
                    "last_success_at": result.last_success_at,
                    "checked_at": result.checked_at,
                }
                for result in results
            ],
        }

    def _candidate_payload(self, candidate: SourceChangeCandidate) -> dict[str, Any]:
        return {
            "id": candidate.id,
            "skill_id": candidate.skill_id,
            "skill_version": candidate.skill_version,
            "source_id": candidate.source_id,
            "source_title": candidate.source_title,
            "status": candidate.status,
            "change_kind": candidate.change_kind,
            "summary": candidate.summary,
            "evidence": json.loads(candidate.evidence_json),
            "created_at": candidate.created_at,
            "resolved_at": candidate.resolved_at,
        }
