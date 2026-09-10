from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.credentials import MemoryCredentialStore
from cloud_study_api.database import (
    DataOwnershipError,
    create_database_engine,
    create_database_url,
    create_session_factory,
    read_schema_version,
    upgrade_database,
)
from cloud_study_api.identity import IdentityError, IdentityService
from cloud_study_api.main import app
from cloud_study_api.models import (
    Base,
    DiagnosticAnswer,
    DiagnosticSession,
    UserOwnedMixin,
    utc_now,
)
from cloud_study_api.notifications import NotificationError, NotificationService
from cloud_study_api.principals import (
    LEGACY_OWNER_USER_ID,
    Principal,
    PrincipalAccessError,
    principal_scope,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_ISSUER = "urn:cloud-study:synthetic:milestone-9b"

EXPECTED_USER_OWNED_TABLES = {
    "user_settings",
    "diagnostic_sessions",
    "diagnostic_answers",
    "diagnostic_events",
    "planning_proposals",
    "planning_units",
    "planning_unit_sources",
    "planning_change_events",
    "notification_preferences",
    "notifications",
    "email_outbox",
    "ai_provider_profiles",
    "learning_runs",
    "learning_run_locks",
    "learning_unit_instances",
    "learning_activities",
    "activity_attempts",
    "activity_evaluations",
    "mastery_evidence",
    "mastery_snapshots",
    "review_tasks",
    "learning_events",
    "learning_independent_reviews",
    "runner_invocations",
    "user_goal_selections",
    "readiness_evaluations",
    "path_comparisons",
    "path_comparison_decisions",
    "readiness_events",
    "market_research_runs",
    "market_research_synthesis_attempts",
    "market_research_events",
    "monetization_experiments",
    "experiment_independent_reviews",
    "experiment_action_records",
    "experiment_outcomes",
    "experiment_income_records",
    "experiment_income_revisions",
    "experiment_feedback_suggestions",
    "experiment_events",
    "privacy_policy_acceptances",
    "privacy_choices",
    "privacy_requests",
    "support_cases",
}
EXPECTED_GLOBAL_MANAGED_TABLES = {
    "app_settings",
    "source_check_runs",
    "source_check_results",
    "source_change_candidates",
    "skill_version_content_locks",
    "readiness_policy_snapshots",
    "market_evidence_snapshots",
    "experiment_policy_snapshots",
}
EXPECTED_9C_SECURITY_TABLES = {
    "account_invitations",
    "application_sessions",
    "auth_rate_limit_buckets",
    "auth_security_events",
    "oidc_login_transactions",
}
EXPECTED_9D_OPERATIONAL_TABLES = {
    "privacy_deletion_jobs",
    "privacy_deletion_tombstones",
}
EXPECTED_9E_OPERATIONAL_TABLES = {
    "support_access_grants",
    "operations_controls",
    "operations_quota_buckets",
    "operations_audit_events",
    "operations_metrics",
}


def _migration_config(database_path: Path) -> Config:
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "apps" / "api" / "migrations"))
    config.set_main_option("sqlalchemy.url", create_database_url(database_path).replace("%", "%%"))
    return config


def _identity_fixture(
    tmp_path: Path,
) -> tuple[sessionmaker[Session], IdentityService, Principal, Principal]:
    database_path = tmp_path / "identities.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    identities = IdentityService(session_factory)
    user_a = identities.create_synthetic_identity(
        issuer=SYNTHETIC_ISSUER,
        subject="user-a",
    )
    user_b = identities.create_synthetic_identity(
        issuer=SYNTHETIC_ISSUER,
        subject="user-b",
    )
    return session_factory, identities, user_a, user_b


def _diagnostic(session_id: str) -> DiagnosticSession:
    now = utc_now()
    return DiagnosticSession(
        id=session_id,
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
        end_reason="synthetic_test",
    )


def test_every_existing_table_has_an_explicit_private_or_managed_classification() -> None:
    mapped = {mapper.local_table.name: mapper.class_ for mapper in Base.registry.mappers}
    user_owned = {
        name
        for name, model in mapped.items()
        if isinstance(model, type) and issubclass(model, UserOwnedMixin)
    }
    preexisting = (user_owned - {"user_settings"}) | EXPECTED_GLOBAL_MANAGED_TABLES
    assert user_owned == EXPECTED_USER_OWNED_TABLES
    assert len(preexisting) == 51
    assert (
        set(mapped) - preexisting
        == {
            "user_settings",
            "users",
            "external_identities",
            "user_role_assignments",
            "account_state_events",
        }
        | EXPECTED_9C_SECURITY_TABLES
        | EXPECTED_9D_OPERATIONAL_TABLES
        | EXPECTED_9E_OPERATIONAL_TABLES
    )


def test_principal_scope_blocks_guessed_ids_lists_updates_deletes_and_cross_links(
    tmp_path: Path,
) -> None:
    session_factory, _identities, user_a, user_b = _identity_fixture(tmp_path)
    with principal_scope(user_a), session_factory() as database:
        record = _diagnostic("diagnostic-a")
        database.add(record)
        database.commit()
        assert record.user_id == user_a.user_id

    with principal_scope(user_b), session_factory() as database:
        assert database.get(DiagnosticSession, "diagnostic-a") is None
        assert database.scalars(select(DiagnosticSession)).all() == []
        changed = database.execute(
            update(DiagnosticSession)
            .where(DiagnosticSession.id == "diagnostic-a")
            .values(status="failed")
        )
        assert changed.rowcount == 0
        removed = database.execute(
            delete(DiagnosticSession).where(DiagnosticSession.id == "diagnostic-a")
        )
        assert removed.rowcount == 0
        database.rollback()

        forged = _diagnostic("forged")
        forged.user_id = user_a.user_id
        database.add(forged)
        with pytest.raises(DataOwnershipError):
            database.commit()
        database.rollback()

        answer = DiagnosticAnswer(
            id="cross-linked-answer",
            session_id="diagnostic-a",
            question_id="q-1",
            response_kind="skipped",
            content=None,
            revision=1,
            supersedes_answer_id=None,
            created_at=utc_now(),
        )
        database.add(answer)
        with pytest.raises(DataOwnershipError):
            database.commit()


def test_notifications_and_credentials_are_principal_scoped(tmp_path: Path) -> None:
    session_factory, _identities, user_a, user_b = _identity_fixture(tmp_path)
    credentials = MemoryCredentialStore()
    notifications = NotificationService(session_factory, credentials)
    with principal_scope(user_a):
        notification_id = notifications.create(
            category="synthetic",
            severity="info",
            title="A only",
            message="synthetic content",
        )
        notifications.update_preferences(
            email_enabled=False,
            email_action_required=False,
            email_warning=False,
            email_delay_minutes=10,
            recipient_email="a@example.test",
            sender_email="sender@example.test",
            smtp_host="smtp.example.test",
            smtp_port=465,
            smtp_username="a",
            smtp_security="ssl",
            smtp_password="test-a",
        )
        reference_a = notifications.get_preferences()["credential_reference"]

    with principal_scope(user_b):
        assert notifications.list_notifications() == []
        with pytest.raises(NotificationError) as missing:
            notifications.mark_read(notification_id)
        assert missing.value.code == "notification_not_found"
        assert notifications.get_preferences()["credential_reference"] is None

    assert reference_a == f"cloud-study/email/smtp/{user_a.user_id}"
    assert credentials.get(reference_a) == "test-a"


def test_account_states_and_support_role_default_to_denied(tmp_path: Path) -> None:
    session_factory, identities, user_a, _user_b = _identity_fixture(tmp_path)
    support = identities.create_synthetic_identity(
        issuer=SYNTHETIC_ISSUER,
        subject="support",
        role="support_restricted",
    )
    with (
        principal_scope(support),
        session_factory() as database,
        pytest.raises(PrincipalAccessError),
    ):
        database.scalars(select(DiagnosticSession)).all()

    identities.set_account_status(
        user_id=user_a.user_id,
        new_status="suspended",
        reason_code="synthetic_9b_test",
    )
    with pytest.raises(IdentityError) as suspended:
        identities.authenticate_synthetic(SYNTHETIC_ISSUER, "user-a")
    assert suspended.value.code == "account_unavailable"


def test_synthetic_http_identity_maps_subjects_without_accepting_internal_user_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "synthetic-api.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    identities = IdentityService(session_factory)
    user_a = identities.create_synthetic_identity(issuer=SYNTHETIC_ISSUER, subject="api-a")
    identities.create_synthetic_identity(issuer=SYNTHETIC_ISSUER, subject="api-b")
    identities.create_synthetic_identity(
        issuer=SYNTHETIC_ISSUER,
        subject="api-support",
        role="support_restricted",
    )
    notifications = NotificationService(session_factory, MemoryCredentialStore())
    with principal_scope(user_a):
        notification_id = notifications.create(
            category="synthetic",
            severity="info",
            title="A only",
            message="not enumerable",
        )
    session_factory.kw["bind"].dispose()

    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("CLOUD_STUDY_SYNTHETIC_IDENTITY_ENABLED", "1")
    with TestClient(app) as client:
        assert client.get("/notifications").status_code == 401
        unknown = client.get(
            "/notifications",
            headers={
                "X-Cloud-Study-Synthetic-Issuer": SYNTHETIC_ISSUER,
                "X-Cloud-Study-Synthetic-Subject": user_a.user_id,
            },
        )
        assert unknown.status_code == 401
        a_headers = {
            "X-Cloud-Study-Synthetic-Issuer": SYNTHETIC_ISSUER,
            "X-Cloud-Study-Synthetic-Subject": "api-a",
        }
        b_headers = {
            "X-Cloud-Study-Synthetic-Issuer": SYNTHETIC_ISSUER,
            "X-Cloud-Study-Synthetic-Subject": "api-b",
        }
        assert [item["id"] for item in client.get("/notifications", headers=a_headers).json()] == [
            notification_id
        ]
        assert client.get("/notifications", headers=b_headers).json() == []
        guessed = client.post(f"/notifications/{notification_id}/read", headers=b_headers)
        assert guessed.status_code == 404
        support = client.get(
            "/notifications",
            headers={
                "X-Cloud-Study-Synthetic-Issuer": SYNTHETIC_ISSUER,
                "X-Cloud-Study-Synthetic-Subject": "api-support",
            },
        )
        assert support.status_code == 403
        assert support.json()["detail"]["code"] == "role_access_denied"


def test_0012_backfills_owner_preserves_global_data_and_roundtrips(tmp_path: Path) -> None:
    database_path = tmp_path / "backfill.db"
    config = _migration_config(database_path)
    command.upgrade(config, "0011")
    engine = create_database_engine(database_path)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO diagnostic_sessions (
                        id, skill_id, skill_version, is_preview, provider_id, model_id,
                        credential_reference, external_ai_consent, external_ai_consent_at,
                        status, current_question_id, created_at, updated_at, last_activity_at,
                        ended_at, end_reason
                    ) VALUES (
                        'legacy-session', 'algorithm', '0.2.2', 1, 'local-deterministic',
                        'diagnostic-v1', NULL, 0, NULL, 'ended', NULL,
                        '2026-09-05 01:00:00', '2026-09-05 01:01:00',
                        '2026-09-05 01:01:00', '2026-09-05 01:01:00', 'legacy-test'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO diagnostic_events (
                        session_id, event_type, payload_json, occurred_at
                    )
                    VALUES
                      ('legacy-session', 'first', '{}', '2026-09-05 01:00:00'),
                      ('legacy-session', 'second', '{}', '2026-09-05 01:01:00')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO skill_version_content_locks (
                        id, skill_id, skill_version, manifest_sha256, content_lock_sha256,
                        content_lock_json, created_at
                    ) VALUES (
                        'legacy-lock', 'algorithm', '0.2.2',
                        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                        '{}', '2026-09-05 00:00:00'
                    )
                    """
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    assert read_schema_version(database_path) == "0015"
    engine = create_database_engine(database_path)
    try:
        schema = inspect(engine)
        for table_name in EXPECTED_USER_OWNED_TABLES:
            columns = {column["name"]: column for column in schema.get_columns(table_name)}
            assert columns["user_id"]["nullable"] is False
            assert any(
                foreign_key["referred_table"] == "users"
                and foreign_key["constrained_columns"] == ["user_id"]
                for foreign_key in schema.get_foreign_keys(table_name)
            )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT user_id FROM diagnostic_sessions WHERE id = 'legacy-session'")
                ).scalar_one()
                == LEGACY_OWNER_USER_ID
            )
            assert connection.execute(
                text(
                    "SELECT event_type FROM diagnostic_events "
                    "WHERE session_id = 'legacy-session' ORDER BY occurred_at, id"
                )
            ).scalars().all() == ["first", "second"]
            lock = connection.execute(
                text(
                    "SELECT manifest_sha256, content_lock_sha256, created_at "
                    "FROM skill_version_content_locks WHERE id = 'legacy-lock'"
                )
            ).one()
            assert lock[0].startswith("a") and lock[1].startswith("b")
            assert "2026-09-05" in str(lock[2])
    finally:
        engine.dispose()

    command.downgrade(config, "0011")
    assert read_schema_version(database_path) == "0011"
    engine = create_database_engine(database_path)
    try:
        schema = inspect(engine)
        assert "user_id" not in {
            column["name"] for column in schema.get_columns("diagnostic_sessions")
        }
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT status FROM diagnostic_sessions WHERE id = 'legacy-session'")
                ).scalar_one()
                == "ended"
            )
    finally:
        engine.dispose()


def test_0012_refuses_lossy_downgrade_after_another_subject_exists(tmp_path: Path) -> None:
    database_path = tmp_path / "refuse-downgrade.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    engine = create_database_engine(database_path)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, status, created_at, updated_at) "
                    "VALUES ('11111111-1111-4111-8111-111111111111', 'active', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()
    with pytest.raises(RuntimeError, match="pre-9B snapshot"):
        command.downgrade(_migration_config(database_path), "0011")


def test_0012_renders_postgresql_candidate_sql_without_a_driver() -> None:
    output = StringIO()
    config = Config(
        str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"),
        output_buffer=output,
    )
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "apps" / "api" / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql://synthetic.invalid/cloud_study")
    command.upgrade(config, "0011:0012", sql=True)
    rendered = output.getvalue()
    assert "CREATE TABLE users" in rendered
    assert "ALTER TABLE diagnostic_sessions ADD COLUMN user_id" in rendered
    assert "pg_get_serial_sequence('user_settings', 'id')" in rendered
    assert "WHERE status = 'active'" in rendered
