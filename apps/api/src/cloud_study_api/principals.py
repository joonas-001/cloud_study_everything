from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

UserRole = Literal["user", "owner_operator", "support_restricted"]
AccountStatus = Literal["active", "suspended", "deletion_pending", "deleted"]

# Stable, opaque internal subject for every record that predates milestone 9B.
# It is deliberately unrelated to an email address or an external identity subject.
LEGACY_OWNER_USER_ID = "8f369a6e-8b7d-4a45-9f40-39bcfd6ac789"
LEGACY_OWNER_ROLE: UserRole = "owner_operator"


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    role: UserRole
    account_status: AccountStatus


LEGACY_OWNER_PRINCIPAL = Principal(
    user_id=LEGACY_OWNER_USER_ID,
    role=LEGACY_OWNER_ROLE,
    account_status="active",
)

_current_principal: ContextVar[Principal] = ContextVar(
    "cloud_study_current_principal",
    default=LEGACY_OWNER_PRINCIPAL,
)


class PrincipalAccessError(RuntimeError):
    """Raised when an account cannot access user-owned data."""


def current_principal() -> Principal:
    return _current_principal.get()


def require_data_principal() -> Principal:
    principal = current_principal()
    if principal.account_status != "active":
        raise PrincipalAccessError("the current account is not active")
    if principal.role == "support_restricted":
        raise PrincipalAccessError("support accounts have no default access to user data")
    return principal


@contextmanager
def principal_scope(principal: Principal) -> Iterator[None]:
    token = _current_principal.set(principal)
    try:
        yield
    finally:
        _current_principal.reset(token)
