from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Engine, Table, case, delete, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.models import (
    AccountInvitation,
    ApplicationSession,
    OperationsAuditEvent,
    OperationsControl,
    OperationsMetric,
    OperationsQuotaBucket,
    PrivacyChoice,
    SupportAccessGrant,
    SupportCase,
    UserRoleAssignment,
    utc_now,
)
from cloud_study_api.principals import (
    LEGACY_OWNER_USER_ID,
    Principal,
    current_principal,
    require_data_principal,
)

SUPPORT_CATEGORIES = {
    "product_support",
    "account_recovery",
    "security_vulnerability",
    "privacy_request",
    "content_correction",
    "abuse_appeal",
}
ACCESS_SCOPES = {"ticket_metadata", "case_content"}
SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{2,79}$")
GENESIS_HASH = "0" * 64


class OperationsError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=lambda item: _aware(item).isoformat() if isinstance(item, datetime) else str(item),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _subject_hash(user_id: str | None) -> str:
    return hashlib.sha256(f"cloud-study-9e:{user_id or 'anonymous'}".encode()).hexdigest()


def _table(model: Any) -> Table:
    return cast(Table, model.__table__)


class OperationsService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        repository_root: Path,
        *,
        now: Callable[[], datetime] = utc_now,
        enforcement_enabled: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._engine = cast(Engine, session_factory.kw["bind"])
        self._now = now
        self._enforcement_enabled = enforcement_enabled
        policy_path = repository_root / "governance" / "operations" / "milestone-9e-policy.json"
        self._policy: dict[str, Any] = json.loads(policy_path.read_text(encoding="utf-8"))
        self._validate_policy()
        self._ensure_control()

    def _validate_policy(self) -> None:
        if self._policy.get("status") != "synthetic_candidate_only":
            raise RuntimeError("9E operations policy must remain a synthetic candidate")
        if self._policy.get("real_user_ready") is not False:
            raise RuntimeError("9E operations policy cannot declare real-user readiness")
        routes = self._policy.get("support", {}).get("routes", {})
        if set(routes) != SUPPORT_CATEGORIES:
            raise RuntimeError("9E support routing categories are incomplete")
        quotas = self._policy.get("quotas", {})
        if set(quotas) != {"login", "runner", "export", "search", "notifications", "future_ai"}:
            raise RuntimeError("9E quota policy is incomplete")
        cost = self._policy.get("cost", {})
        if cost.get("unknown_recurring_costs") is not False:
            raise RuntimeError("9E cannot proceed with unknown recurring cost")
        if cost.get("automatic_recharge") or cost.get("automatic_scaling"):
            raise RuntimeError("9E forbids automatic recharge and scaling")

    def _ensure_control(self) -> None:
        table = _table(OperationsControl)
        now = self._now()
        with self._engine.begin() as connection:
            if connection.execute(select(table.c.id).where(table.c.id == 1)).first() is None:
                connection.execute(
                    insert(table).values(
                        id=1,
                        service_mode="normal",
                        invitations_enabled=True,
                        runner_enabled=True,
                        external_ai_enabled=False,
                        external_sources_enabled=False,
                        email_enabled=False,
                        revision=1,
                        reason_code="milestone_9e_safe_defaults",
                        updated_by_user_id=LEGACY_OWNER_USER_ID,
                        updated_at=now,
                    )
                )

    @staticmethod
    def _require_operator() -> Principal:
        principal = current_principal()
        if principal.account_status != "active" or principal.role != "owner_operator":
            raise OperationsError(403, "operator_required", "Owner-operator access is required.")
        return principal

    @staticmethod
    def _require_support() -> Principal:
        principal = current_principal()
        if principal.account_status != "active" or principal.role != "support_restricted":
            raise OperationsError(
                403, "support_role_required", "Restricted support access is required."
            )
        return principal

    def overview(self) -> dict[str, Any]:
        principal = current_principal()
        control = self._control()
        return {
            "policy_version": self._policy["policy_version"],
            "status": self._policy["status"],
            "real_user_ready": False,
            "role": principal.role,
            "support": self._policy["support"],
            "controls": control,
            "quotas": self._policy["quotas"],
            "cost": self._policy["cost"],
            "observability": self._policy["observability"],
            "hard_stop_events": self._policy["hard_stop_events"],
            "blocking_reasons": self._policy["blocking_reasons"],
        }

    def _control(self) -> dict[str, Any]:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(_table(OperationsControl)).where(OperationsControl.id == 1)
                )
                .mappings()
                .one()
            )
        return dict(row)

    def create_case(self, *, category: str, summary: str, description: str) -> dict[str, Any]:
        principal = require_data_principal()
        if category not in SUPPORT_CATEGORIES:
            raise OperationsError(422, "support_category_invalid", "Support category is invalid.")
        summary = summary.strip()
        description = description.strip()
        if not 3 <= len(summary) <= 160 or not 3 <= len(description) <= 4000:
            raise OperationsError(
                422, "support_content_invalid", "Support content length is invalid."
            )
        now = self._now()
        case = SupportCase(
            id=str(uuid4()),
            user_id=principal.user_id,
            category=category,
            status="open",
            summary=summary,
            description=description,
            created_at=now,
            updated_at=now,
        )
        with self._session_factory() as database:
            database.add(case)
            database.commit()
        self._audit(
            "support_case_created",
            principal.user_id,
            target_user_id=principal.user_id,
            case_id=case.id,
            reason_code=category,
        )
        return self._case_payload(case, include_content=True)

    def list_cases(self) -> list[dict[str, Any]]:
        require_data_principal()
        with self._session_factory() as database:
            rows = database.scalars(
                select(SupportCase).order_by(SupportCase.created_at.desc())
            ).all()
        return [self._case_payload(row, include_content=True) for row in rows]

    def list_visible_grants(self) -> list[dict[str, Any]]:
        principal = current_principal()
        table = _table(SupportAccessGrant)
        statement = select(table).order_by(table.c.requested_at.desc())
        if principal.role == "support_restricted":
            statement = statement.where(table.c.support_user_id == principal.user_id)
        elif principal.role == "user":
            statement = statement.where(table.c.target_user_id == principal.user_id)
        elif principal.role != "owner_operator":
            raise OperationsError(403, "role_access_denied", "Access is denied.")
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._grant_payload(row) for row in rows]

    def request_support_access(
        self,
        *,
        case_id: str,
        scope: str,
        reason_code: str,
        duration_minutes: int,
    ) -> dict[str, Any]:
        support = self._require_support()
        self._validate_access_input(scope, reason_code, duration_minutes, emergency=False)
        case_table = _table(SupportCase)
        with self._engine.begin() as connection:
            case = (
                connection.execute(
                    select(case_table.c.id, case_table.c.user_id).where(case_table.c.id == case_id)
                )
                .mappings()
                .one_or_none()
            )
            if case is None:
                raise OperationsError(
                    404, "support_case_unavailable", "Support case is unavailable."
                )
            now = self._now()
            grant_id = str(uuid4())
            connection.execute(
                insert(SupportAccessGrant).values(
                    id=grant_id,
                    case_id=case_id,
                    target_user_id=case["user_id"],
                    support_user_id=support.user_id,
                    requested_by_user_id=support.user_id,
                    approved_by_user_id=None,
                    status="requested",
                    scope=scope,
                    reason_code=reason_code,
                    incident_reference=None,
                    emergency=False,
                    requested_at=now,
                    approved_at=None,
                    expires_at=now + timedelta(minutes=duration_minutes),
                    revoked_at=None,
                    post_notice_at=None,
                )
            )
        self._audit(
            "support_access_requested",
            support.user_id,
            target_user_id=str(case["user_id"]),
            case_id=case_id,
            grant_id=grant_id,
            reason_code=reason_code,
            payload={"scope": scope, "duration_minutes": duration_minutes},
        )
        return self.get_grant(grant_id)

    def approve_support_access(self, grant_id: str) -> dict[str, Any]:
        operator = self._require_operator()
        table = _table(SupportAccessGrant)
        now = self._now()
        with self._engine.begin() as connection:
            grant = (
                connection.execute(select(table).where(table.c.id == grant_id))
                .mappings()
                .one_or_none()
            )
            if (
                grant is None
                or grant["status"] != "requested"
                or _aware(grant["expires_at"]) <= now
            ):
                raise OperationsError(
                    409, "support_access_not_approvable", "Access request is not approvable."
                )
            if grant["scope"] == "case_content" and not self._support_diagnostics_enabled(
                connection, str(grant["target_user_id"])
            ):
                raise OperationsError(
                    409,
                    "support_diagnostics_consent_required",
                    "The user has not enabled support diagnostics for case content.",
                )
            connection.execute(
                update(table)
                .where(table.c.id == grant_id, table.c.status == "requested")
                .values(
                    status="active",
                    approved_by_user_id=operator.user_id,
                    approved_at=now,
                )
            )
        self._audit(
            "support_access_approved",
            operator.user_id,
            target_user_id=str(grant["target_user_id"]),
            case_id=cast(str | None, grant["case_id"]),
            grant_id=grant_id,
            reason_code="dual_confirmation_completed",
            payload={"scope": grant["scope"]},
        )
        return self.get_grant(grant_id)

    def create_emergency_access(
        self,
        *,
        case_id: str,
        support_user_id: str,
        incident_reference: str,
        reason_code: str,
        duration_minutes: int,
    ) -> dict[str, Any]:
        operator = self._require_operator()
        self._validate_access_input(
            "ticket_metadata", reason_code, duration_minutes, emergency=True
        )
        if not SAFE_CODE.fullmatch(incident_reference):
            raise OperationsError(
                422, "incident_reference_invalid", "Incident reference is invalid."
            )
        case_table = _table(SupportCase)
        role_table = _table(UserRoleAssignment)
        now = self._now()
        with self._engine.begin() as connection:
            case = (
                connection.execute(
                    select(case_table.c.id, case_table.c.user_id).where(case_table.c.id == case_id)
                )
                .mappings()
                .one_or_none()
            )
            support_role = connection.execute(
                select(role_table.c.role).where(role_table.c.user_id == support_user_id)
            ).scalar_one_or_none()
            if case is None or support_role != "support_restricted":
                raise OperationsError(
                    404, "emergency_access_target_unavailable", "Emergency target is unavailable."
                )
            grant_id = str(uuid4())
            connection.execute(
                insert(SupportAccessGrant).values(
                    id=grant_id,
                    case_id=case_id,
                    target_user_id=case["user_id"],
                    support_user_id=support_user_id,
                    requested_by_user_id=operator.user_id,
                    approved_by_user_id=operator.user_id,
                    status="active",
                    scope="ticket_metadata",
                    reason_code=reason_code,
                    incident_reference=incident_reference,
                    emergency=True,
                    requested_at=now,
                    approved_at=now,
                    expires_at=now + timedelta(minutes=duration_minutes),
                    revoked_at=None,
                    post_notice_at=None,
                )
            )
        self._audit(
            "emergency_support_access_activated",
            operator.user_id,
            target_user_id=str(case["user_id"]),
            case_id=case_id,
            grant_id=grant_id,
            reason_code=reason_code,
            payload={"incident_reference": incident_reference, "scope": "ticket_metadata"},
        )
        return self.get_grant(grant_id)

    def view_with_grant(self, grant_id: str) -> dict[str, Any]:
        support = self._require_support()
        grant_table = _table(SupportAccessGrant)
        case_table = _table(SupportCase)
        now = self._now()
        with self._engine.begin() as connection:
            grant = (
                connection.execute(select(grant_table).where(grant_table.c.id == grant_id))
                .mappings()
                .one_or_none()
            )
            if (
                grant is None
                or grant["support_user_id"] != support.user_id
                or grant["status"] != "active"
            ):
                raise OperationsError(403, "support_access_denied", "Support access is denied.")
            if _aware(grant["expires_at"]) <= now:
                connection.execute(
                    update(grant_table)
                    .where(grant_table.c.id == grant_id, grant_table.c.status == "active")
                    .values(status="expired")
                )
                expired = True
                case = None
            else:
                expired = False
                self._set_connection_principal(connection, str(grant["target_user_id"]))
                case = (
                    connection.execute(
                        select(case_table).where(
                            case_table.c.id == grant["case_id"],
                            case_table.c.user_id == grant["target_user_id"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        if expired:
            self._audit(
                "support_access_expired",
                support.user_id,
                target_user_id=str(grant["target_user_id"]),
                case_id=cast(str | None, grant["case_id"]),
                grant_id=grant_id,
                reason_code="access_deadline_elapsed",
            )
            raise OperationsError(403, "support_access_expired", "Support access has expired.")
        if case is None:
            raise OperationsError(404, "support_case_unavailable", "Support case is unavailable.")
        self._audit(
            "support_case_viewed",
            support.user_id,
            target_user_id=str(grant["target_user_id"]),
            case_id=str(case["id"]),
            grant_id=grant_id,
            reason_code=str(grant["reason_code"]),
            payload={"scope": grant["scope"]},
        )
        payload = self._case_payload(case, include_content=grant["scope"] == "case_content")
        payload["access_scope"] = grant["scope"]
        payload["access_expires_at"] = grant["expires_at"]
        return payload

    def revoke_access(self, grant_id: str, *, reason_code: str) -> dict[str, Any]:
        principal = current_principal()
        if not SAFE_CODE.fullmatch(reason_code):
            raise OperationsError(422, "reason_code_invalid", "Reason code is invalid.")
        table = _table(SupportAccessGrant)
        now = self._now()
        with self._engine.begin() as connection:
            grant = (
                connection.execute(select(table).where(table.c.id == grant_id))
                .mappings()
                .one_or_none()
            )
            if grant is None:
                raise OperationsError(
                    404, "support_access_not_found", "Access record was not found."
                )
            permitted = principal.role == "owner_operator" or (
                principal.role == "user" and grant["target_user_id"] == principal.user_id
            )
            if not permitted:
                raise OperationsError(403, "support_access_denied", "Access is denied.")
            if grant["status"] not in {"requested", "active"}:
                raise OperationsError(409, "support_access_terminal", "Access is already terminal.")
            connection.execute(
                update(table)
                .where(table.c.id == grant_id, table.c.status.in_(["requested", "active"]))
                .values(status="revoked", revoked_at=now)
            )
        self._audit(
            "support_access_revoked",
            principal.user_id,
            target_user_id=str(grant["target_user_id"]),
            case_id=cast(str | None, grant["case_id"]),
            grant_id=grant_id,
            reason_code=reason_code,
        )
        return self.get_grant(grant_id)

    def mark_emergency_notice(self, grant_id: str) -> dict[str, Any]:
        operator = self._require_operator()
        table = _table(SupportAccessGrant)
        now = self._now()
        with self._engine.begin() as connection:
            grant = (
                connection.execute(select(table).where(table.c.id == grant_id))
                .mappings()
                .one_or_none()
            )
            if grant is None or not grant["emergency"]:
                raise OperationsError(
                    404, "emergency_access_not_found", "Emergency access was not found."
                )
            connection.execute(
                update(table).where(table.c.id == grant_id).values(post_notice_at=now)
            )
        self._audit(
            "emergency_access_post_notice_recorded",
            operator.user_id,
            target_user_id=str(grant["target_user_id"]),
            case_id=cast(str | None, grant["case_id"]),
            grant_id=grant_id,
            reason_code="target_user_notified",
        )
        return self.get_grant(grant_id)

    def get_grant(self, grant_id: str) -> dict[str, Any]:
        principal = current_principal()
        table = _table(SupportAccessGrant)
        with self._engine.connect() as connection:
            row = (
                connection.execute(select(table).where(table.c.id == grant_id))
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise OperationsError(404, "support_access_not_found", "Access record was not found.")
        visible = (
            principal.role == "owner_operator"
            or row["support_user_id"] == principal.user_id
            or (principal.role == "user" and row["target_user_id"] == principal.user_id)
        )
        if not visible:
            raise OperationsError(404, "support_access_not_found", "Access record was not found.")
        return self._grant_payload(row)

    def update_controls(self, values: Mapping[str, Any], *, reason_code: str) -> dict[str, Any]:
        operator = self._require_operator()
        allowed = {
            "service_mode",
            "invitations_enabled",
            "runner_enabled",
            "external_ai_enabled",
            "external_sources_enabled",
            "email_enabled",
        }
        if not values or set(values) - allowed or not SAFE_CODE.fullmatch(reason_code):
            raise OperationsError(
                422, "operations_control_invalid", "Operations control update is invalid."
            )
        if (
            values.get("external_ai_enabled")
            or values.get("external_sources_enabled")
            or values.get("email_enabled")
        ):
            raise OperationsError(
                409,
                "capability_not_authorized_in_9e",
                "External AI, sources and email cannot be enabled in milestone 9E.",
            )
        if "service_mode" in values and values["service_mode"] not in {
            "normal",
            "read_only",
            "stopped",
        }:
            raise OperationsError(422, "service_mode_invalid", "Service mode is invalid.")
        table = _table(OperationsControl)
        with self._engine.begin() as connection:
            current = connection.execute(select(table).where(table.c.id == 1)).mappings().one()
            connection.execute(
                update(table)
                .where(table.c.id == 1, table.c.revision == current["revision"])
                .values(
                    **dict(values),
                    external_ai_enabled=False,
                    external_sources_enabled=False,
                    email_enabled=False,
                    revision=int(current["revision"]) + 1,
                    reason_code=reason_code,
                    updated_by_user_id=operator.user_id,
                    updated_at=self._now(),
                )
            )
        self._audit(
            "operations_control_changed",
            operator.user_id,
            reason_code=reason_code,
            payload={key: values[key] for key in sorted(values)},
        )
        return self._control()

    def require_feature(self, feature: str) -> None:
        if feature not in {
            "invitations",
            "runner",
            "external_ai",
            "external_sources",
            "email",
        }:
            raise OperationsError(
                500, "operations_feature_unknown", "Operations feature is unknown."
            )
        if not self._enforcement_enabled:
            return
        if not bool(self._control()[f"{feature}_enabled"]):
            raise OperationsError(409, f"{feature}_stopped", f"{feature} is temporarily stopped.")

    def revoke_all_invitations(self, *, reason_code: str) -> int:
        operator = self._require_operator()
        if not SAFE_CODE.fullmatch(reason_code):
            raise OperationsError(422, "reason_code_invalid", "Reason code is invalid.")
        now = self._now()
        table = _table(AccountInvitation)
        with self._engine.begin() as connection:
            result = connection.execute(
                update(table)
                .where(table.c.accepted_at.is_(None), table.c.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            count = int(result.rowcount or 0)
        self._audit(
            "all_invitations_revoked",
            operator.user_id,
            reason_code=reason_code,
            payload={"revoked_count": count},
        )
        return count

    def revoke_user_sessions(self, user_id: str, *, reason_code: str) -> int:
        operator = self._require_operator()
        if not SAFE_CODE.fullmatch(reason_code):
            raise OperationsError(422, "reason_code_invalid", "Reason code is invalid.")
        table = _table(ApplicationSession)
        now = self._now()
        with self._engine.begin() as connection:
            result = connection.execute(
                update(table)
                .where(table.c.user_id == user_id, table.c.revoked_at.is_(None))
                .values(revoked_at=now, revocation_reason=reason_code)
            )
            count = int(result.rowcount or 0)
        self._audit(
            "user_sessions_revoked",
            operator.user_id,
            target_user_id=user_id,
            reason_code=reason_code,
            payload={"revoked_count": count},
        )
        return count

    def authorize_request(self, path: str, method: str, principal: Principal) -> str | None:
        if not self._enforcement_enabled:
            return None
        control = self._control()
        recovery_path = path.startswith("/operations")
        safe_recovery = recovery_path or path in {"/health", "/auth/session", "/auth/logout"}
        if control["service_mode"] == "stopped" and not safe_recovery:
            self.record_metric(principal.user_id, "service", "rejected", "service_stopped", 503)
            raise OperationsError(503, "service_stopped", "The service is temporarily stopped.")
        if (
            control["service_mode"] == "read_only"
            and method not in {"GET", "HEAD", "OPTIONS"}
            and not safe_recovery
        ):
            self.record_metric(principal.user_id, "service", "rejected", "service_read_only", 409)
            raise OperationsError(409, "service_read_only", "The service is temporarily read-only.")
        feature = self._feature_for(path, method)
        if feature is not None and not bool(control[f"{feature}_enabled"]):
            self.record_metric(principal.user_id, feature, "rejected", f"{feature}_stopped", 409)
            raise OperationsError(409, f"{feature}_stopped", f"{feature} is temporarily stopped.")
        capability = self._capability_for(path, method)
        if capability is None:
            return None
        self._reserve_quota(capability, principal.user_id)
        return capability

    def release_request(
        self,
        capability: str | None,
        principal: Principal,
        *,
        status_code: int,
    ) -> None:
        if capability is not None:
            table = _table(OperationsQuotaBucket)
            hashes = {_subject_hash(principal.user_id), "global"}
            with self._engine.begin() as connection:
                connection.execute(
                    update(table)
                    .where(table.c.capability == capability, table.c.principal_hash.in_(hashes))
                    .values(
                        active_count=case(
                            (table.c.active_count > 0, table.c.active_count - 1), else_=0
                        ),
                        updated_at=self._now(),
                    )
                )
            self.record_metric(
                principal.user_id,
                capability,
                "accepted" if status_code < 400 else "failed",
                "request_completed" if status_code < 400 else "request_failed",
                status_code,
            )

    def _reserve_quota(self, capability: str, user_id: str) -> None:
        rule = self._policy["quotas"][capability]
        now = self._now()
        with self._engine.begin() as connection:
            self._consume_bucket(
                connection,
                capability,
                _subject_hash(user_id),
                int(rule["per_user"]),
                int(rule["concurrency"]),
                int(rule["window_seconds"]),
                now,
            )
            self._consume_bucket(
                connection,
                capability,
                "global",
                int(rule["global"]),
                int(rule["concurrency"]),
                int(rule["window_seconds"]),
                now,
            )

    def _consume_bucket(
        self,
        connection: Any,
        capability: str,
        principal_hash: str,
        limit: int,
        concurrency: int,
        window_seconds: int,
        now: datetime,
    ) -> None:
        if limit <= 0 or concurrency <= 0:
            raise OperationsError(429, "quota_exceeded", "The capability quota is unavailable.")
        table = _table(OperationsQuotaBucket)
        row = (
            connection.execute(
                select(table)
                .where(
                    table.c.capability == capability,
                    table.c.principal_hash == principal_hash,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            connection.execute(
                insert(table).values(
                    id=str(uuid4()),
                    capability=capability,
                    principal_hash=principal_hash,
                    window_started_at=now,
                    used_count=1,
                    active_count=1,
                    updated_at=now,
                )
            )
            return
        expired = _aware(row["window_started_at"]) + timedelta(seconds=window_seconds) <= now
        used = 0 if expired else int(row["used_count"])
        active = 0 if expired else int(row["active_count"])
        if used >= limit:
            raise OperationsError(429, "quota_exceeded", "The capability quota is exhausted.")
        if active >= concurrency:
            raise OperationsError(429, "concurrency_limit_exceeded", "The capability is busy.")
        connection.execute(
            update(table)
            .where(table.c.id == row["id"])
            .values(
                window_started_at=now if expired else row["window_started_at"],
                used_count=used + 1,
                active_count=active + 1,
                updated_at=now,
            )
        )

    def record_metric(
        self,
        user_id: str | None,
        action: str,
        outcome: str,
        reason_code: str,
        status_code: int,
    ) -> None:
        now = self._now()
        table = _table(OperationsMetric)
        with self._engine.begin() as connection:
            connection.execute(delete(table).where(table.c.occurred_at < now - timedelta(days=7)))
            connection.execute(
                insert(table).values(
                    id=str(uuid4()),
                    principal_hash=_subject_hash(user_id),
                    action=action,
                    outcome=outcome,
                    reason_code=reason_code,
                    status_code=status_code,
                    occurred_at=now,
                )
            )

    def verify_audit_chain(self) -> dict[str, Any]:
        self._require_operator()
        table = _table(OperationsAuditEvent)
        with self._engine.connect() as connection:
            rows = connection.execute(select(table).order_by(table.c.position)).mappings().all()
        previous = GENESIS_HASH
        for row in rows:
            material = self._audit_material(row, previous)
            if row["previous_hash"] != previous or row["event_hash"] != _canonical_sha256(material):
                return {"valid": False, "event_count": len(rows), "failed_event_id": row["id"]}
            previous = str(row["event_hash"])
        return {"valid": True, "event_count": len(rows), "head_hash": previous}

    def _audit(
        self,
        event_type: str,
        actor_user_id: str,
        *,
        target_user_id: str | None = None,
        case_id: str | None = None,
        grant_id: str | None = None,
        outcome: str = "accepted",
        reason_code: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        now = self._now()
        event_id = str(uuid4())
        table = _table(OperationsAuditEvent)
        with self._engine.begin() as connection:
            last = connection.execute(
                select(table.c.position, table.c.event_hash)
                .order_by(table.c.position.desc())
                .limit(1)
            ).one_or_none()
            position = int(last.position) + 1 if last is not None else 1
            previous_hash = str(last.event_hash) if last is not None else GENESIS_HASH
            values = {
                "id": event_id,
                "position": position,
                "event_type": event_type,
                "actor_hash": _subject_hash(actor_user_id),
                "target_hash": _subject_hash(target_user_id) if target_user_id else None,
                "case_id": case_id,
                "grant_id": grant_id,
                "outcome": outcome,
                "reason_code": reason_code,
                "payload_sha256": _canonical_sha256(dict(payload or {})),
                "previous_hash": previous_hash,
                "occurred_at": now,
            }
            values["event_hash"] = _canonical_sha256(self._audit_material(values, previous_hash))
            connection.execute(insert(table).values(**values))

    @staticmethod
    def _audit_material(row: Any, previous_hash: str) -> dict[str, Any]:
        return {
            "id": row["id"],
            "position": row["position"],
            "event_type": row["event_type"],
            "actor_hash": row["actor_hash"],
            "target_hash": row["target_hash"],
            "case_id": row["case_id"],
            "grant_id": row["grant_id"],
            "outcome": row["outcome"],
            "reason_code": row["reason_code"],
            "payload_sha256": row["payload_sha256"],
            "previous_hash": previous_hash,
            "occurred_at": _aware(row["occurred_at"]).isoformat(),
        }

    def _validate_access_input(
        self, scope: str, reason_code: str, duration_minutes: int, *, emergency: bool
    ) -> None:
        maximum = int(
            self._policy["support"][
                "emergency_access_max_minutes" if emergency else "normal_access_max_minutes"
            ]
        )
        if scope not in ACCESS_SCOPES or not SAFE_CODE.fullmatch(reason_code):
            raise OperationsError(
                422, "support_access_request_invalid", "Access request is invalid."
            )
        if not 1 <= duration_minutes <= maximum:
            raise OperationsError(
                422, "support_access_duration_invalid", "Access duration is invalid."
            )

    @staticmethod
    def _support_diagnostics_enabled(connection: Any, user_id: str) -> bool:
        table = _table(PrivacyChoice)
        return bool(
            connection.execute(
                select(table.c.enabled).where(
                    table.c.user_id == user_id,
                    table.c.purpose == "support_diagnostics",
                )
            ).scalar_one_or_none()
        )

    @staticmethod
    def _set_connection_principal(connection: Any, user_id: str) -> None:
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql(
                "SELECT set_config('cloud_study.user_id', %s, true)", (user_id,)
            )

    @staticmethod
    def _case_payload(row: SupportCase | RowMapping, *, include_content: bool) -> dict[str, Any]:
        def value(key: str) -> Any:
            return getattr(row, key) if isinstance(row, SupportCase) else row[key]

        payload = {
            "id": value("id"),
            "category": value("category"),
            "status": value("status"),
            "created_at": value("created_at"),
            "updated_at": value("updated_at"),
            "closed_at": value("closed_at"),
            "content_visible": include_content,
        }
        if include_content:
            payload.update(summary=value("summary"), description=value("description"))
        return payload

    @staticmethod
    def _grant_payload(row: RowMapping) -> dict[str, Any]:
        return {
            "id": row["id"],
            "case_id": row["case_id"],
            "status": row["status"],
            "scope": row["scope"],
            "reason_code": row["reason_code"],
            "emergency": row["emergency"],
            "incident_reference": row["incident_reference"],
            "requested_at": row["requested_at"],
            "approved_at": row["approved_at"],
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
            "post_notice_at": row["post_notice_at"],
            "post_notice_pending": bool(row["emergency"] and row["post_notice_at"] is None),
        }

    @staticmethod
    def _feature_for(path: str, method: str) -> str | None:
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if path.startswith("/auth/invitations"):
            return "invitations"
        if path.endswith("/execute"):
            return "runner"
        return None

    @staticmethod
    def _capability_for(path: str, method: str) -> str | None:
        if path in {"/auth/login/start", "/auth/callback"}:
            return "login"
        if method == "POST" and path == "/privacy/exports":
            return "export"
        if method == "POST" and path.endswith("/execute"):
            return "runner"
        if "/search" in path:
            return "search"
        if method == "POST" and ("notifications" in path or "email-outbox" in path):
            return "notifications"
        return None
