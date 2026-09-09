from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.models import (
    AccountStateEvent,
    ExternalIdentity,
    InternalUser,
    NotificationPreference,
    UserRoleAssignment,
    UserSettings,
    utc_now,
)
from cloud_study_api.principals import (
    AccountStatus,
    Principal,
    UserRole,
    current_principal,
    principal_scope,
)


class IdentityError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class IdentityService:
    """Resolves pre-provisioned synthetic identities to stable internal subjects.

    This is deliberately not a Clerk adapter. It exists only for local 9B isolation
    validation and never accepts an internal user id from an HTTP request.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._now = now

    def authenticate_synthetic(self, issuer: str, subject: str) -> Principal:
        normalized_issuer = issuer.strip()
        normalized_subject = subject.strip()
        if not normalized_issuer or not normalized_subject:
            raise IdentityError(401, "authentication_required", "Synthetic identity is required.")
        if len(normalized_issuer) > 255 or len(normalized_subject) > 255:
            raise IdentityError(401, "invalid_identity", "Synthetic identity is invalid.")
        with self._session_factory() as database:
            row = database.execute(
                select(InternalUser, UserRoleAssignment)
                .join(ExternalIdentity, ExternalIdentity.user_id == InternalUser.id)
                .join(UserRoleAssignment, UserRoleAssignment.user_id == InternalUser.id)
                .where(
                    ExternalIdentity.issuer == normalized_issuer,
                    ExternalIdentity.subject == normalized_subject,
                    ExternalIdentity.revoked_at.is_(None),
                )
            ).one_or_none()
        if row is None:
            raise IdentityError(401, "authentication_required", "Synthetic identity is unknown.")
        user, assignment = row
        if user.status != "active":
            raise IdentityError(403, "account_unavailable", "The account is not active.")
        return Principal(
            user_id=user.id,
            role=assignment.role,  # type: ignore[arg-type]
            account_status=user.status,  # type: ignore[arg-type]
        )

    def create_synthetic_identity(
        self,
        *,
        issuer: str,
        subject: str,
        role: UserRole = "user",
        status: AccountStatus = "active",
    ) -> Principal:
        if not issuer.startswith("urn:cloud-study:synthetic:"):
            raise ValueError("synthetic issuers must use the governed urn namespace")
        if not subject.strip() or len(subject) > 255:
            raise ValueError("synthetic subject is invalid")
        now = self._now()
        user_id = str(uuid4())
        principal = Principal(user_id=user_id, role=role, account_status=status)
        with self._session_factory() as database:
            database.add(
                InternalUser(
                    id=user_id,
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
            )
            database.flush()
            database.add_all(
                [
                    UserRoleAssignment(user_id=user_id, role=role, assigned_at=now),
                    ExternalIdentity(
                        id=str(uuid4()),
                        user_id=user_id,
                        issuer=issuer,
                        subject=subject.strip(),
                        created_at=now,
                    ),
                    AccountStateEvent(
                        id=str(uuid4()),
                        user_id=user_id,
                        actor_user_id=None,
                        previous_status=None,
                        new_status=status,
                        reason_code="synthetic_9b_provisioning",
                        occurred_at=now,
                    ),
                ]
            )
            database.commit()
        if role != "support_restricted" and status == "active":
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
        return principal

    def set_account_status(
        self,
        *,
        user_id: str,
        new_status: AccountStatus,
        reason_code: str,
    ) -> None:
        actor = current_principal()
        if actor.account_status != "active" or actor.role != "owner_operator":
            raise IdentityError(403, "operator_required", "Owner-operator access is required.")
        transitions: dict[str, set[str]] = {
            "active": {"suspended", "deletion_pending"},
            "suspended": {"active", "deletion_pending"},
            "deletion_pending": {"active", "deleted"},
            "deleted": set(),
        }
        with self._session_factory() as database:
            user = database.get(InternalUser, user_id)
            if user is None:
                raise IdentityError(404, "user_not_found", "User not found.")
            if new_status not in transitions[user.status]:
                raise IdentityError(409, "invalid_account_transition", "Account transition denied.")
            now = self._now()
            previous_status = user.status
            user.status = new_status
            user.updated_at = now
            if new_status == "deletion_pending":
                user.deletion_requested_at = now
            elif new_status == "active":
                user.deletion_requested_at = None
            elif new_status == "deleted":
                user.deleted_at = now
            database.add(
                AccountStateEvent(
                    id=str(uuid4()),
                    user_id=user_id,
                    actor_user_id=actor.user_id,
                    previous_status=previous_status,
                    new_status=new_status,
                    reason_code=reason_code,
                    occurred_at=now,
                )
            )
            database.commit()
