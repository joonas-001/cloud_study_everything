from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.database import (
    create_database_engine,
    create_database_url,
    create_session_factory,
    read_schema_version,
    upgrade_database,
)
from cloud_study_api.identity import IdentityService
from cloud_study_api.main import app
from cloud_study_api.models import OperationsMetric, PrivacyChoice
from cloud_study_api.operations import OperationsError, OperationsService
from cloud_study_api.principals import Principal, principal_scope
from cloud_study_api.privacy import PrivacyService

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_ISSUER = "urn:cloud-study:synthetic:milestone-9e"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def _fixture(
    tmp_path: Path,
) -> tuple[sessionmaker[Session], OperationsService, Principal, Principal, Principal, Clock]:
    database_path = tmp_path / "operations.db"
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
        subject="user",
    )
    support = identities.create_synthetic_identity(
        issuer=SYNTHETIC_ISSUER,
        subject="support",
        role="support_restricted",
    )
    service = OperationsService(session_factory, REPOSITORY_ROOT, now=clock)
    return session_factory, service, owner, user, support, clock


def _migration_config(database_path: Path) -> Config:
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "apps" / "api" / "migrations"))
    config.set_main_option("sqlalchemy.url", create_database_url(database_path).replace("%", "%%"))
    return config


def _case(service: OperationsService, user: Principal) -> dict[str, object]:
    with principal_scope(user):
        return service.create_case(
            category="product_support",
            summary="合成登录问题",
            description="这是只应在明确授权后可见的合成支持正文。",
        )


def test_support_case_is_private_and_normal_access_requires_two_roles_and_consent(
    tmp_path: Path,
) -> None:
    session_factory, service, owner, user, support, _ = _fixture(tmp_path)
    support_case = _case(service, user)

    with principal_scope(support):
        with pytest.raises(RuntimeError, match="no default access"):
            service.list_cases()
        requested = service.request_support_access(
            case_id=str(support_case["id"]),
            scope="case_content",
            reason_code="diagnose_user_report",
            duration_minutes=30,
        )
        assert requested["status"] == "requested"
        with pytest.raises(OperationsError) as unapproved:
            service.view_with_grant(str(requested["id"]))
        assert unapproved.value.code == "support_access_denied"

    with principal_scope(owner):
        with pytest.raises(OperationsError) as no_consent:
            service.approve_support_access(str(requested["id"]))
        assert no_consent.value.code == "support_diagnostics_consent_required"

    privacy = PrivacyService(session_factory, REPOSITORY_ROOT)
    with principal_scope(user):
        privacy.update_choices({"support_diagnostics": True})
    with principal_scope(owner):
        approved = service.approve_support_access(str(requested["id"]))
        assert approved["status"] == "active"
    with principal_scope(support):
        viewed = service.view_with_grant(str(requested["id"]))
        assert viewed["content_visible"] is True
        assert viewed["description"] == "这是只应在明确授权后可见的合成支持正文。"

    with principal_scope(user):
        visible = service.list_visible_grants()
        assert [item["id"] for item in visible] == [requested["id"]]
        revoked = service.revoke_access(
            str(requested["id"]), reason_code="user_withdrew_support_access"
        )
        assert revoked["status"] == "revoked"
    with principal_scope(support):
        with pytest.raises(OperationsError) as revoked_access:
            service.view_with_grant(str(requested["id"]))
        assert revoked_access.value.code == "support_access_denied"


def test_access_expiry_emergency_scope_post_notice_and_append_only_audit(tmp_path: Path) -> None:
    _, service, owner, user, support, clock = _fixture(tmp_path)
    support_case = _case(service, user)
    with principal_scope(support):
        request = service.request_support_access(
            case_id=str(support_case["id"]),
            scope="ticket_metadata",
            reason_code="inspect_case_state",
            duration_minutes=1,
        )
    with principal_scope(owner):
        service.approve_support_access(str(request["id"]))
    clock.advance(timedelta(minutes=2))
    with principal_scope(support):
        with pytest.raises(OperationsError) as expired:
            service.view_with_grant(str(request["id"]))
        assert expired.value.code == "support_access_expired"

    with principal_scope(owner):
        emergency = service.create_emergency_access(
            case_id=str(support_case["id"]),
            support_user_id=support.user_id,
            incident_reference="incident.synthetic.001",
            reason_code="suspected_account_takeover",
            duration_minutes=15,
        )
        assert emergency["scope"] == "ticket_metadata"
        assert emergency["post_notice_pending"] is True
    with principal_scope(support):
        metadata = service.view_with_grant(str(emergency["id"]))
        assert metadata["content_visible"] is False
        assert "summary" not in metadata and "description" not in metadata
    with principal_scope(owner):
        notified = service.mark_emergency_notice(str(emergency["id"]))
        assert notified["post_notice_pending"] is False
        chain = service.verify_audit_chain()
        assert chain["valid"] is True
        assert chain["event_count"] >= 7

    engine = create_database_engine(tmp_path / "operations.db")
    try:
        with pytest.raises(DatabaseError, match="append-only"), engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE operations_audit_events SET reason_code = 'tampered' WHERE position = 1"
                )
            )
        with pytest.raises(DatabaseError, match="append-only"), engine.begin() as connection:
            connection.execute(text("DELETE FROM operations_audit_events WHERE position = 1"))
    finally:
        engine.dispose()


def test_kill_switches_read_only_stop_quota_and_minimized_metrics(tmp_path: Path) -> None:
    session_factory, service, owner, user, _, _ = _fixture(tmp_path)
    with principal_scope(owner):
        status = service.overview()
        assert status["real_user_ready"] is False
        assert status["cost"]["unknown_recurring_costs"] is False
        assert status["controls"]["external_ai_enabled"] is False
        controls = service.update_controls(
            {"runner_enabled": False}, reason_code="synthetic_runner_isolation_drill"
        )
        assert controls["runner_enabled"] is False

    with principal_scope(user):
        with pytest.raises(OperationsError) as runner_stopped:
            service.authorize_request("/activity-attempts/example/execute", "POST", user)
        assert runner_stopped.value.code == "runner_stopped"

    with principal_scope(owner):
        service.update_controls(
            {"service_mode": "read_only"}, reason_code="synthetic_capacity_drill"
        )
    with principal_scope(user):
        with pytest.raises(OperationsError) as read_only:
            service.authorize_request("/support/cases", "POST", user)
        assert read_only.value.code == "service_read_only"
        assert service.authorize_request("/support/cases", "GET", user) is None

    with principal_scope(owner):
        service.update_controls({"service_mode": "stopped"}, reason_code="synthetic_leak_drill")
    with principal_scope(user):
        with pytest.raises(OperationsError) as stopped:
            service.authorize_request("/learning-runs", "GET", user)
        assert stopped.value.code == "service_stopped"
        assert service.authorize_request("/operations/status", "GET", user) is None

    with principal_scope(owner):
        service.update_controls({"service_mode": "normal"}, reason_code="synthetic_drill_closed")
    with principal_scope(user):
        for _ in range(3):
            reservation = service.authorize_request("/privacy/exports", "POST", user)
            assert reservation == "export"
            service.release_request(reservation, user, status_code=200)
        with pytest.raises(OperationsError) as exhausted:
            service.authorize_request("/privacy/exports", "POST", user)
        assert exhausted.value.code == "quota_exceeded"

    with principal_scope(owner), session_factory() as database:
        metrics = database.scalars(select(OperationsMetric)).all()
        assert metrics
        serialized = "\n".join(
            f"{row.principal_hash}|{row.action}|{row.outcome}|{row.reason_code}" for row in metrics
        )
        assert user.user_id not in serialized
        assert "合成登录问题" not in serialized
        assert all(len(row.principal_hash) == 64 for row in metrics)
    with principal_scope(user), session_factory() as database:
        choice = database.scalar(
            select(PrivacyChoice).where(PrivacyChoice.purpose == "support_diagnostics")
        )
        assert choice is None


def test_synthetic_api_support_exception_and_control_middleware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(tmp_path / "operations-api.db"))
    monkeypatch.setenv("CLOUD_STUDY_SYNTHETIC_IDENTITY_ENABLED", "1")
    monkeypatch.setenv("CLOUD_STUDY_AUTH_MODE", "legacy_owner")
    with TestClient(app) as client:
        identities: IdentityService = app.state.identity_service
        owner = identities.create_synthetic_identity(
            issuer=SYNTHETIC_ISSUER, subject="api-owner", role="owner_operator"
        )
        user = identities.create_synthetic_identity(issuer=SYNTHETIC_ISSUER, subject="api-user")
        identities.create_synthetic_identity(
            issuer=SYNTHETIC_ISSUER,
            subject="api-support",
            role="support_restricted",
        )
        owner_headers = {
            "X-Cloud-Study-Synthetic-Issuer": SYNTHETIC_ISSUER,
            "X-Cloud-Study-Synthetic-Subject": "api-owner",
        }
        user_headers = {
            "X-Cloud-Study-Synthetic-Issuer": SYNTHETIC_ISSUER,
            "X-Cloud-Study-Synthetic-Subject": "api-user",
        }
        support_headers = {
            "X-Cloud-Study-Synthetic-Issuer": SYNTHETIC_ISSUER,
            "X-Cloud-Study-Synthetic-Subject": "api-support",
        }
        created = client.post(
            "/support/cases",
            headers=user_headers,
            json={
                "category": "security_vulnerability",
                "summary": "合成安全报告",
                "description": "用于 API 授权边界验证的合成正文。",
            },
        )
        assert created.status_code == 201
        denied = client.get("/support/cases", headers=support_headers)
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "role_access_denied"
        requested = client.post(
            "/support/access-requests",
            headers=support_headers,
            json={
                "case_id": created.json()["id"],
                "scope": "ticket_metadata",
                "reason_code": "triage_security_report",
                "duration_minutes": 15,
            },
        )
        assert requested.status_code == 201
        approved = client.post(
            f"/operations/support/access-requests/{requested.json()['id']}/approve",
            headers=owner_headers,
        )
        assert approved.status_code == 200
        viewed = client.post(
            f"/support/access-requests/{requested.json()['id']}/view",
            headers=support_headers,
        )
        assert viewed.status_code == 200
        assert viewed.json()["content_visible"] is False
        assert "summary" not in viewed.json()

        read_only = client.put(
            "/operations/controls",
            headers=owner_headers,
            json={"service_mode": "read_only", "reason_code": "api_read_only_drill"},
        )
        assert read_only.status_code == 200
        blocked = client.post(
            "/support/cases",
            headers=user_headers,
            json={
                "category": "product_support",
                "summary": "应被只读阻断",
                "description": "这条合成请求不应被写入。",
            },
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "service_read_only"
        restored = client.put(
            "/operations/controls",
            headers=owner_headers,
            json={"service_mode": "normal", "reason_code": "api_read_only_drill_closed"},
        )
        assert restored.status_code == 200
        audit = client.get("/operations/audit/verify", headers=owner_headers)
        assert audit.status_code == 200 and audit.json()["valid"] is True
        assert owner.user_id != user.user_id


def test_0015_roundtrip_and_postgresql_sql_include_rls_and_immutable_audit(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    config = _migration_config(database_path)
    command.upgrade(config, "0014")
    command.upgrade(config, "0015")
    assert read_schema_version(database_path) == "0015"
    engine = create_database_engine(database_path)
    try:
        schema = inspect(engine)
        assert {
            "support_cases",
            "support_access_grants",
            "operations_controls",
            "operations_quota_buckets",
            "operations_audit_events",
            "operations_metrics",
        }.issubset(schema.get_table_names())
        with engine.connect() as connection:
            triggers = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                        "AND tbl_name = 'operations_audit_events'"
                    )
                ).all()
            }
        assert triggers == {
            "operations_audit_events_no_update",
            "operations_audit_events_no_delete",
        }
    finally:
        engine.dispose()
    command.downgrade(config, "0014")
    assert read_schema_version(database_path) == "0014"
    command.upgrade(config, "0015")
    assert read_schema_version(database_path) == "0015"

    output = StringIO()
    postgres = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"), output_buffer=output)
    postgres.set_main_option(
        "script_location", str(REPOSITORY_ROOT / "apps" / "api" / "migrations")
    )
    postgres.set_main_option("sqlalchemy.url", "postgresql://synthetic.invalid/cloud_study")
    command.upgrade(postgres, "0014:0015", sql=True)
    rendered = output.getvalue()
    assert 'ALTER TABLE "support_cases" FORCE ROW LEVEL SECURITY' in rendered
    assert "cloud_study_operations_audit_immutable" in rendered


def test_policy_and_tabletop_record_cover_every_required_incident_without_real_user_claims() -> (
    None
):
    policy = json.loads(
        (REPOSITORY_ROOT / "governance" / "operations" / "milestone-9e-policy.json").read_text(
            encoding="utf-8"
        )
    )
    record = json.loads(
        (REPOSITORY_ROOT / "governance" / "operations" / "milestone-9e-drills.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "security_vulnerability",
        "dependency_or_image_update",
        "credential_rotation",
        "identity_provider_outage",
        "cross_user_disclosure",
        "runner_isolation_failure",
        "backup_failure",
        "capacity_exhaustion",
        "supplier_exit",
    }
    assert policy["real_user_ready"] is False
    assert policy["cost"]["automatic_recharge"] is False
    assert policy["cost"]["automatic_scaling"] is False
    assert {item["incident"] for item in record["drills"]} == expected
    assert all(
        item["owner"] == "owner_operator" and item["result"] == "passed"
        for item in record["drills"]
    )
    assert "real Clerk" in " ".join(record["limitations"])
