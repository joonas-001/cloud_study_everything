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

from cloud_study_api.governance import SkillPackage
from cloud_study_api.models import (
    AppSettings,
    DiagnosticAnswer,
    DiagnosticEvent,
    DiagnosticSession,
    utc_now,
)
from cloud_study_api.providers import (
    AnswerSnapshot,
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
                preview=preview,
                provider=provider,
                credential_reference=credential_reference,
                external_ai_consent=external_ai_consent,
                external_ai_enabled=settings.external_ai_enabled,
            )
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

            _, current_question_id = provider.question_path(definition, {})
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
            if self._expire_if_needed(database, session, settings, self._now()):
                database.commit()
                raise DiagnosticError(404, "active_session_not_found", "No active session.")
            package = self._package(skill_id, skill_version)
            definition = self._definition(package)
            provider = self._provider(session.provider_id, session.model_id)
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
            if self._expire_if_needed(database, session, settings, self._now()):
                database.commit()
            definition = self._definition(self._package(session.skill_id, session.skill_version))
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
                transitions=item["transitions"],
            )
            for item in raw["questions"]
        }
        definition = DiagnosticDefinition(
            definition_id=raw["id"],
            skill_id=raw["skill_id"],
            skill_version=raw["skill_version"],
            start_question_id=raw["start_question_id"],
            questions=questions,
        )
        self._definitions[identity] = definition
        return definition

    def _validate_creation(
        self,
        *,
        package: SkillPackage,
        preview: bool,
        provider: DiagnosticProvider,
        credential_reference: str | None,
        external_ai_consent: bool,
        external_ai_enabled: bool,
    ) -> None:
        if package.availability != "available":
            raise DiagnosticError(409, "skill_package_suspended", "The package is suspended.")
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
        if self._expire_if_needed(database, session, settings, self._now()):
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
        definition = self._definition(self._package(session.skill_id, session.skill_version))
        provider = self._provider(session.provider_id, session.model_id)
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
        snapshots = {
            question_id: AnswerSnapshot(
                question_id=question_id,
                response_kind=answer.response_kind,
            )
            for question_id, answer in self._latest_answers(database, session.id).items()
        }
        path, current_question_id = provider.question_path(definition, snapshots)
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

    def _session_payload(
        self,
        database: Session,
        session: DiagnosticSession,
        definition: DiagnosticDefinition,
        provider: DiagnosticProvider,
        settings: AppSettings,
    ) -> dict[str, Any]:
        latest = self._latest_answers(database, session.id)
        snapshots = {
            question_id: AnswerSnapshot(
                question_id=question_id,
                response_kind=answer.response_kind,
            )
            for question_id, answer in latest.items()
        }
        path, _ = provider.question_path(definition, snapshots)
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
                    "revision": answer.revision,
                    "on_current_path": answer.question_id in path_set,
                    "created_at": answer.created_at,
                }
                for answer in sorted(latest.values(), key=lambda item: item.created_at)
            ],
            "ready_to_end": session.status == "active" and session.current_question_id is None,
            "can_generate_plan": False,
            "created_at": session.created_at,
            "last_activity_at": session.last_activity_at,
            "ended_at": session.ended_at,
            "end_reason": session.end_reason,
        }

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
