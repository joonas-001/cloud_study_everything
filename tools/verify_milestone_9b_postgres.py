from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import psycopg
from cloud_study_api.database import (
    create_postgresql_engine,
    create_postgresql_session_factory,
    create_session_factory,
    upgrade_database,
)
from cloud_study_api.identity import IdentityService
from cloud_study_api.models import (
    DiagnosticSession,
    Notification,
    NotificationPreference,
    UserSettings,
    utc_now,
)
from cloud_study_api.postgresql_migration import migrate_sqlite_to_postgresql
from cloud_study_api.principals import Principal, principal_scope
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import CursorResult


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
        end_reason="synthetic_9b_postgresql_validation",
    )


def _build_source(
    database_path: Path, repository_root: Path
) -> tuple[Principal, Principal]:
    upgrade_database(database_path, repository_root)
    session_factory = create_session_factory(database_path)
    identities = IdentityService(session_factory)
    user_a = identities.create_synthetic_identity(
        issuer="urn:cloud-study:synthetic:postgres-validation",
        subject="user-a",
    )
    user_b = identities.create_synthetic_identity(
        issuer="urn:cloud-study:synthetic:postgres-validation",
        subject="user-b",
    )
    for principal, record_id in ((user_a, "pg-user-a"), (user_b, "pg-user-b")):
        with principal_scope(principal), session_factory() as database:
            database.add(_diagnostic(record_id))
            database.commit()
    with principal_scope(user_a), session_factory() as database:
        database.add(
            Notification(
                id="pg-notification-a",
                category="synthetic",
                severity="info",
                title="A only",
                message="synthetic PostgreSQL RLS probe",
                related_type=None,
                related_id=None,
                deduplication_key="pg-a-only",
                created_at=utc_now(),
                read_at=None,
                archived_at=None,
            )
        )
        database.commit()
    session_factory.kw["bind"].dispose()
    return user_a, user_b


def verify(
    *,
    repository_root: Path,
    owner_url: str,
    app_url: str,
) -> dict[str, object]:
    with TemporaryDirectory(prefix="cloud-study-9b-") as temporary_directory:
        source_path = Path(temporary_directory) / "synthetic-source.sqlite3"
        user_a, user_b = _build_source(source_path, repository_root)
        migration = migrate_sqlite_to_postgresql(
            source_database=source_path,
            target_database_url=owner_url,
        )

        app_factory = create_postgresql_session_factory(app_url)
        with principal_scope(user_a), app_factory() as database:
            visible_a = database.scalars(
                select(DiagnosticSession.id).order_by(DiagnosticSession.id)
            ).all()
            assert visible_a == ["pg-user-a"]
            assert database.scalar(select(func.count()).select_from(Notification)) == 1
        with principal_scope(user_b), app_factory() as database:
            visible_b = database.scalars(
                select(DiagnosticSession.id).order_by(DiagnosticSession.id)
            ).all()
            assert visible_b == ["pg-user-b"]
            assert database.get(Notification, "pg-notification-a") is None
            changed = cast(
                CursorResult[Any],
                database.execute(
                    update(Notification)
                    .where(Notification.id == "pg-notification-a")
                    .values(title="forged")
                ),
            )
            removed = cast(
                CursorResult[Any],
                database.execute(
                    delete(Notification).where(Notification.id == "pg-notification-a")
                ),
            )
            changed_rows = changed.rowcount
            removed_rows = removed.rowcount
            assert changed_rows == 0
            assert removed_rows == 0
            database.rollback()
        user_c = IdentityService(app_factory).create_synthetic_identity(
            issuer="urn:cloud-study:synthetic:postgres-validation",
            subject="user-c-after-copy",
        )
        with principal_scope(user_c), app_factory() as database:
            user_c_settings_id = database.scalar(select(UserSettings.id))
            user_c_notification_preference_id = database.scalar(
                select(NotificationPreference.id)
            )
            assert user_c_settings_id is not None and user_c_settings_id > 3
            assert (
                user_c_notification_preference_id is not None
                and user_c_notification_preference_id > 3
            )
        app_factory.kw["bind"].dispose()

        psycopg_url = app_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with (
            psycopg.connect(psycopg_url) as psycopg_connection,
            psycopg_connection.cursor() as cursor,
        ):
            cursor.execute("SELECT COUNT(*) FROM notifications")
            assert cursor.fetchone() == (0,)
            denied_without_principal = False
            try:
                cursor.execute(
                    """
                    INSERT INTO notifications (
                        id, user_id, category, severity, title, message, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    """,
                    (
                        "pg-forged-without-principal",
                        user_a.user_id,
                        "synthetic",
                        "info",
                        "forged",
                        "must be rejected by RLS",
                    ),
                )
            except psycopg.errors.InsufficientPrivilege:
                denied_without_principal = True
                psycopg_connection.rollback()
            assert denied_without_principal

        owner_engine = create_postgresql_engine(owner_url)
        try:
            with owner_engine.connect() as owner_connection:
                policy_count = owner_connection.execute(
                    text(
                        "SELECT COUNT(*) FROM pg_policies "
                        "WHERE schemaname = 'public' AND policyname LIKE 'pl_%_user_isolation'"
                    )
                ).scalar_one()
                role = owner_connection.execute(
                    text(
                        "SELECT rolsuper, rolcreatedb, rolcreaterole "
                        "FROM pg_roles WHERE rolname = 'cloud_study_app'"
                    )
                ).one()
            assert policy_count == 40
            assert role == (False, False, False)
        finally:
            owner_engine.dispose()

        return {
            "postgresql_version": "17.6",
            "alembic_revision": migration["target_revision"],
            "migrated_tables": migration["table_count"],
            "migrated_rows": migration["row_count"],
            "source_unchanged": migration["source_unchanged"],
            "target_digest_verified": migration["target_verified"],
            "rls_policy_count": policy_count,
            "application_role_superuser": role[0],
            "application_role_create_database": role[1],
            "application_role_create_role": role[2],
            "user_a_visible_diagnostics": visible_a,
            "user_b_visible_diagnostics": visible_b,
            "cross_user_update_rows": changed_rows,
            "cross_user_delete_rows": removed_rows,
            "post_copy_user_settings_id": user_c_settings_id,
            "post_copy_notification_preference_id": user_c_notification_preference_id,
            "missing_principal_read_rows": 0,
            "missing_principal_write": "denied",
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-url", required=True)
    parser.add_argument("--app-url", required=True)
    arguments = parser.parse_args()
    report = verify(
        repository_root=Path(__file__).resolve().parents[1],
        owner_url=arguments.owner_url,
        app_url=arguments.app_url,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
