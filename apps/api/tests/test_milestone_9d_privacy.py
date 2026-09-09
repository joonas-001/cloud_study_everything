from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.backups import (
    create_encrypted_backup,
    generate_backup_key_pair,
    restore_encrypted_backup,
)
from cloud_study_api.database import (
    create_database_engine,
    create_database_url,
    create_session_factory,
    upgrade_database,
)
from cloud_study_api.identity import IdentityService
from cloud_study_api.main import app
from cloud_study_api.models import (
    AccountStateEvent,
    DiagnosticSession,
    ExternalIdentity,
    InternalUser,
    PrivacyChoice,
    PrivacyDeletionJob,
    PrivacyDeletionTombstone,
    PrivacyPolicyAcceptance,
    PrivacyRequest,
    UserOwnedMixin,
    UserSettings,
)
from cloud_study_api.principals import Principal, principal_scope
from cloud_study_api.privacy import PrivacyError, PrivacyService

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_ISSUER = "urn:cloud-study:synthetic:milestone-9d"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 9, 4, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def _fixture(
    tmp_path: Path,
) -> tuple[Path, sessionmaker[Session], PrivacyService, Principal, Principal, Clock]:
    database_path = tmp_path / "privacy.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    clock = Clock()
    identities = IdentityService(session_factory, now=clock)
    owner = identities.create_synthetic_identity(
        issuer=SYNTHETIC_ISSUER,
        subject="owner",
        role="owner_operator",
    )
    user = identities.create_synthetic_identity(
        issuer=SYNTHETIC_ISSUER,
        subject="user-a",
    )
    service = PrivacyService(session_factory, REPOSITORY_ROOT, now=clock)
    return database_path, session_factory, service, owner, user, clock


def _diagnostic(identifier: str) -> DiagnosticSession:
    now = datetime(2026, 9, 9, tzinfo=UTC)
    return DiagnosticSession(
        id=identifier,
        skill_id="algorithm",
        skill_version="0.2.2",
        is_preview=True,
        provider_id="local-deterministic",
        model_id="diagnostic-v1",
        credential_reference=None,
        external_ai_consent=False,
        external_ai_consent_at=None,
        status="ended",
        current_question_id=None,
        created_at=now,
        updated_at=now,
        last_activity_at=now,
        ended_at=now,
        end_reason="synthetic_privacy_test",
    )


def test_policy_choices_access_correction_and_export_are_current_user_only(tmp_path: Path) -> None:
    _, session_factory, service, owner, user, _ = _fixture(tmp_path)
    identities = IdentityService(session_factory)
    other = identities.create_synthetic_identity(
        issuer=SYNTHETIC_ISSUER,
        subject="user-b",
    )
    with principal_scope(user), session_factory() as database:
        database.add(_diagnostic("private-user-a"))
        database.add(
            AccountStateEvent(
                id="00000000-0000-4000-8000-000000000099",
                user_id=user.user_id,
                actor_user_id=owner.user_id,
                previous_status="active",
                new_status="active",
                reason_code="synthetic_operator_export_test",
                occurred_at=datetime(2026, 9, 9, tzinfo=UTC),
            )
        )
        database.commit()
    with principal_scope(other), session_factory() as database:
        database.add(_diagnostic("private-user-b"))
        database.commit()

    with principal_scope(user):
        initial = service.overview()
        assert initial["status"] == "synthetic_candidate_only"
        assert initial["professional_review"] == "required_before_9g"
        assert initial["real_user_ready"] is False
        notice = next(
            document
            for document in initial["documents"]
            if document["document_type"] == "privacy_notice"
        )
        notice_path = (
            REPOSITORY_ROOT / "governance" / "privacy" / "policies" / "privacy-notice-candidate.md"
        )
        assert notice["content_markdown"] == notice_path.read_text(encoding="utf-8")
        assert notice["content_sha256"] == hashlib.sha256(notice_path.read_bytes()).hexdigest()
        required = [item["document_type"] for item in initial["documents"] if item["required"]]
        accepted = service.accept_documents(required)
        assert all(
            item["accepted"] for item in accepted["documents"] if item["document_type"] in required
        )
        choices = service.update_choices({"external_ai": True, "email_notifications": False})
        ai_choice = next(item for item in choices["choices"] if item["purpose"] == "external_ai")
        assert ai_choice["enabled"] is True
        assert ai_choice["effective_enabled"] is False

        access = service.access_report()
        assert access["table_counts"]["diagnostic_sessions"] == 1
        corrected = service.correct_settings(
            inactivity_timeout_minutes=90,
            choices={"external_sources": False},
        )
        assert corrected["real_user_ready"] is False
        with session_factory() as database:
            assert database.scalar(select(UserSettings)).inactivity_timeout_minutes == 90  # type: ignore[union-attr]

        with pytest.raises(PrivacyError) as unconfirmed:
            service.create_export(confirm_sensitive_data=False)
        assert unconfirmed.value.code == "sensitive_export_confirmation_required"
        exported = service.create_export(confirm_sensitive_data=True)

    assert exported["format"] == "cloud-study-portable-export"
    assert exported["content_sha256"]
    diagnostic_ids = {row["id"] for row in exported["tables"]["diagnostic_sessions"]}
    assert diagnostic_ids == {"private-user-a"}
    serialized = str(exported)
    assert "private-user-b" not in serialized
    assert "user-b" not in serialized
    assert owner.user_id not in serialized
    assert all("actor_user_id" not in event for event in exported["account_state_events"])
    assert "session_token_hashes" in exported["scope"]["excludes"]


def test_deletion_is_reauth_gated_cancellable_and_transactionally_purges_private_data(
    tmp_path: Path,
) -> None:
    database_path, session_factory, service, owner, user, clock = _fixture(tmp_path)
    with principal_scope(user), session_factory() as database:
        database.add(_diagnostic("delete-me"))
        database.commit()

    with principal_scope(user):
        with pytest.raises(PrivacyError) as stale:
            service.request_deletion(reauthenticated_at=clock() - timedelta(minutes=6))
        assert stale.value.code == "recent_reauthentication_required"
        first = service.request_deletion(reauthenticated_at=clock())
    assert first["status"] == "waiting"
    assert first["execute_after"] == clock() + timedelta(days=7)

    cancelled = service.cancel_deletion(user_id=user.user_id, reauthenticated_at=clock())
    assert cancelled["status"] == "cancelled"
    with session_factory() as database:
        assert database.get(InternalUser, user.user_id).status == "active"  # type: ignore[union-attr]

    with principal_scope(user):
        second = service.request_deletion(reauthenticated_at=clock())
    private_key = tmp_path / "offline-private.pem"
    public_key = tmp_path / "backup-public.pem"
    pre_deletion_backup = tmp_path / "pre-deletion-backup.csbak"
    restored_database = tmp_path / "restored-pre-deletion.db"
    session_factory.kw["bind"].dispose()
    generate_backup_key_pair(private_key, public_key)
    create_encrypted_backup(
        database_path,
        pre_deletion_backup,
        public_key,
        policy_id="milestone-9d-synthetic",
        policy_version="1.0.0",
    )

    clock.advance(timedelta(days=8))
    with principal_scope(owner):
        completed = service.run_due_deletions()
        assert [item["id"] for item in completed] == [second["id"]]
        ledger = service.export_deletion_ledger()

    engine = create_database_engine(database_path)
    with engine.connect() as connection:
        assert (
            connection.scalar(select(InternalUser.status).where(InternalUser.id == user.user_id))
            == "deleted"
        )
        assert (
            connection.scalar(
                select(DiagnosticSession.id).where(DiagnosticSession.user_id == user.user_id)
            )
            is None
        )
        assert (
            connection.scalar(
                select(ExternalIdentity.id).where(ExternalIdentity.user_id == user.user_id)
            )
            is None
        )
        tombstone = (
            connection.execute(
                select(PrivacyDeletionTombstone).where(
                    PrivacyDeletionTombstone.user_id == user.user_id
                )
            )
            .mappings()
            .one()
        )
        assert tombstone["retain_until"].replace(tzinfo=UTC) == clock() + timedelta(days=180)
    engine.dispose()

    restore_encrypted_backup(pre_deletion_backup, restored_database, private_key)
    restored_factory = create_session_factory(restored_database)
    restored_service = PrivacyService(restored_factory, REPOSITORY_ROOT, now=clock)
    with principal_scope(owner):
        assert restored_service.reapply_deletion_ledger(ledger) == 1
    restored_engine = create_database_engine(restored_database)
    with restored_engine.connect() as connection:
        assert (
            connection.scalar(select(InternalUser.status).where(InternalUser.id == user.user_id))
            == "deleted"
        )
        assert (
            connection.scalar(
                select(DiagnosticSession.id).where(DiagnosticSession.user_id == user.user_id)
            )
            is None
        )
        restored_job = (
            connection.execute(
                select(PrivacyDeletionJob).where(PrivacyDeletionJob.id == second["id"])
            )
            .mappings()
            .one()
        )
        assert restored_job["status"] == "completed"
        assert (
            restored_job["completed_at"].replace(tzinfo=UTC).isoformat()
            == ledger["records"][0]["completed_at"]
        )
    restored_engine.dispose()


def test_owner_deletion_requires_transfer_and_0014_roundtrip(tmp_path: Path) -> None:
    _, _, service, owner, _, clock = _fixture(tmp_path)
    with principal_scope(owner), pytest.raises(PrivacyError) as blocked:
        service.request_deletion(reauthenticated_at=clock())
    assert blocked.value.code == "owner_transfer_required"

    database_path = tmp_path / "migration.db"
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "apps" / "api" / "migrations"))
    config.set_main_option("sqlalchemy.url", create_database_url(database_path).replace("%", "%%"))
    command.upgrade(config, "0014")
    engine = create_database_engine(database_path)
    assert {
        "privacy_policy_acceptances",
        "privacy_choices",
        "privacy_requests",
        "privacy_deletion_jobs",
        "privacy_deletion_tombstones",
    }.issubset(inspect(engine).get_table_names())
    engine.dispose()
    command.downgrade(config, "0013")
    engine = create_database_engine(database_path)
    assert "privacy_deletion_jobs" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(config, "0014")
    engine = create_database_engine(database_path)
    assert "privacy_choices" in inspect(engine).get_table_names()
    engine.dispose()


def test_privacy_http_contract_enforces_current_synthetic_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path, session_factory, _, _, user, _ = _fixture(tmp_path)
    session_factory.kw["bind"].dispose()
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("CLOUD_STUDY_SYNTHETIC_IDENTITY_ENABLED", "1")
    headers = {
        "X-Cloud-Study-Synthetic-Issuer": SYNTHETIC_ISSUER,
        "X-Cloud-Study-Synthetic-Subject": "user-a",
    }
    with TestClient(app) as client:
        assert client.get("/privacy").status_code == 401
        overview = client.get("/privacy", headers=headers)
        assert overview.status_code == 200
        required = [
            item["document_type"] for item in overview.json()["documents"] if item["required"]
        ]
        accepted = client.post(
            "/privacy/policy-acceptances",
            headers=headers,
            json={"document_types": required},
        )
        assert accepted.status_code == 200
        unconfirmed = client.post(
            "/privacy/exports",
            headers=headers,
            json={"confirm_sensitive_data": False},
        )
        assert unconfirmed.status_code == 409
        exported = client.post(
            "/privacy/exports",
            headers=headers,
            json={"confirm_sensitive_data": True},
        )
        assert exported.status_code == 200
        assert exported.json()["user_id"] == user.user_id
        deletion = client.post("/privacy/deletion-jobs", headers=headers)
        assert deletion.status_code == 200
        assert deletion.json()["status"] == "waiting"


def test_privacy_model_tables_have_expected_classification() -> None:
    assert issubclass(PrivacyPolicyAcceptance, UserOwnedMixin)
    assert issubclass(PrivacyChoice, UserOwnedMixin)
    assert issubclass(PrivacyRequest, UserOwnedMixin)
    assert not issubclass(PrivacyDeletionJob, UserOwnedMixin)
