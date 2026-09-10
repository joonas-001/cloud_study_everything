from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.authentication import (
    AuthenticationError,
    AuthenticationService,
    DeterministicOidcAdapter,
    VerifiedOidcClaims,
)
from cloud_study_api.config import AuthenticationSettings
from cloud_study_api.database import (
    create_database_engine,
    create_database_url,
    create_session_factory,
    upgrade_database,
)
from cloud_study_api.main import app
from cloud_study_api.models import (
    AccountInvitation,
    ApplicationSession,
    AuthSecurityEvent,
    ExternalIdentity,
    InternalUser,
    OidcLoginTransaction,
)
from cloud_study_api.principals import LEGACY_OWNER_USER_ID

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ISSUER = "https://synthetic-identity.invalid"
AUDIENCE = "cloud-study-synthetic-client"
ORIGIN = "https://app.synthetic.invalid"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def _settings() -> AuthenticationSettings:
    return AuthenticationSettings(
        mode="synthetic_oidc",
        issuer=ISSUER,
        audience=AUDIENCE,
        authorization_endpoint=f"{ISSUER}/authorize",
        redirect_uri=f"{ORIGIN}/api/auth/callback",
        allowed_origin=ORIGIN,
        server_secret=None,
    )


def _fixture(
    tmp_path: Path,
) -> tuple[
    sessionmaker[Session],
    AuthenticationService,
    DeterministicOidcAdapter,
    Clock,
]:
    database_path = tmp_path / "authentication.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    with session_factory() as database:
        database.add(
            ExternalIdentity(
                id=str(uuid4()),
                user_id=LEGACY_OWNER_USER_ID,
                issuer=ISSUER,
                subject="synthetic-owner",
                created_at=datetime.now(UTC),
            )
        )
        database.commit()
    clock = Clock()
    adapter = DeterministicOidcAdapter(_settings())
    service = AuthenticationService(session_factory, _settings(), adapter, now=clock)
    return session_factory, service, adapter, clock


def _query(start_url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(start_url).query).items()}


def _claims(
    query: dict[str, str],
    clock: Clock,
    *,
    subject: str,
) -> VerifiedOidcClaims:
    return VerifiedOidcClaims(
        issuer=ISSUER,
        audience=(AUDIENCE,),
        subject=subject,
        nonce=query["nonce"],
        issued_at=clock(),
        expires_at=clock() + timedelta(minutes=5),
        authenticated_at=clock(),
        authentication_methods=("pwd", "mfa"),
    )


def _login(
    service: AuthenticationService,
    adapter: DeterministicOidcAdapter,
    clock: Clock,
    *,
    subject: str,
    invitation_token: str | None = None,
    prior_session_token: str | None = None,
):
    start = service.begin_login(
        invitation_token=invitation_token,
        prior_session_token=prior_session_token,
        rate_limit_identifier=f"login-{uuid4()}",
    )
    query = _query(start.authorization_url)
    code = adapter.issue_code(state=query["state"], claims=_claims(query, clock, subject=subject))
    return service.complete_login(
        code=code,
        state=query["state"],
        rate_limit_identifier=f"callback-{uuid4()}",
    )


def test_oidc_invitation_pkce_session_rotation_and_all_device_revocation(tmp_path: Path) -> None:
    session_factory, service, adapter, clock = _fixture(tmp_path)
    owner = _login(service, adapter, clock, subject="synthetic-owner")

    with session_factory() as database:
        stored_session = database.get(ApplicationSession, owner.session_id)
        transaction = database.scalars(select(OidcLoginTransaction)).one()
        assert stored_session is not None
        assert stored_session.token_sha256 != owner.token
        assert owner.token not in transaction.encrypted_pkce_verifier

    invitation = service.create_invitation(
        raw_session_token=owner.token,
        role="user",
        expires_in_minutes=60,
    )
    user = _login(
        service,
        adapter,
        clock,
        subject="synthetic-user",
        invitation_token=invitation.token,
    )
    with session_factory() as database:
        stored_invitation = database.get(AccountInvitation, invitation.invitation_id)
        assert stored_invitation is not None
        assert stored_invitation.token_sha256 != invitation.token
        assert stored_invitation.accepted_by_user_id == user.principal.user_id
        assert database.get(InternalUser, user.principal.user_id) is not None

    with pytest.raises(AuthenticationError) as reused_invitation:
        service.begin_login(
            invitation_token=invitation.token,
            prior_session_token=None,
            rate_limit_identifier="reused-invitation",
        )
    assert reused_invitation.value.code == "invitation_unavailable"

    rotated = _login(
        service,
        adapter,
        clock,
        subject="synthetic-owner",
        prior_session_token=owner.token,
    )
    with pytest.raises(AuthenticationError):
        service.authenticate_session(owner.token)
    service.authenticate_session(rotated.token)

    second_device = _login(service, adapter, clock, subject="synthetic-owner")
    service.logout(rotated.token, all_devices=True)
    with pytest.raises(AuthenticationError):
        service.authenticate_session(rotated.token)
    with pytest.raises(AuthenticationError):
        service.authenticate_session(second_device.token)


def test_concurrent_invitation_callbacks_create_only_one_account(tmp_path: Path) -> None:
    session_factory, service, adapter, clock = _fixture(tmp_path)
    owner = _login(service, adapter, clock, subject="synthetic-owner")
    invitation = service.create_invitation(
        raw_session_token=owner.token,
        role="user",
        expires_in_minutes=60,
    )
    callbacks: list[tuple[str, str]] = []
    for subject in ("concurrent-user-a", "concurrent-user-b"):
        started = service.begin_login(
            invitation_token=invitation.token,
            prior_session_token=None,
            rate_limit_identifier=f"start-{subject}",
        )
        query = _query(started.authorization_url)
        callbacks.append(
            (
                adapter.issue_code(
                    state=query["state"], claims=_claims(query, clock, subject=subject)
                ),
                query["state"],
            )
        )

    barrier = Barrier(2)

    def finish(callback: tuple[str, str]):
        code, state = callback
        barrier.wait()
        try:
            return service.complete_login(
                code=code,
                state=state,
                rate_limit_identifier=f"callback-{state}",
            )
        except AuthenticationError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(finish, callbacks))

    assert sum(not isinstance(result, AuthenticationError) for result in results) == 1
    errors = [result for result in results if isinstance(result, AuthenticationError)]
    assert len(errors) == 1
    assert errors[0].code in {"invitation_unavailable", "identity_binding_conflict"}
    with session_factory() as database:
        accepted = database.get(AccountInvitation, invitation.invitation_id)
        identities = database.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.subject.in_(("concurrent-user-a", "concurrent-user-b"))
            )
        ).all()
        assert accepted is not None
        assert accepted.accepted_by_user_id is not None
        assert len(identities) == 1
        assert identities[0].user_id == accepted.accepted_by_user_id


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda claims: replace(claims, issuer="https://wrong.invalid"), "oidc_claims_rejected"),
        (lambda claims: replace(claims, audience=("wrong",)), "oidc_claims_rejected"),
        (lambda claims: replace(claims, nonce="wrong"), "oidc_claims_rejected"),
        (
            lambda claims: replace(claims, expires_at=claims.issued_at - timedelta(seconds=1)),
            "oidc_claims_rejected",
        ),
        (lambda claims: replace(claims, authentication_methods=("pwd",)), "oidc_claims_rejected"),
    ],
)
def test_oidc_claim_confusion_and_missing_mfa_are_rejected(
    tmp_path: Path,
    mutation,
    expected_code: str,
) -> None:
    _session_factory, service, adapter, clock = _fixture(tmp_path)
    start = service.begin_login(
        invitation_token=None,
        prior_session_token=None,
        rate_limit_identifier="claims-test",
    )
    query = _query(start.authorization_url)
    claims = mutation(_claims(query, clock, subject="synthetic-owner"))
    code = adapter.issue_code(state=query["state"], claims=claims)
    with pytest.raises(AuthenticationError) as rejected:
        service.complete_login(
            code=code,
            state=query["state"],
            rate_limit_identifier="claims-callback",
        )
    assert rejected.value.code == expected_code


def test_state_code_pkce_replay_and_rate_limits_fail_closed(tmp_path: Path) -> None:
    session_factory, service, adapter, clock = _fixture(tmp_path)
    start = service.begin_login(
        invitation_token=None,
        prior_session_token=None,
        rate_limit_identifier="pkce-start",
    )
    query = _query(start.authorization_url)
    code = adapter.issue_code(
        state=query["state"], claims=_claims(query, clock, subject="synthetic-owner")
    )
    with session_factory() as database:
        transaction = database.scalars(select(OidcLoginTransaction)).one()
        transaction.encrypted_pkce_verifier = service._cipher.encrypt(b"wrong-verifier").decode(
            "ascii"
        )
        database.commit()
    with pytest.raises(AuthenticationError) as pkce:
        service.complete_login(
            code=code,
            state=query["state"],
            rate_limit_identifier="pkce-callback",
        )
    assert pkce.value.code == "pkce_verification_failed"
    with pytest.raises(AuthenticationError) as replay:
        service.complete_login(
            code=code,
            state=query["state"],
            rate_limit_identifier="pkce-replay",
        )
    assert replay.value.code == "invalid_login_state"

    for _ in range(10):
        service.begin_login(
            invitation_token=None,
            prior_session_token=None,
            rate_limit_identifier="one-client",
        )
    with pytest.raises(AuthenticationError) as limited:
        service.begin_login(
            invitation_token=None,
            prior_session_token=None,
            rate_limit_identifier="one-client",
        )
    assert limited.value.code == "rate_limit_exceeded"


def test_deletion_waiting_session_and_operator_recovery_are_bounded(tmp_path: Path) -> None:
    _session_factory, service, adapter, clock = _fixture(tmp_path)
    owner = _login(service, adapter, clock, subject="synthetic-owner")
    invitation = service.create_invitation(
        raw_session_token=owner.token,
        role="user",
        expires_in_minutes=60,
    )
    user = _login(
        service,
        adapter,
        clock,
        subject="recoverable-user",
        invitation_token=invitation.token,
    )
    service.request_deletion(user.token)
    with pytest.raises(AuthenticationError):
        service.authenticate_session(user.token)

    cancellation_session = _login(service, adapter, clock, subject="recoverable-user")
    assert cancellation_session.principal.account_status == "deletion_pending"
    service.cancel_deletion(raw_session_token=cancellation_session.token)
    assert (
        service.authenticate_session(cancellation_session.token).principal.account_status
        == "active"
    )

    service.set_account_availability(
        raw_session_token=owner.token,
        target_user_id=user.principal.user_id,
        new_status="suspended",
    )
    with pytest.raises(AuthenticationError):
        service.authenticate_session(cancellation_session.token)
    with pytest.raises(AuthenticationError) as suspended_login:
        _login(service, adapter, clock, subject="recoverable-user")
    assert suspended_login.value.code == "account_unavailable"
    service.set_account_availability(
        raw_session_token=owner.token,
        target_user_id=user.principal.user_id,
        new_status="active",
    )
    _login(service, adapter, clock, subject="recoverable-user")
    with pytest.raises(AuthenticationError) as self_lockout:
        service.set_account_availability(
            raw_session_token=owner.token,
            target_user_id=owner.principal.user_id,
            new_status="suspended",
        )
    assert self_lockout.value.code == "owner_self_lockout_denied"


def test_session_idle_absolute_expiry_and_audit_minimization(tmp_path: Path) -> None:
    session_factory, service, adapter, clock = _fixture(tmp_path)
    session = _login(service, adapter, clock, subject="synthetic-owner")
    clock.advance(timedelta(minutes=29))
    refreshed = service.authenticate_session(session.token)
    assert refreshed.idle_expires_at == clock() + timedelta(minutes=30)
    clock.advance(timedelta(minutes=31))
    with pytest.raises(AuthenticationError) as idle_expired:
        service.authenticate_session(session.token)
    assert idle_expired.value.code == "session_expired"

    with session_factory() as database:
        events = database.scalars(select(AuthSecurityEvent)).all()
        serialized = " ".join(
            f"{event.event_type} {event.outcome} {event.reason_code}" for event in events
        )
    assert "synthetic-owner" not in serialized
    assert session.token not in serialized


def test_http_cookie_origin_and_unauthenticated_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "auth-http.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    with session_factory() as database:
        database.add(
            ExternalIdentity(
                id=str(uuid4()),
                user_id=LEGACY_OWNER_USER_ID,
                issuer=ISSUER,
                subject="http-owner",
                created_at=datetime.now(UTC),
            )
        )
        database.commit()
    session_factory.kw["bind"].dispose()

    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("CLOUD_STUDY_AUTH_MODE", "synthetic_oidc")
    monkeypatch.setenv("CLOUD_STUDY_AUTH_ALLOWED_ORIGIN", ORIGIN)
    monkeypatch.setenv("CLOUD_STUDY_OIDC_REDIRECT_URI", f"{ORIGIN}/api/auth/callback")
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/notifications").status_code == 401
        assert client.post("/auth/login/start", json={}).status_code == 403
        started = client.post("/auth/login/start", json={}, headers={"Origin": ORIGIN})
        assert started.status_code == 200
        query = _query(started.json()["authorization_url"])
        adapter = app.state.oidc_adapter
        code = adapter.issue_code(
            state=query["state"],
            claims=VerifiedOidcClaims(
                issuer=ISSUER,
                audience=(AUDIENCE,),
                subject="http-owner",
                nonce=query["nonce"],
                issued_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
                authenticated_at=datetime.now(UTC),
                authentication_methods=("pwd", "mfa"),
            ),
        )
        callback = client.get("/auth/callback", params={"code": code, "state": query["state"]})
        assert callback.status_code == 200
        cookie = callback.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=strict" in cookie
        assert client.get("/notifications").status_code == 200
        csrf = client.post("/notifications/unknown/read")
        assert csrf.status_code == 403
        assert csrf.json()["detail"]["code"] == "csrf_origin_rejected"
        current = client.get("/auth/session").json()
        assert current["authenticated"] is True
        assert current["role"] == "owner_operator"
        logged_out = client.post("/auth/logout-all", headers={"Origin": ORIGIN})
        assert logged_out.status_code == 200
        assert client.get("/auth/session").json()["authenticated"] is False
        assert client.get("/notifications").status_code == 401


def test_0013_migration_roundtrip(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "apps" / "api" / "migrations"))
    config.set_main_option("sqlalchemy.url", create_database_url(database_path).replace("%", "%%"))
    command.upgrade(config, "0013")
    engine = create_database_engine(database_path)
    assert "application_sessions" in inspect(engine).get_table_names()
    engine.dispose()
    command.downgrade(config, "0012")
    engine = create_database_engine(database_path)
    assert "application_sessions" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(config, "0013")
    engine = create_database_engine(database_path)
    assert "auth_security_events" in inspect(engine).get_table_names()
    engine.dispose()
