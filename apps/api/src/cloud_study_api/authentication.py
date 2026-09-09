from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from urllib.parse import urlencode
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.config import AuthenticationSettings
from cloud_study_api.models import (
    AccountInvitation,
    AccountStateEvent,
    ApplicationSession,
    AuthRateLimitBucket,
    AuthSecurityEvent,
    ExternalIdentity,
    InternalUser,
    NotificationPreference,
    OidcLoginTransaction,
    UserRoleAssignment,
    UserSettings,
    utc_now,
)
from cloud_study_api.principals import Principal, UserRole, principal_scope


class AuthenticationError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class VerifiedOidcClaims:
    issuer: str
    audience: tuple[str, ...]
    subject: str
    nonce: str
    issued_at: datetime
    expires_at: datetime
    authenticated_at: datetime
    authentication_methods: tuple[str, ...]


class OidcAdapter(Protocol):
    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str: ...

    def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> VerifiedOidcClaims: ...


class DeterministicOidcAdapter:
    """Local-only OIDC simulator that still enforces code and PKCE one-time use."""

    def __init__(self, settings: AuthenticationSettings) -> None:
        self._settings = settings
        self._challenges_by_state: dict[str, str] = {}
        self._codes: dict[str, tuple[VerifiedOidcClaims, str]] = {}

    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str:
        self._challenges_by_state[state] = code_challenge
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.audience,
                "redirect_uri": redirect_uri,
                "scope": "openid",
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self._settings.authorization_endpoint}?{query}"

    def issue_code(self, *, state: str, claims: VerifiedOidcClaims) -> str:
        challenge = self._challenges_by_state.pop(state, None)
        if challenge is None:
            raise ValueError("unknown synthetic authorization state")
        code = secrets.token_urlsafe(32)
        self._codes[code] = (claims, challenge)
        return code

    def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> VerifiedOidcClaims:
        del redirect_uri
        issued = self._codes.pop(code, None)
        if issued is None:
            raise AuthenticationError(
                401, "invalid_authorization_code", "Login could not be completed."
            )
        claims, expected_challenge = issued
        if not hmac.compare_digest(expected_challenge, _pkce_challenge(code_verifier)):
            raise AuthenticationError(
                401, "pkce_verification_failed", "Login could not be completed."
            )
        return claims


class ManagedOidcNotActivatedAdapter:
    """Fail-closed boundary until a real Clerk application is separately authorized."""

    def authorization_url(self, **_kwargs: str) -> str:
        raise AuthenticationError(
            503,
            "managed_identity_not_activated",
            "Managed identity is not activated for this candidate.",
        )

    def exchange_authorization_code(self, **_kwargs: str) -> VerifiedOidcClaims:
        raise AuthenticationError(
            503,
            "managed_identity_not_activated",
            "Managed identity is not activated for this candidate.",
        )


@dataclass(frozen=True, slots=True)
class AuthenticationStart:
    authorization_url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SessionResult:
    token: str
    session_id: str
    principal: Principal
    idle_expires_at: datetime
    absolute_expires_at: datetime
    authenticated_at: datetime
    mfa_authenticated: bool


@dataclass(frozen=True, slots=True)
class InvitationResult:
    invitation_id: str
    token: str
    role: UserRole
    expires_at: datetime


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AuthenticationService:
    LOGIN_TRANSACTION_TTL = timedelta(minutes=10)
    REAUTH_MAX_AGE = timedelta(minutes=5)
    INVITATION_MAX_TTL = timedelta(days=7)
    DELETION_CANCELLATION_WINDOW = timedelta(days=7)

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: AuthenticationSettings,
        adapter: OidcAdapter,
        *,
        now: Callable[[], datetime] = utc_now,
        encryption_key: bytes | None = None,
        rate_limit_key: bytes | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.settings = settings
        self.adapter = adapter
        self._now = now
        derived_encryption_key = (
            base64.urlsafe_b64encode(hashlib.sha256(settings.server_secret + b":fernet").digest())
            if settings.server_secret is not None
            else Fernet.generate_key()
        )
        self._cipher = Fernet(encryption_key or derived_encryption_key)
        self._rate_limit_key = rate_limit_key or (
            hmac.new(settings.server_secret, b"rate-limit", hashlib.sha256).digest()
            if settings.server_secret is not None
            else secrets.token_bytes(32)
        )

    def begin_login(
        self,
        *,
        invitation_token: str | None,
        prior_session_token: str | None,
        rate_limit_identifier: str,
    ) -> AuthenticationStart:
        self._enforce_rate_limit("login", rate_limit_identifier, limit=10)
        now = self._now()
        invitation_id: str | None = None
        prior_session_id: str | None = None
        with self._session_factory() as database:
            if invitation_token:
                invitation = database.scalar(
                    select(AccountInvitation).where(
                        AccountInvitation.token_sha256 == _sha256(invitation_token)
                    )
                )
                if (
                    invitation is None
                    or invitation.revoked_at is not None
                    or invitation.accepted_at is not None
                    or _aware(invitation.expires_at) <= now
                ):
                    raise AuthenticationError(
                        400, "invitation_unavailable", "The invitation is unavailable."
                    )
                invitation_id = invitation.id
            if prior_session_token:
                prior = self._find_session(database, prior_session_token)
                if prior is not None and prior.revoked_at is None:
                    prior_session_id = prior.id
            state = secrets.token_urlsafe(32)
            nonce = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(64)
            transaction = OidcLoginTransaction(
                id=str(uuid4()),
                state_sha256=_sha256(state),
                nonce_sha256=_sha256(nonce),
                encrypted_pkce_verifier=self._cipher.encrypt(verifier.encode("ascii")).decode(
                    "ascii"
                ),
                invitation_id=invitation_id,
                prior_session_id=prior_session_id,
                created_at=now,
                expires_at=now + self.LOGIN_TRANSACTION_TTL,
            )
            database.add(transaction)
            database.commit()
        authorization_url = self.adapter.authorization_url(
            state=state,
            nonce=nonce,
            code_challenge=_pkce_challenge(verifier),
            redirect_uri=self.settings.redirect_uri,
        )
        self._audit("login_started", "accepted", "authorization_started", None)
        return AuthenticationStart(
            authorization_url=authorization_url,
            expires_at=now + self.LOGIN_TRANSACTION_TTL,
        )

    def complete_login(
        self,
        *,
        code: str,
        state: str,
        rate_limit_identifier: str,
    ) -> SessionResult:
        self._enforce_rate_limit("callback", rate_limit_identifier, limit=15)
        if not code or len(code) > 2048 or not state or len(state) > 512:
            raise AuthenticationError(
                401, "invalid_login_callback", "Login could not be completed."
            )
        now = self._now()
        with self._session_factory() as database:
            transaction = database.scalar(
                select(OidcLoginTransaction).where(
                    OidcLoginTransaction.state_sha256 == _sha256(state)
                )
            )
            if (
                transaction is None
                or transaction.consumed_at is not None
                or _aware(transaction.expires_at) <= now
            ):
                self._audit("login_callback", "denied", "state_invalid_or_replayed", None)
                raise AuthenticationError(
                    401, "invalid_login_state", "Login could not be completed."
                )
            claimed = cast(
                CursorResult[Any],
                database.execute(
                    update(OidcLoginTransaction)
                    .where(
                        OidcLoginTransaction.id == transaction.id,
                        OidcLoginTransaction.consumed_at.is_(None),
                    )
                    .values(consumed_at=now)
                ),
            )
            if claimed.rowcount != 1:
                database.rollback()
                raise AuthenticationError(
                    401, "invalid_login_state", "Login could not be completed."
                )
            database.commit()
            try:
                verifier = self._cipher.decrypt(
                    transaction.encrypted_pkce_verifier.encode("ascii")
                ).decode("ascii")
            except InvalidToken as error:
                raise AuthenticationError(
                    401, "login_transaction_unavailable", "Login could not be completed."
                ) from error
        claims = self.adapter.exchange_authorization_code(
            code=code,
            code_verifier=verifier,
            redirect_uri=self.settings.redirect_uri,
        )
        self._validate_claims(claims, transaction.nonce_sha256, now)
        principal, new_user = self._resolve_or_create_principal(transaction, claims, now)
        raw_token = secrets.token_urlsafe(48)
        session_id = str(uuid4())
        idle_expires_at = now + timedelta(minutes=self.settings.idle_minutes)
        absolute_expires_at = now + timedelta(hours=self.settings.absolute_hours)
        with self._session_factory() as database:
            if transaction.prior_session_id:
                database.execute(
                    update(ApplicationSession)
                    .where(
                        ApplicationSession.id == transaction.prior_session_id,
                        ApplicationSession.revoked_at.is_(None),
                    )
                    .values(revoked_at=now, revocation_reason="login_session_rotated")
                )
            database.add(
                ApplicationSession(
                    id=session_id,
                    user_id=principal.user_id,
                    token_sha256=_sha256(raw_token),
                    created_at=now,
                    last_seen_at=now,
                    idle_expires_at=idle_expires_at,
                    absolute_expires_at=absolute_expires_at,
                    authenticated_at=_aware(claims.authenticated_at),
                    mfa_authenticated=True,
                )
            )
            database.commit()
        if new_user:
            self._initialize_user_defaults(principal, now)
        self._audit("login_completed", "accepted", "oidc_mfa_verified", principal.user_id)
        return SessionResult(
            token=raw_token,
            session_id=session_id,
            principal=principal,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            authenticated_at=_aware(claims.authenticated_at),
            mfa_authenticated=True,
        )

    def authenticate_session(
        self,
        raw_token: str,
        *,
        slide: bool = True,
        allow_deletion_pending: bool = False,
    ) -> SessionResult:
        if not raw_token or len(raw_token) > 512:
            raise AuthenticationError(401, "authentication_required", "Authentication is required.")
        now = self._now()
        with self._session_factory() as database:
            session = self._find_session(database, raw_token)
            if session is None or session.revoked_at is not None:
                raise AuthenticationError(
                    401, "authentication_required", "Authentication is required."
                )
            if _aware(session.absolute_expires_at) <= now or _aware(session.idle_expires_at) <= now:
                if session.revoked_at is None:
                    session.revoked_at = now
                    session.revocation_reason = "session_expired"
                    database.commit()
                raise AuthenticationError(401, "session_expired", "The session has expired.")
            row = database.execute(
                select(InternalUser, UserRoleAssignment)
                .join(UserRoleAssignment, UserRoleAssignment.user_id == InternalUser.id)
                .where(InternalUser.id == session.user_id)
            ).one_or_none()
            allowed_statuses = (
                {"active", "deletion_pending"} if allow_deletion_pending else {"active"}
            )
            if row is None or row[0].status not in allowed_statuses:
                raise AuthenticationError(403, "account_unavailable", "The account is not active.")
            if slide:
                session.last_seen_at = now
                session.idle_expires_at = min(
                    now + timedelta(minutes=self.settings.idle_minutes),
                    _aware(session.absolute_expires_at),
                )
                database.commit()
            user, assignment = row
            principal = Principal(
                user_id=user.id,
                role=assignment.role,  # type: ignore[arg-type]
                account_status=user.status,  # type: ignore[arg-type]
            )
            return SessionResult(
                token=raw_token,
                session_id=session.id,
                principal=principal,
                idle_expires_at=_aware(session.idle_expires_at),
                absolute_expires_at=_aware(session.absolute_expires_at),
                authenticated_at=_aware(session.authenticated_at),
                mfa_authenticated=session.mfa_authenticated,
            )

    def logout(self, raw_token: str, *, all_devices: bool) -> None:
        session = self.authenticate_session(raw_token, slide=False)
        now = self._now()
        with self._session_factory() as database:
            statement = update(ApplicationSession).where(ApplicationSession.revoked_at.is_(None))
            reason = "all_devices_logout" if all_devices else "session_logout"
            if all_devices:
                statement = statement.where(ApplicationSession.user_id == session.principal.user_id)
            else:
                statement = statement.where(ApplicationSession.id == session.session_id)
            database.execute(statement.values(revoked_at=now, revocation_reason=reason))
            database.commit()
        self._audit("logout", "accepted", reason, session.principal.user_id)

    def create_invitation(
        self,
        *,
        raw_session_token: str,
        role: UserRole,
        expires_in_minutes: int,
    ) -> InvitationResult:
        session = self.authenticate_session(raw_session_token, slide=False)
        self._require_operator_reauthentication(session)
        if role not in {"user", "support_restricted"}:
            raise AuthenticationError(400, "invalid_invitation_role", "Invitation role is invalid.")
        if not 5 <= expires_in_minutes <= int(self.INVITATION_MAX_TTL.total_seconds() / 60):
            raise AuthenticationError(
                400, "invalid_invitation_expiry", "Invitation expiry is invalid."
            )
        self._enforce_rate_limit("invite", session.principal.user_id, limit=20)
        now = self._now()
        raw_token = secrets.token_urlsafe(48)
        invitation_id = str(uuid4())
        expires_at = now + timedelta(minutes=expires_in_minutes)
        with self._session_factory() as database:
            database.add(
                AccountInvitation(
                    id=invitation_id,
                    token_sha256=_sha256(raw_token),
                    created_by_user_id=session.principal.user_id,
                    role=role,
                    created_at=now,
                    expires_at=expires_at,
                )
            )
            database.commit()
        self._audit(
            "invitation_created", "accepted", "single_use_invitation", session.principal.user_id
        )
        return InvitationResult(invitation_id, raw_token, role, expires_at)

    def revoke_invitation(self, *, raw_session_token: str, invitation_id: str) -> None:
        session = self.authenticate_session(raw_session_token, slide=False)
        self._require_operator_reauthentication(session)
        now = self._now()
        with self._session_factory() as database:
            invitation = database.get(AccountInvitation, invitation_id)
            if invitation is None:
                raise AuthenticationError(404, "invitation_not_found", "Invitation not found.")
            if invitation.accepted_at is not None:
                raise AuthenticationError(
                    409, "invitation_already_used", "Invitation is already used."
                )
            invitation.revoked_at = invitation.revoked_at or now
            database.commit()
        self._audit("invitation_revoked", "accepted", "operator_revoked", session.principal.user_id)

    def set_account_availability(
        self,
        *,
        raw_session_token: str,
        target_user_id: str,
        new_status: str,
    ) -> None:
        session = self.authenticate_session(raw_session_token, slide=False)
        self._require_operator_reauthentication(session)
        self._enforce_rate_limit("recovery", session.principal.user_id, limit=20)
        if target_user_id == session.principal.user_id:
            raise AuthenticationError(
                409, "owner_self_lockout_denied", "The active owner cannot suspend itself."
            )
        now = self._now()
        with self._session_factory() as database:
            user = database.get(InternalUser, target_user_id)
            if user is None:
                raise AuthenticationError(404, "account_not_found", "Account not found.")
            allowed = (user.status, new_status) in {
                ("active", "suspended"),
                ("suspended", "active"),
            }
            if not allowed:
                raise AuthenticationError(
                    409, "invalid_account_transition", "Account transition denied."
                )
            previous_status = user.status
            transitioned = cast(
                CursorResult[Any],
                database.execute(
                    update(InternalUser)
                    .where(
                        InternalUser.id == target_user_id,
                        InternalUser.status == previous_status,
                    )
                    .values(status=new_status, updated_at=now)
                    .execution_options(synchronize_session=False)
                ),
            )
            if transitioned.rowcount != 1:
                database.rollback()
                raise AuthenticationError(
                    409, "account_state_conflict", "Account transition must be retried."
                )
            database.add(
                AccountStateEvent(
                    id=str(uuid4()),
                    user_id=user.id,
                    actor_user_id=session.principal.user_id,
                    previous_status=previous_status,
                    new_status=new_status,
                    reason_code=(
                        "operator_security_suspension"
                        if new_status == "suspended"
                        else "operator_account_recovery"
                    ),
                    occurred_at=now,
                )
            )
            database.commit()
        if new_status == "suspended":
            self._revoke_user_sessions(target_user_id, "account_suspended")
        self._audit(
            "account_availability_changed",
            "accepted",
            f"account_{new_status}",
            target_user_id,
        )

    def request_deletion(self, raw_session_token: str) -> None:
        session = self.authenticate_session(raw_session_token, slide=False)
        self._require_recent_mfa(session)
        self._transition_self(session, "deletion_pending", "user_deletion_requested")
        self._revoke_user_sessions(session.principal.user_id, "deletion_requested")

    def cancel_deletion(self, *, raw_session_token: str) -> None:
        session = self.authenticate_session(
            raw_session_token,
            slide=False,
            allow_deletion_pending=True,
        )
        self._require_recent_mfa(session)
        self._transition_self(session, "active", "user_deletion_cancelled")

    def _transition_self(self, session: SessionResult, new_status: str, reason: str) -> None:
        now = self._now()
        with self._session_factory() as database:
            user = database.get(InternalUser, session.principal.user_id)
            if user is None:
                raise AuthenticationError(404, "account_not_found", "Account not found.")
            previous = user.status
            allowed = previous == "active" and new_status == "deletion_pending"
            allowed = allowed or (previous == "deletion_pending" and new_status == "active")
            if not allowed:
                raise AuthenticationError(
                    409, "invalid_account_transition", "Account transition denied."
                )
            if new_status == "active" and (
                user.deletion_requested_at is None
                or _aware(user.deletion_requested_at) + self.DELETION_CANCELLATION_WINDOW <= now
            ):
                raise AuthenticationError(
                    409, "deletion_cancellation_expired", "Cancellation period expired."
                )
            transitioned = cast(
                CursorResult[Any],
                database.execute(
                    update(InternalUser)
                    .where(
                        InternalUser.id == user.id,
                        InternalUser.status == previous,
                    )
                    .values(
                        status=new_status,
                        updated_at=now,
                        deletion_requested_at=(now if new_status == "deletion_pending" else None),
                    )
                    .execution_options(synchronize_session=False)
                ),
            )
            if transitioned.rowcount != 1:
                database.rollback()
                raise AuthenticationError(
                    409, "account_state_conflict", "Account transition must be retried."
                )
            database.add(
                AccountStateEvent(
                    id=str(uuid4()),
                    user_id=user.id,
                    actor_user_id=user.id,
                    previous_status=previous,
                    new_status=new_status,
                    reason_code=reason,
                    occurred_at=now,
                )
            )
            database.commit()

    def _validate_claims(
        self, claims: VerifiedOidcClaims, expected_nonce_sha256: str, now: datetime
    ) -> None:
        valid = (
            hmac.compare_digest(claims.issuer, self.settings.issuer)
            and self.settings.audience in claims.audience
            and hmac.compare_digest(_sha256(claims.nonce), expected_nonce_sha256)
            and bool(claims.subject)
            and len(claims.subject) <= 255
            and _aware(claims.issued_at) <= now + timedelta(minutes=1)
            and _aware(claims.expires_at) > now
            and _aware(claims.authenticated_at) <= now + timedelta(minutes=1)
            and "mfa" in claims.authentication_methods
        )
        if not valid:
            self._audit("login_callback", "denied", "oidc_claims_rejected", None)
            raise AuthenticationError(401, "oidc_claims_rejected", "Login could not be completed.")

    def _resolve_or_create_principal(
        self,
        transaction: OidcLoginTransaction,
        claims: VerifiedOidcClaims,
        now: datetime,
    ) -> tuple[Principal, bool]:
        with self._session_factory() as database:
            row = database.execute(
                select(ExternalIdentity, InternalUser, UserRoleAssignment)
                .join(InternalUser, InternalUser.id == ExternalIdentity.user_id)
                .join(UserRoleAssignment, UserRoleAssignment.user_id == InternalUser.id)
                .where(
                    ExternalIdentity.issuer == claims.issuer,
                    ExternalIdentity.subject == claims.subject,
                )
            ).one_or_none()
            if row is not None:
                identity, user, assignment = row
                if identity.revoked_at is not None or user.status not in {
                    "active",
                    "deletion_pending",
                }:
                    raise AuthenticationError(
                        403, "account_unavailable", "The account is unavailable."
                    )
                return (
                    Principal(
                        user_id=user.id,
                        role=assignment.role,  # type: ignore[arg-type]
                        account_status=user.status,  # type: ignore[arg-type]
                    ),
                    False,
                )
            if transaction.invitation_id is None:
                raise AuthenticationError(
                    401, "authentication_required", "Login could not be completed."
                )
            invitation = database.get(AccountInvitation, transaction.invitation_id)
            if (
                invitation is None
                or invitation.accepted_at is not None
                or invitation.revoked_at is not None
                or _aware(invitation.expires_at) <= now
            ):
                raise AuthenticationError(
                    400, "invitation_unavailable", "The invitation is unavailable."
                )
            user_id = str(uuid4())
            user = InternalUser(id=user_id, status="active", created_at=now, updated_at=now)
            database.add(user)
            database.flush()
            role: UserRole = invitation.role  # type: ignore[assignment]
            claimed = cast(
                CursorResult[Any],
                database.execute(
                    update(AccountInvitation)
                    .where(
                        AccountInvitation.id == invitation.id,
                        AccountInvitation.accepted_at.is_(None),
                        AccountInvitation.revoked_at.is_(None),
                        AccountInvitation.expires_at > now,
                    )
                    .values(accepted_by_user_id=user_id, accepted_at=now)
                    .execution_options(synchronize_session=False)
                ),
            )
            if claimed.rowcount != 1:
                database.rollback()
                raise AuthenticationError(
                    400, "invitation_unavailable", "The invitation is unavailable."
                )
            database.add_all(
                [
                    ExternalIdentity(
                        id=str(uuid4()),
                        user_id=user_id,
                        issuer=claims.issuer,
                        subject=claims.subject,
                        created_at=now,
                    ),
                    UserRoleAssignment(user_id=user_id, role=role, assigned_at=now),
                    AccountStateEvent(
                        id=str(uuid4()),
                        user_id=user_id,
                        actor_user_id=invitation.created_by_user_id,
                        previous_status=None,
                        new_status="active",
                        reason_code="invitation_accepted_with_oidc_mfa",
                        occurred_at=now,
                    ),
                ]
            )
            try:
                database.commit()
            except IntegrityError as error:
                database.rollback()
                raise AuthenticationError(
                    401, "identity_binding_conflict", "Login could not be completed."
                ) from error
            return Principal(user_id=user_id, role=role, account_status="active"), True

    def _initialize_user_defaults(self, principal: Principal, now: datetime) -> None:
        if principal.role == "support_restricted":
            return
        with principal_scope(principal), self._session_factory() as database:
            database.add_all(
                [
                    UserSettings(
                        external_ai_enabled=False,
                        inactivity_timeout_minutes=120,
                        updated_at=now,
                    ),
                    NotificationPreference(
                        email_enabled=False,
                        email_action_required=False,
                        email_warning=False,
                        email_delay_minutes=10,
                        smtp_security="starttls",
                        updated_at=now,
                    ),
                ]
            )
            database.commit()

    def _require_recent_mfa(self, session: SessionResult) -> None:
        if (
            not session.mfa_authenticated
            or session.authenticated_at + self.REAUTH_MAX_AGE <= self._now()
        ):
            raise AuthenticationError(403, "reauthentication_required", "Recent MFA is required.")

    def _require_operator_reauthentication(self, session: SessionResult) -> None:
        if session.principal.role != "owner_operator":
            raise AuthenticationError(
                403, "operator_required", "Owner-operator access is required."
            )
        self._require_recent_mfa(session)

    def _revoke_user_sessions(self, user_id: str, reason: str) -> None:
        now = self._now()
        with self._session_factory() as database:
            database.execute(
                update(ApplicationSession)
                .where(
                    ApplicationSession.user_id == user_id,
                    ApplicationSession.revoked_at.is_(None),
                )
                .values(revoked_at=now, revocation_reason=reason)
            )
            database.commit()

    @staticmethod
    def _find_session(database: Session, raw_token: str) -> ApplicationSession | None:
        return database.scalar(
            select(ApplicationSession).where(ApplicationSession.token_sha256 == _sha256(raw_token))
        )

    def _enforce_rate_limit(self, action: str, identifier: str, *, limit: int) -> None:
        now = self._now()
        window = timedelta(minutes=10)
        key_sha256 = hmac.new(
            self._rate_limit_key, identifier.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        window_floor = now - window
        for _attempt in range(5):
            with self._session_factory() as database:
                incremented = cast(
                    CursorResult[Any],
                    database.execute(
                        update(AuthRateLimitBucket)
                        .where(
                            AuthRateLimitBucket.action == action,
                            AuthRateLimitBucket.key_sha256 == key_sha256,
                            AuthRateLimitBucket.window_started_at > window_floor,
                            AuthRateLimitBucket.attempt_count < limit,
                        )
                        .values(attempt_count=AuthRateLimitBucket.attempt_count + 1)
                        .execution_options(synchronize_session=False)
                    ),
                )
                if incremented.rowcount == 1:
                    database.commit()
                    return

                bucket = database.scalar(
                    select(AuthRateLimitBucket).where(
                        AuthRateLimitBucket.action == action,
                        AuthRateLimitBucket.key_sha256 == key_sha256,
                    )
                )
                if bucket is not None and _aware(bucket.window_started_at) > window_floor:
                    if bucket.attempt_count >= limit:
                        raise AuthenticationError(429, "rate_limit_exceeded", "Try again later.")
                    database.rollback()
                    continue
                if bucket is not None:
                    reset = cast(
                        CursorResult[Any],
                        database.execute(
                            update(AuthRateLimitBucket)
                            .where(
                                AuthRateLimitBucket.id == bucket.id,
                                AuthRateLimitBucket.window_started_at == bucket.window_started_at,
                                AuthRateLimitBucket.attempt_count == bucket.attempt_count,
                            )
                            .values(window_started_at=now, attempt_count=1)
                            .execution_options(synchronize_session=False)
                        ),
                    )
                    if reset.rowcount == 1:
                        database.commit()
                        return
                    database.rollback()
                    continue

                database.add(
                    AuthRateLimitBucket(
                        id=str(uuid4()),
                        action=action,
                        key_sha256=key_sha256,
                        window_started_at=now,
                        attempt_count=1,
                    )
                )
                try:
                    database.commit()
                    return
                except IntegrityError:
                    database.rollback()
        raise AuthenticationError(429, "rate_limit_exceeded", "Try again later.")

    def _audit(
        self,
        event_type: str,
        outcome: str,
        reason_code: str,
        user_id: str | None,
    ) -> None:
        with self._session_factory() as database:
            database.add(
                AuthSecurityEvent(
                    id=str(uuid4()),
                    user_id=user_id,
                    event_type=event_type,
                    outcome=outcome,
                    reason_code=reason_code,
                    correlation_id=str(uuid4()),
                    occurred_at=self._now(),
                )
            )
            database.commit()
