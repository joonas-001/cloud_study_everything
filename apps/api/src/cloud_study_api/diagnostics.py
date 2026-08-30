from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.adaptive_diagnostics import (
    AdaptiveDecision,
    AdaptiveDiagnosticStateError,
    decide,
)
from cloud_study_api.content_locking import ensure_package_content_lock
from cloud_study_api.governance import RepositoryValidationError, SkillPackage
from cloud_study_api.models import (
    AppSettings,
    DiagnosticAnswer,
    DiagnosticEvent,
    DiagnosticSession,
    utc_now,
)
from cloud_study_api.providers import (
    AdaptiveDiagnosticPolicy,
    AnswerSnapshot,
    DiagnosticCapability,
    DiagnosticDefinition,
    DiagnosticProvider,
    DiagnosticQuestion,
    ProviderRegistry,
)


class DiagnosticError(RuntimeError):
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


class DiagnosticService:
    def __init__(
        self,
        repository_root: Path,
        packages: list[SkillPackage],
        session_factory: sessionmaker[Session],
        provider_registry: ProviderRegistry | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository_root = repository_root
        self._packages = {(package.package_id, package.version): package for package in packages}
        self._session_factory = session_factory
        self._providers = provider_registry or ProviderRegistry()
        self._now = now
        self._definitions: dict[tuple[str, str], DiagnosticDefinition] = {}

    def get_privacy_settings(self) -> dict[str, Any]:
        with self._session_factory() as database:
            settings = self._settings(database)
            return self._privacy_payload(settings)

    def update_privacy_settings(self, external_ai_enabled: bool) -> dict[str, Any]:
        with self._session_factory() as database:
            settings = self._settings(database)
            previous = settings.external_ai_enabled
            settings.external_ai_enabled = external_ai_enabled
            settings.updated_at = self._now()
            database.add(
                DiagnosticEvent(
                    session_id=None,
                    event_type="external_ai_setting_changed",
                    payload_json=json.dumps(
                        {"previous": previous, "current": external_ai_enabled},
                        sort_keys=True,
                    ),
                    occurred_at=self._now(),
                )
            )
            database.commit()
            return self._privacy_payload(settings)

    def create_session(
        self,
        *,
        skill_id: str,
        skill_version: str,
        preview: bool,
        provider_id: str,
        model_id: str,
        credential_reference: str | None,
        external_ai_consent: bool,
    ) -> dict[str, Any]:
        package = self._package(skill_id, skill_version)
        provider = self._provider(provider_id, model_id)
        definition = self._definition(package)
        now = self._now()

        with self._session_factory() as database:
            settings = self._settings(database)
            self._validate_creation(
                package=package,
                definition=definition,
                preview=preview,
                provider=provider,
                credential_reference=credential_reference,
                external_ai_consent=external_ai_consent,
                external_ai_enabled=settings.external_ai_enabled,
            )
            try:
                ensure_package_content_lock(database, package, now)
            except RepositoryValidationError as error:
                raise DiagnosticError(
                    409,
                    "skill_package_content_changed",
                    str(error),
                ) from error
            existing = self._active_session(database, skill_id, skill_version)
            if existing is not None and not self._expire_if_needed(
                database, existing, settings, now
            ):
                raise DiagnosticError(
                    409,
                    "active_session_exists",
                    "An active diagnostic session already exists.",
                    {"session_id": existing.id},
                )

            adaptive_decision = self._adaptive_decision(definition, {})
            if adaptive_decision is None:
                _, current_question_id = provider.question_path(definition, {})
            else:
                current_question_id = adaptive_decision.selected_question_id
            session = DiagnosticSession(
                id=str(uuid4()),
                skill_id=skill_id,
                skill_version=skill_version,
                is_preview=preview,
                provider_id=provider_id,
                model_id=model_id,
                credential_reference=credential_reference,
                external_ai_consent=external_ai_consent,
                external_ai_consent_at=now if external_ai_consent else None,
                status="active",
                current_question_id=current_question_id,
                created_at=now,
                updated_at=now,
                last_activity_at=now,
            )
            database.add(session)
            self._event(
                database,
                session.id,
                "session_created",
                {
                    "skill_id": skill_id,
                    "skill_version": skill_version,
                    "preview": preview,
                    "provider_id": provider_id,
                    "model_id": model_id,
                },
                now,
            )
            if adaptive_decision is not None:
                self._record_adaptive_decision(database, session.id, adaptive_decision, now)
            try:
                database.commit()
            except IntegrityError as error:
                database.rollback()
                active = self._active_session(database, skill_id, skill_version)
                raise DiagnosticError(
                    409,
                    "active_session_exists",
                    "An active diagnostic session already exists.",
                    {"session_id": active.id if active is not None else None},
                ) from error
            return self._session_payload(database, session, definition, provider, settings)

    def get_active_session(self, skill_id: str, skill_version: str) -> dict[str, Any]:
        with self._session_factory() as database:
            settings = self._settings(database)
            session = self._active_session(database, skill_id, skill_version)
            if session is None:
                raise DiagnosticError(404, "active_session_not_found", "No active session.")
            package = self._package(skill_id, skill_version)
            definition = self._definition(package)
            now = self._now()
            if self._end_on_time_limit(
                database, session, definition, now
            ) or self._expire_if_needed(database, session, settings, now):
                database.commit()
                raise DiagnosticError(404, "active_session_not_found", "No active session.")
            provider = self._provider(session.provider_id, session.model_id)
            self._validate_adaptive_state(database, session, definition)
            self._event(
                database,
                session.id,
                "session_resumed",
                {"current_question_id": session.current_question_id},
                self._now(),
            )
            database.commit()
            return self._session_payload(database, session, definition, provider, settings)

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._session_factory() as database:
            settings = self._settings(database)
            session = self._session(database, session_id)
            definition = self._definition(self._package(session.skill_id, session.skill_version))
            now = self._now()
            if self._end_on_time_limit(
                database, session, definition, now
            ) or self._expire_if_needed(database, session, settings, now):
                database.commit()
            provider = self._provider(session.provider_id, session.model_id)
            return self._session_payload(database, session, definition, provider, settings)

    def get_latest_session(self, skill_id: str, skill_version: str) -> dict[str, Any]:
        with self._session_factory() as database:
            settings = self._settings(database)
            session = database.scalar(
                select(DiagnosticSession)
                .where(
                    DiagnosticSession.skill_id == skill_id,
                    DiagnosticSession.skill_version == skill_version,
                )
                .order_by(DiagnosticSession.created_at.desc())
            )
            if session is None:
                raise DiagnosticError(404, "session_not_found", "Session not found.")
            definition = self._definition(self._package(skill_id, skill_version))
            now = self._now()
            if self._end_on_time_limit(
                database, session, definition, now
            ) or self._expire_if_needed(database, session, settings, now):
                database.commit()
            provider = self._provider(session.provider_id, session.model_id)
            return self._session_payload(database, session, definition, provider, settings)

    def submit_answer(
        self,
        session_id: str,
        *,
        question_id: str,
        response_kind: str,
        content: str | None,
    ) -> dict[str, Any]:
        with self._session_factory() as database:
            settings, session, definition, provider = self._writable_context(database, session_id)
            if question_id != session.current_question_id:
                raise DiagnosticError(
                    409,
                    "question_not_current",
                    "Only the current diagnostic question can be answered.",
                )
            self._validate_answer(definition, question_id, response_kind, content)
            existing = self._latest_answers(database, session.id).get(question_id)
            if existing is not None:
                raise DiagnosticError(
                    409,
                    "answer_already_exists",
                    "Use the correction endpoint to revise an existing answer.",
                )
            now = self._now()
            database.add(
                DiagnosticAnswer(
                    id=str(uuid4()),
                    session_id=session.id,
                    question_id=question_id,
                    response_kind=response_kind,
                    content=self._normalized_content(response_kind, content),
                    revision=1,
                    supersedes_answer_id=None,
                    created_at=now,
                )
            )
            database.flush()
            self._recompute_path(database, session, definition, provider, now)
            self._event(
                database,
                session.id,
                "answer_recorded",
                {"question_id": question_id, "response_kind": response_kind, "revision": 1},
                now,
            )
            database.commit()
            return self._session_payload(database, session, definition, provider, settings)

    def correct_answer(
        self,
        session_id: str,
        question_id: str,
        *,
        response_kind: str,
        content: str | None,
    ) -> dict[str, Any]:
        with self._session_factory() as database:
            settings, session, definition, provider = self._writable_context(database, session_id)
            self._validate_answer(definition, question_id, response_kind, content)
            previous = self._latest_answers(database, session.id).get(question_id)
            if previous is None:
                raise DiagnosticError(
                    404,
                    "answer_not_found",
                    "The answer to correct does not exist.",
                )
            now = self._now()
            answer = DiagnosticAnswer(
                id=str(uuid4()),
                session_id=session.id,
                question_id=question_id,
                response_kind=response_kind,
                content=self._normalized_content(response_kind, content),
                revision=previous.revision + 1,
                supersedes_answer_id=previous.id,
                created_at=now,
            )
            database.add(answer)
            database.flush()
            self._recompute_path(database, session, definition, provider, now)
            self._event(
                database,
                session.id,
                "answer_corrected",
                {
                    "question_id": question_id,
                    "response_kind": response_kind,
                    "revision": answer.revision,
                    "supersedes_answer_id": previous.id,
                },
                now,
            )
            database.commit()
            return self._session_payload(database, session, definition, provider, settings)

    def end_session(self, session_id: str) -> dict[str, Any]:
        with self._session_factory() as database:
            settings, session, definition, provider = self._writable_context(database, session_id)
            now = self._now()
            session.status = "ended"
            session.end_reason = "user_ended"
            session.ended_at = now
            session.updated_at = now
            session.last_activity_at = now
            self._event(database, session.id, "session_ended", {"reason": "user_ended"}, now)
            database.commit()
            return self._session_payload(database, session, definition, provider, settings)

    def _settings(self, database: Session) -> AppSettings:
        settings = database.get(AppSettings, 1)
        if settings is None:
            raise RuntimeError("app settings row is missing")
        return settings

    def _privacy_payload(self, settings: AppSettings) -> dict[str, Any]:
        return {
            "external_ai_enabled": settings.external_ai_enabled,
            "inactivity_timeout_minutes": settings.inactivity_timeout_minutes,
            "updated_at": settings.updated_at,
        }

    def _package(self, skill_id: str, skill_version: str) -> SkillPackage:
        try:
            return self._packages[(skill_id, skill_version)]
        except KeyError as error:
            raise DiagnosticError(
                404,
                "skill_package_not_found",
                "The requested skill package version is not registered.",
            ) from error

    def _provider(self, provider_id: str, model_id: str) -> DiagnosticProvider:
        try:
            provider = self._providers.get(provider_id)
        except KeyError as error:
            raise DiagnosticError(422, "unsupported_provider", str(error)) from error
        if model_id not in provider.capabilities.model_ids:
            raise DiagnosticError(
                422,
                "unsupported_model",
                "The model is not declared by the selected provider.",
            )
        return provider

    def _definition(self, package: SkillPackage) -> DiagnosticDefinition:
        identity = (package.package_id, package.version)
        if identity in self._definitions:
            return self._definitions[identity]
        entries = [
            entry
            for entry in package.manifest["content_files"]
            if entry["kind"] == "diagnostic_definition"
        ]
        if len(entries) != 1:
            raise DiagnosticError(
                409,
                "diagnostic_definition_unavailable",
                "The skill package must contain exactly one diagnostic definition.",
            )
        path = package.path / entries[0]["path"]
        raw = cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))
        questions = {
            item["id"]: DiagnosticQuestion(
                question_id=item["id"],
                prompt=item["prompt"],
                reason=item["reason"],
                response_type=item["response_type"],
                options=tuple(
                    (option["value"], option["label"]) for option in item.get("options", [])
                ),
                transitions=item["transitions"],
                question_version=item.get("question_version"),
                capability_ids=tuple(item.get("capability_ids", [])),
                prerequisite_capability_ids=tuple(item.get("prerequisite_capability_ids", [])),
                difficulty=item.get("difficulty"),
                signal_kind=item.get("signal_kind"),
                deterministic_answer_values=frozenset(item.get("deterministic_answer_values", [])),
                critical_misconception_values=frozenset(
                    item.get("critical_misconception_values", [])
                ),
                selection_reason_code=item.get("selection_reason_code"),
                allows_early_stop=bool(item.get("allows_early_stop", False)),
                estimated_minutes=int(item.get("estimated_minutes", 1)),
            )
            for item in raw["questions"]
        }
        policy: AdaptiveDiagnosticPolicy | None = None
        capabilities: dict[str, DiagnosticCapability] | None = None
        if raw.get("schema_version") == "2.0.0":
            policy_raw = self._content_document(package, "diagnostic_policy")
            graph_raw = self._content_document(package, "capability_graph")
            if raw.get("policy_id") != policy_raw.get("id"):
                raise DiagnosticError(
                    409,
                    "diagnostic_policy_mismatch",
                    "The diagnostic definition and policy identifiers do not match.",
                )
            policy = AdaptiveDiagnosticPolicy(
                policy_id=policy_raw["id"],
                version=policy_raw["version"],
                session_question_max=int(policy_raw["session_question_max"]),
                session_minutes_max=int(policy_raw["session_minutes_max"]),
                fallback=policy_raw["fallback"],
                evidence_ceiling=policy_raw["evidence_ceiling"],
            )
            capabilities = {
                item["id"]: DiagnosticCapability(
                    capability_id=item["id"],
                    prerequisite_capability_ids=tuple(item.get("prerequisite_capability_ids", [])),
                )
                for item in graph_raw["capabilities"]
            }
        definition = DiagnosticDefinition(
            definition_id=raw["id"],
            skill_id=raw["skill_id"],
            skill_version=raw["skill_version"],
            start_question_id=raw["start_question_id"],
            questions=questions,
            schema_version=raw.get("schema_version", "1.0.0"),
            policy=policy,
            capabilities=capabilities,
        )
        self._definitions[identity] = definition
        return definition

    def _content_document(self, package: SkillPackage, kind: str) -> dict[str, Any]:
        entries = [entry for entry in package.manifest["content_files"] if entry["kind"] == kind]
        if len(entries) != 1:
            raise DiagnosticError(
                409,
                "diagnostic_metadata_unavailable",
                f"The skill package must contain exactly one {kind} document.",
            )
        path = package.path / entries[0]["path"]
        return cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))

    def _validate_creation(
        self,
        *,
        package: SkillPackage,
        definition: DiagnosticDefinition,
        preview: bool,
        provider: DiagnosticProvider,
        credential_reference: str | None,
        external_ai_consent: bool,
        external_ai_enabled: bool,
    ) -> None:
        if package.availability != "available":
            raise DiagnosticError(409, "skill_package_suspended", "The package is suspended.")
        if package.intake != "open":
            raise DiagnosticError(
                409,
                "skill_package_intake_closed",
                "This package version is read-only and cannot start new diagnostics.",
            )
        if (
            definition.schema_version == "2.0.0"
            and provider.capabilities.provider_id != "local-deterministic"
        ):
            raise DiagnosticError(
                409,
                "adaptive_requires_local_provider",
                "The deterministic adaptive diagnostic cannot use an external provider.",
            )
        if package.state == "draft":
            if not preview:
                raise DiagnosticError(
                    409,
                    "draft_requires_preview",
                    "Draft skill packages require preview mode.",
                )
            if provider.capabilities.provider_id != "local-deterministic":
                raise DiagnosticError(
                    409,
                    "preview_requires_local_provider",
                    "Draft preview requires the local deterministic provider.",
                )
            if credential_reference is not None or external_ai_consent:
                raise DiagnosticError(
                    409,
                    "preview_forbids_external_ai",
                    "Draft preview cannot use credentials or external AI consent.",
                )
        elif package.state != "active":
            raise DiagnosticError(
                409,
                "skill_package_not_eligible",
                "The package lifecycle state cannot start diagnostics.",
            )
        if provider.capabilities.is_external:
            if not external_ai_enabled:
                raise DiagnosticError(
                    403,
                    "external_ai_disabled",
                    "The global external AI permission is disabled.",
                )
            if not external_ai_consent:
                raise DiagnosticError(
                    403,
                    "conversation_consent_required",
                    "Conversation-level external AI consent is required.",
                )
            if not credential_reference:
                raise DiagnosticError(
                    422,
                    "credential_reference_required",
                    "External providers require a credential reference.",
                )

    def _active_session(
        self, database: Session, skill_id: str, skill_version: str
    ) -> DiagnosticSession | None:
        return database.scalar(
            select(DiagnosticSession).where(
                DiagnosticSession.skill_id == skill_id,
                DiagnosticSession.skill_version == skill_version,
                DiagnosticSession.status == "active",
            )
        )

    def _session(self, database: Session, session_id: str) -> DiagnosticSession:
        session = database.get(DiagnosticSession, session_id)
        if session is None:
            raise DiagnosticError(404, "session_not_found", "Session not found.")
        return session

    def _expire_if_needed(
        self,
        database: Session,
        session: DiagnosticSession,
        settings: AppSettings,
        now: datetime,
    ) -> bool:
        if session.status != "active":
            return False
        deadline = _aware_utc(session.last_activity_at) + timedelta(
            minutes=settings.inactivity_timeout_minutes
        )
        if _aware_utc(now) < deadline:
            return False
        session.status = "ended"
        session.end_reason = "inactivity_timeout"
        session.ended_at = now
        session.updated_at = now
        self._event(
            database,
            session.id,
            "session_ended",
            {"reason": "inactivity_timeout"},
            now,
        )
        return True

    def _writable_context(
        self, database: Session, session_id: str
    ) -> tuple[
        AppSettings,
        DiagnosticSession,
        DiagnosticDefinition,
        DiagnosticProvider,
    ]:
        settings = self._settings(database)
        session = self._session(database, session_id)
        definition = self._definition(self._package(session.skill_id, session.skill_version))
        now = self._now()
        if self._end_on_time_limit(database, session, definition, now):
            database.commit()
            raise DiagnosticError(
                409,
                "session_ended",
                "The session ended because the diagnostic time limit was reached.",
            )
        if self._expire_if_needed(database, session, settings, now):
            database.commit()
            raise DiagnosticError(
                409,
                "session_ended",
                "The session ended because of inactivity.",
            )
        if session.status != "active":
            raise DiagnosticError(409, "session_not_active", "The session is read-only.")
        if self._provider(session.provider_id, session.model_id).capabilities.is_external:
            if not settings.external_ai_enabled:
                raise DiagnosticError(
                    403,
                    "external_ai_disabled",
                    "The global external AI permission is disabled.",
                )
            if not session.external_ai_consent:
                raise DiagnosticError(
                    403,
                    "conversation_consent_required",
                    "Conversation-level external AI consent is missing.",
                )
        provider = self._provider(session.provider_id, session.model_id)
        self._validate_adaptive_state(database, session, definition)
        return settings, session, definition, provider

    def _validate_answer(
        self,
        definition: DiagnosticDefinition,
        question_id: str,
        response_kind: str,
        content: str | None,
    ) -> None:
        if question_id not in definition.questions:
            raise DiagnosticError(404, "question_not_found", "Question not found.")
        if response_kind not in {"answered", "skipped", "uncertain"}:
            raise DiagnosticError(422, "invalid_response_kind", "Invalid response kind.")
        if response_kind == "answered" and not (content or "").strip():
            raise DiagnosticError(422, "answer_content_required", "Answer text is required.")
        if response_kind != "answered" and content not in {None, ""}:
            raise DiagnosticError(
                422,
                "answer_content_forbidden",
                "Skipped and uncertain answers cannot include content.",
            )
        question = definition.questions[question_id]
        if question.response_type == "single_choice" and response_kind == "answered":
            allowed = {value for value, _label in question.options}
            if (content or "").strip() not in allowed:
                raise DiagnosticError(
                    422,
                    "invalid_choice",
                    "The selected diagnostic option is not allowed.",
                )

    def _normalized_content(self, response_kind: str, content: str | None) -> str | None:
        return content.strip() if response_kind == "answered" and content else None

    def _latest_answers(self, database: Session, session_id: str) -> dict[str, DiagnosticAnswer]:
        latest_revisions: Select[tuple[str, int]] = (
            select(
                DiagnosticAnswer.question_id,
                func.max(DiagnosticAnswer.revision).label("revision"),
            )
            .where(DiagnosticAnswer.session_id == session_id)
            .group_by(DiagnosticAnswer.question_id)
        )
        latest = latest_revisions.subquery()
        answers = database.scalars(
            select(DiagnosticAnswer)
            .join(
                latest,
                (DiagnosticAnswer.question_id == latest.c.question_id)
                & (DiagnosticAnswer.revision == latest.c.revision),
            )
            .where(DiagnosticAnswer.session_id == session_id)
        ).all()
        return {answer.question_id: answer for answer in answers}

    def _recompute_path(
        self,
        database: Session,
        session: DiagnosticSession,
        definition: DiagnosticDefinition,
        provider: DiagnosticProvider,
        now: datetime,
    ) -> None:
        latest = self._latest_answers(database, session.id)
        snapshots = self._answer_snapshots(latest)
        adaptive_decision = self._adaptive_decision(definition, snapshots)
        if adaptive_decision is None:
            path, current_question_id = provider.question_path(definition, snapshots)
        else:
            path = sorted(snapshots)
            current_question_id = adaptive_decision.selected_question_id
            self._record_adaptive_decision(
                database,
                session.id,
                adaptive_decision,
                now,
            )
        session.current_question_id = current_question_id
        session.last_activity_at = now
        session.updated_at = now
        self._event(
            database,
            session.id,
            "diagnostic_path_recomputed",
            {"path": path, "current_question_id": current_question_id},
            now,
        )
        if adaptive_decision is not None and adaptive_decision.stop_reason is not None:
            session.status = "ended"
            session.end_reason = (
                "diagnostic_question_limit"
                if adaptive_decision.stop_reason == "question_limit"
                else "diagnostic_complete"
            )
            session.ended_at = now
            self._event(
                database,
                session.id,
                "session_ended",
                {"reason": session.end_reason},
                now,
            )

    def _session_payload(
        self,
        database: Session,
        session: DiagnosticSession,
        definition: DiagnosticDefinition,
        provider: DiagnosticProvider,
        settings: AppSettings,
    ) -> dict[str, Any]:
        latest = self._latest_answers(database, session.id)
        snapshots = self._answer_snapshots(latest)
        adaptive_decision = self._adaptive_decision(definition, snapshots)
        if adaptive_decision is None:
            path, _ = provider.question_path(definition, snapshots)
        else:
            self._validate_adaptive_state(
                database,
                session,
                definition,
                decision=adaptive_decision,
                latest_answers=latest,
            )
            path = sorted(snapshots)
        path_set = set(path)
        current_question = (
            definition.questions[session.current_question_id]
            if session.current_question_id is not None
            else None
        )
        return {
            "id": session.id,
            "skill_id": session.skill_id,
            "skill_version": session.skill_version,
            "is_preview": session.is_preview,
            "provider_id": session.provider_id,
            "model_id": session.model_id,
            "credential_reference": session.credential_reference,
            "external_ai_consent": session.external_ai_consent,
            "external_ai_enabled": settings.external_ai_enabled,
            "status": session.status,
            "current_question": (
                {
                    "id": current_question.question_id,
                    "prompt": current_question.prompt,
                    "reason": current_question.reason,
                    "response_type": current_question.response_type,
                    "options": [
                        {"value": value, "label": label}
                        for value, label in current_question.options
                    ],
                    "selection_reason_code": (
                        adaptive_decision.selection_reason_code
                        if adaptive_decision is not None
                        else None
                    ),
                    "selection_explanation": (
                        adaptive_decision.explanation if adaptive_decision is not None else None
                    ),
                }
                if current_question is not None
                else None
            ),
            "answers": [
                {
                    "id": answer.id,
                    "question_id": answer.question_id,
                    "response_kind": answer.response_kind,
                    "content": answer.content,
                    "response_type": definition.questions[answer.question_id].response_type,
                    "options": [
                        {"value": value, "label": label}
                        for value, label in definition.questions[answer.question_id].options
                    ],
                    "revision": answer.revision,
                    "on_current_path": answer.question_id in path_set,
                    "created_at": answer.created_at,
                }
                for answer in sorted(latest.values(), key=lambda item: _aware_utc(item.created_at))
            ],
            "ready_to_end": session.status == "active" and session.current_question_id is None,
            "can_generate_plan": False,
            "diagnostic_mode": (
                "deterministic_adaptive" if adaptive_decision is not None else "fixed_sequence"
            ),
            "decision": (
                self._decision_payload(adaptive_decision) if adaptive_decision is not None else None
            ),
            "capability_states": (
                [
                    {
                        "capability_id": item.capability_id,
                        "status": item.status,
                        "positive_signal_count": item.positive_signal_count,
                        "negative_signal_count": item.negative_signal_count,
                        "inconclusive_signal_count": item.inconclusive_signal_count,
                        "reason_codes": list(item.reason_codes),
                    }
                    for item in adaptive_decision.capability_states
                ]
                if adaptive_decision is not None
                else []
            ),
            "limits": (
                {
                    "question_max": definition.policy.session_question_max,
                    "minutes_max": definition.policy.session_minutes_max,
                    "evidence_ceiling": definition.policy.evidence_ceiling,
                }
                if definition.policy is not None
                else None
            ),
            "created_at": session.created_at,
            "last_activity_at": session.last_activity_at,
            "ended_at": session.ended_at,
            "end_reason": session.end_reason,
        }

    def _answer_snapshots(
        self,
        latest: dict[str, DiagnosticAnswer],
    ) -> dict[str, AnswerSnapshot]:
        return {
            question_id: AnswerSnapshot(
                question_id=question_id,
                response_kind=answer.response_kind,
                content=answer.content,
                revision=answer.revision,
            )
            for question_id, answer in latest.items()
        }

    def _adaptive_decision(
        self,
        definition: DiagnosticDefinition,
        snapshots: dict[str, AnswerSnapshot],
    ) -> AdaptiveDecision | None:
        if definition.schema_version != "2.0.0":
            return None
        try:
            return decide(definition, snapshots)
        except AdaptiveDiagnosticStateError as error:
            raise DiagnosticError(
                409,
                "diagnostic_state_invalid",
                "The adaptive diagnostic state cannot be interpreted safely.",
                {"reason": str(error)},
            ) from error

    def _decision_payload(self, decision: AdaptiveDecision) -> dict[str, Any]:
        return {
            "engine_version": decision.engine_version,
            "state_sha256": decision.state_sha256,
            "strategy": decision.strategy,
            "selected_question_id": decision.selected_question_id,
            "selection_reason_code": decision.selection_reason_code,
            "explanation": decision.explanation,
            "stop_reason": decision.stop_reason,
            "question_count": decision.question_count,
            "estimated_minutes": decision.estimated_minutes,
        }

    def _record_adaptive_decision(
        self,
        database: Session,
        session_id: str,
        decision: AdaptiveDecision,
        occurred_at: datetime,
    ) -> None:
        self._event(
            database,
            session_id,
            "adaptive_decision",
            self._decision_payload(decision),
            occurred_at,
        )

    def _validate_adaptive_state(
        self,
        database: Session,
        session: DiagnosticSession,
        definition: DiagnosticDefinition,
        *,
        decision: AdaptiveDecision | None = None,
        latest_answers: dict[str, DiagnosticAnswer] | None = None,
    ) -> None:
        if definition.schema_version != "2.0.0":
            return
        now = self._now()
        timestamps = [session.created_at, session.updated_at, session.last_activity_at]
        if session.ended_at is not None:
            timestamps.append(session.ended_at)
        latest = latest_answers or self._latest_answers(database, session.id)
        all_answers = database.scalars(
            select(DiagnosticAnswer).where(DiagnosticAnswer.session_id == session.id)
        ).all()
        all_events = database.scalars(
            select(DiagnosticEvent).where(DiagnosticEvent.session_id == session.id)
        ).all()
        timestamps.extend(answer.created_at for answer in all_answers)
        timestamps.extend(event.occurred_at for event in all_events)
        if any(_aware_utc(timestamp) > _aware_utc(now) for timestamp in timestamps):
            raise DiagnosticError(
                409,
                "diagnostic_future_state",
                "The persisted diagnostic state contains a future timestamp.",
            )
        created_at = _aware_utc(session.created_at)
        if (
            _aware_utc(session.updated_at) < created_at
            or _aware_utc(session.last_activity_at) < created_at
            or (session.ended_at is not None and _aware_utc(session.ended_at) < created_at)
            or any(_aware_utc(answer.created_at) < created_at for answer in all_answers)
            or any(_aware_utc(event.occurred_at) < created_at for event in all_events)
        ):
            raise DiagnosticError(
                409,
                "diagnostic_state_corrupt",
                "The persisted diagnostic timeline is inconsistent.",
            )
        expected = decision or self._adaptive_decision(
            definition,
            self._answer_snapshots(latest),
        )
        assert expected is not None
        audit = database.scalars(
            select(DiagnosticEvent)
            .where(
                DiagnosticEvent.session_id == session.id,
                DiagnosticEvent.event_type == "adaptive_decision",
            )
            .order_by(DiagnosticEvent.id.desc())
        ).first()
        if audit is None or _aware_utc(audit.occurred_at) > _aware_utc(now):
            raise DiagnosticError(
                409,
                "diagnostic_state_corrupt",
                "The adaptive diagnostic audit state is missing or invalid.",
            )
        try:
            recorded = json.loads(audit.payload_json)
        except json.JSONDecodeError as error:
            raise DiagnosticError(
                409,
                "diagnostic_state_corrupt",
                "The adaptive diagnostic audit state is not valid JSON.",
            ) from error
        if recorded != self._decision_payload(expected) or (
            session.current_question_id != expected.selected_question_id
        ):
            raise DiagnosticError(
                409,
                "diagnostic_state_corrupt",
                "The persisted adaptive decision does not match deterministic replay.",
            )

    def _end_on_time_limit(
        self,
        database: Session,
        session: DiagnosticSession,
        definition: DiagnosticDefinition,
        now: datetime,
    ) -> bool:
        if session.status != "active" or definition.policy is None:
            return False
        deadline = _aware_utc(session.created_at) + timedelta(
            minutes=definition.policy.session_minutes_max
        )
        if _aware_utc(now) < deadline:
            return False
        self._validate_adaptive_state(database, session, definition)
        session.status = "ended"
        session.end_reason = "diagnostic_time_limit"
        session.ended_at = now
        session.updated_at = now
        session.last_activity_at = now
        self._event(
            database,
            session.id,
            "session_ended",
            {"reason": "diagnostic_time_limit"},
            now,
        )
        return True

    def _event(
        self,
        database: Session,
        session_id: str | None,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        database.add(
            DiagnosticEvent(
                session_id=session_id,
                event_type=event_type,
                payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                occurred_at=occurred_at,
            )
        )
