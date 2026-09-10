from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, cast
from uuid import UUID, uuid4

from sqlalchemy import Engine, Table, delete, func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.models import (
    AccountStateEvent,
    ApplicationSession,
    AuthSecurityEvent,
    Base,
    ExternalIdentity,
    InternalUser,
    PrivacyChoice,
    PrivacyDeletionJob,
    PrivacyDeletionTombstone,
    PrivacyPolicyAcceptance,
    PrivacyRequest,
    UserOwnedMixin,
    UserRoleAssignment,
    UserSettings,
    utc_now,
)
from cloud_study_api.principals import current_principal, require_data_principal


class PrivacyError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return {"encoding": "hex", "value": value.hex()}
    return value


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_value,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PrivacyService:
    CANCELLATION_WINDOW = timedelta(days=7)
    TOMBSTONE_RETENTION = timedelta(days=180)
    BACKUP_NATURAL_EXPIRY = timedelta(days=28)
    REAUTH_MAX_AGE = timedelta(minutes=5)
    PURPOSES: ClassVar[set[str]] = {
        "external_ai",
        "external_sources",
        "email_notifications",
        "support_diagnostics",
    }

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        repository_root: Path,
        *,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._engine = cast(Engine, session_factory.kw["bind"])
        self._now = now
        self._repository_root = repository_root
        policy_path = repository_root / "governance" / "privacy" / "milestone-9d-policy.json"
        self._policy = json.loads(policy_path.read_text(encoding="utf-8"))
        self._validate_policy()

    def _validate_policy(self) -> None:
        if self._policy.get("status") != "synthetic_candidate_only":
            raise RuntimeError("9D policy bundle must remain a synthetic candidate")
        if self._policy.get("professional_review") != "required_before_9g":
            raise RuntimeError("9D policy bundle must preserve the professional-review gate")
        document_types = [item["document_type"] for item in self._policy["documents"]]
        if len(document_types) != len(set(document_types)):
            raise RuntimeError("9D policy document types must be unique")
        purposes = {item["purpose"] for item in self._policy["optional_purposes"]}
        if purposes != self.PURPOSES:
            raise RuntimeError("9D optional privacy purposes are incomplete")

    def _documents(self) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        for item in self._policy["documents"]:
            document = dict(item)
            content_path = self._policy_path(str(item["content_path"]))
            content = content_path.read_bytes()
            document["content_sha256"] = hashlib.sha256(content).hexdigest()
            document["content_markdown"] = content.decode("utf-8")
            documents.append(document)
        return documents

    def _policy_path(self, relative_path: str) -> Path:
        policy_root = self._repository_root / "governance" / "privacy"
        candidate = (policy_root / relative_path).resolve()
        try:
            candidate.relative_to(policy_root.resolve())
        except ValueError as error:
            raise RuntimeError("9D policy document path escapes the governed directory") from error
        if not candidate.is_file():
            raise RuntimeError(f"9D policy document is missing: {relative_path}")
        return candidate

    def overview(self) -> dict[str, Any]:
        principal = require_data_principal()
        with self._session_factory() as database:
            acceptance_rows = database.scalars(
                select(PrivacyPolicyAcceptance).order_by(
                    PrivacyPolicyAcceptance.accepted_at,
                    PrivacyPolicyAcceptance.document_type,
                )
            ).all()
            choice_rows = {
                row.purpose: row for row in database.scalars(select(PrivacyChoice)).all()
            }
            job = database.scalar(
                select(PrivacyDeletionJob)
                .where(PrivacyDeletionJob.user_id == principal.user_id)
                .order_by(PrivacyDeletionJob.requested_at.desc())
            )
        acceptances = [
            {
                "document_type": row.document_type,
                "document_version": row.document_version,
                "content_sha256": row.content_sha256,
                "accepted_at": row.accepted_at,
            }
            for row in acceptance_rows
        ]
        accepted_keys = {
            (row.document_type, row.document_version, row.content_sha256) for row in acceptance_rows
        }
        documents = self._documents()
        for document in documents:
            document["accepted"] = (
                document["document_type"],
                document["version"],
                document["content_sha256"],
            ) in accepted_keys
        notice = next(item for item in documents if item["document_type"] == "privacy_notice")
        choices = []
        for definition in self._policy["optional_purposes"]:
            row = choice_rows.get(definition["purpose"])
            enabled = row.enabled if row is not None else False
            support_access_enabled = definition["purpose"] == "support_diagnostics" and enabled
            choices.append(
                {
                    **definition,
                    "enabled": enabled,
                    "notice_version": row.notice_version if row is not None else notice["version"],
                    "updated_at": row.updated_at if row is not None else None,
                    "effective_enabled": support_access_enabled,
                    "effective_reason": (
                        "9E 仅允许已双确认的本地工单正文访问;不会外发,也不开放普通用户数据。"
                        if support_access_enabled
                        else "真实外部能力仍受独立门禁并保持关闭。"
                    ),
                }
            )
        return {
            "bundle_version": self._policy["bundle_version"],
            "status": self._policy["status"],
            "professional_review": self._policy["professional_review"],
            "controller": self._policy["controller"],
            "documents": documents,
            "acceptances": acceptances,
            "choices": choices,
            "data_categories": self._policy["data_categories"],
            "retention_rules": self._policy["retention_rules"],
            "restricted_support_attachments": self._policy["restricted_support_attachments"],
            "deletion_job": self._job_payload(job) if job is not None else None,
            "real_user_ready": False,
            "blocking_reasons": [
                "professional_privacy_review_pending",
                "private_support_contact_not_configured",
                "real_identity_provider_not_activated",
                "9g_not_authorized",
            ],
        }

    def accept_documents(self, document_types: list[str]) -> dict[str, Any]:
        principal = require_data_principal()
        if not document_types or len(document_types) != len(set(document_types)):
            raise PrivacyError(422, "invalid_policy_selection", "政策文件选择不能为空或重复。")
        documents = {item["document_type"]: item for item in self._documents()}
        unknown = set(document_types) - set(documents)
        if unknown:
            raise PrivacyError(422, "unknown_policy_document", "政策文件版本不受管。")
        now = self._now()
        with self._session_factory() as database:
            for document_type in document_types:
                document = documents[document_type]
                existing = database.scalar(
                    select(PrivacyPolicyAcceptance).where(
                        PrivacyPolicyAcceptance.document_type == document_type,
                        PrivacyPolicyAcceptance.document_version == document["version"],
                        PrivacyPolicyAcceptance.content_sha256 == document["content_sha256"],
                    )
                )
                if existing is None:
                    database.add(
                        PrivacyPolicyAcceptance(
                            id=str(uuid4()),
                            user_id=principal.user_id,
                            document_type=document_type,
                            document_version=document["version"],
                            content_sha256=document["content_sha256"],
                            accepted_at=now,
                        )
                    )
            database.commit()
        return self.overview()

    def update_choices(self, choices: Mapping[str, bool]) -> dict[str, Any]:
        principal = require_data_principal()
        if not choices or set(choices) - self.PURPOSES:
            raise PrivacyError(422, "invalid_privacy_choice", "隐私用途选择不受管。")
        now = self._now()
        notice = next(
            item for item in self._documents() if item["document_type"] == "privacy_notice"
        )
        with self._session_factory() as database:
            for purpose, enabled in choices.items():
                row = database.scalar(select(PrivacyChoice).where(PrivacyChoice.purpose == purpose))
                if row is None:
                    database.add(
                        PrivacyChoice(
                            id=str(uuid4()),
                            user_id=principal.user_id,
                            purpose=purpose,
                            enabled=enabled,
                            notice_version=notice["version"],
                            updated_at=now,
                        )
                    )
                else:
                    row.enabled = enabled
                    row.notice_version = notice["version"]
                    row.updated_at = now
            database.commit()
        return self.overview()

    def access_report(self) -> dict[str, Any]:
        principal = require_data_principal()
        now = self._now()
        self._record_request("access", {"scope": "metadata_and_counts"}, now)
        table_counts: dict[str, int] = {}
        with self._engine.connect() as connection:
            for table in self._private_tables():
                table_counts[table.name] = int(
                    connection.execute(
                        select(func.count())
                        .select_from(table)
                        .where(table.c.user_id == principal.user_id)
                    ).scalar_one()
                )
            user = (
                connection.execute(
                    select(
                        InternalUser.id,
                        InternalUser.status,
                        InternalUser.created_at,
                        InternalUser.updated_at,
                        InternalUser.deletion_requested_at,
                        InternalUser.deleted_at,
                    ).where(InternalUser.id == principal.user_id)
                )
                .mappings()
                .one()
            )
        return {
            "generated_at": now,
            "subject": {key: _json_value(value) for key, value in user.items()},
            "table_counts": table_counts,
            "data_categories": self._policy["data_categories"],
            "scope_note": (
                "仅返回当前主体的元数据、分类和逐表数量; 正文只在确认后的全量导出中返回。"
            ),
        }

    def correct_settings(
        self,
        *,
        inactivity_timeout_minutes: int | None,
        choices: Mapping[str, bool],
    ) -> dict[str, Any]:
        principal = require_data_principal()
        if inactivity_timeout_minutes is None and not choices:
            raise PrivacyError(422, "empty_correction", "更正请求至少需要一个字段。")
        if inactivity_timeout_minutes is not None and not 1 <= inactivity_timeout_minutes <= 1440:
            raise PrivacyError(
                422, "invalid_inactivity_timeout", "无操作时限必须为 1 至 1440 分钟。"
            )
        if set(choices) - self.PURPOSES:
            raise PrivacyError(422, "invalid_privacy_choice", "隐私用途选择不受管。")
        now = self._now()
        with self._session_factory() as database:
            if inactivity_timeout_minutes is not None:
                settings = database.scalar(select(UserSettings))
                if settings is None:
                    settings = UserSettings(
                        user_id=principal.user_id,
                        external_ai_enabled=False,
                        inactivity_timeout_minutes=inactivity_timeout_minutes,
                        updated_at=now,
                    )
                    database.add(settings)
                else:
                    settings.inactivity_timeout_minutes = inactivity_timeout_minutes
                    settings.updated_at = now
            notice = next(
                item for item in self._documents() if item["document_type"] == "privacy_notice"
            )
            for purpose, enabled in choices.items():
                row = database.scalar(select(PrivacyChoice).where(PrivacyChoice.purpose == purpose))
                if row is None:
                    database.add(
                        PrivacyChoice(
                            id=str(uuid4()),
                            user_id=principal.user_id,
                            purpose=purpose,
                            enabled=enabled,
                            notice_version=notice["version"],
                            updated_at=now,
                        )
                    )
                else:
                    row.enabled = enabled
                    row.notice_version = notice["version"]
                    row.updated_at = now
            scope = {
                "inactivity_timeout_minutes": inactivity_timeout_minutes is not None,
                "choice_purposes": sorted(choices),
            }
            database.add(
                PrivacyRequest(
                    id=str(uuid4()),
                    user_id=principal.user_id,
                    request_type="correction",
                    status="completed",
                    scope_sha256=_canonical_sha256(scope),
                    requested_at=now,
                    completed_at=now,
                )
            )
            database.commit()
        return self.overview()

    def create_export(self, *, confirm_sensitive_data: bool) -> dict[str, Any]:
        principal = require_data_principal()
        if not confirm_sensitive_data:
            raise PrivacyError(
                409,
                "sensitive_export_confirmation_required",
                "全量导出可能包含代码、自由文本和收入信息, 必须明确确认。",
            )
        now = self._now()
        self._record_request("export", {"scope": "full_portable_export_v1"}, now)
        tables: dict[str, list[dict[str, Any]]] = {}
        with self._engine.connect() as connection:
            for table in self._private_tables():
                rows = connection.execute(
                    select(table).where(table.c.user_id == principal.user_id)
                ).mappings()
                tables[table.name] = [self._serialized_row(row) for row in rows]
            account = (
                connection.execute(select(InternalUser).where(InternalUser.id == principal.user_id))
                .mappings()
                .one()
            )
            identities = connection.execute(
                select(
                    ExternalIdentity.id,
                    ExternalIdentity.user_id,
                    ExternalIdentity.issuer,
                    ExternalIdentity.subject,
                    ExternalIdentity.created_at,
                    ExternalIdentity.revoked_at,
                ).where(ExternalIdentity.user_id == principal.user_id)
            ).mappings()
            roles = connection.execute(
                select(UserRoleAssignment).where(UserRoleAssignment.user_id == principal.user_id)
            ).mappings()
            state_events = connection.execute(
                select(
                    AccountStateEvent.id,
                    AccountStateEvent.user_id,
                    AccountStateEvent.previous_status,
                    AccountStateEvent.new_status,
                    AccountStateEvent.reason_code,
                    AccountStateEvent.occurred_at,
                ).where(AccountStateEvent.user_id == principal.user_id)
            ).mappings()
            security_events = connection.execute(
                select(
                    AuthSecurityEvent.event_type,
                    AuthSecurityEvent.outcome,
                    AuthSecurityEvent.reason_code,
                    AuthSecurityEvent.correlation_id,
                    AuthSecurityEvent.occurred_at,
                ).where(AuthSecurityEvent.user_id == principal.user_id)
            ).mappings()
        payload = {
            "format": "cloud-study-portable-export",
            "version": "1.0.0",
            "generated_at": now,
            "user_id": principal.user_id,
            "scope": {
                "current_user_only": True,
                "includes_sensitive_user_content": True,
                "excludes": [
                    "credential_secret_values",
                    "session_token_hashes",
                    "oidc_transaction_secrets",
                    "rate_limit_keys",
                    "other_users",
                    "global_managed_content",
                ],
            },
            "account": self._serialized_row(account),
            "external_identities": [self._serialized_row(row) for row in identities],
            "roles": [self._serialized_row(row) for row in roles],
            "account_state_events": [self._serialized_row(row) for row in state_events],
            "security_events": [self._serialized_row(row) for row in security_events],
            "tables": tables,
            "table_counts": {name: len(rows) for name, rows in tables.items()},
        }
        payload["content_sha256"] = _canonical_sha256(payload)
        return payload

    def request_deletion(self, *, reauthenticated_at: datetime) -> dict[str, Any]:
        principal = require_data_principal()
        now = self._now()
        if principal.role == "owner_operator":
            raise PrivacyError(
                409,
                "owner_transfer_required",
                "唯一所有者删除前必须先完成受控的所有者职责转移。",
            )
        if now - _aware(reauthenticated_at) > self.REAUTH_MAX_AGE:
            raise PrivacyError(
                403, "recent_reauthentication_required", "删除账号需要最近的 MFA 认证。"
            )
        job_id = str(uuid4())
        with self._engine.begin() as connection:
            user = (
                connection.execute(select(InternalUser).where(InternalUser.id == principal.user_id))
                .mappings()
                .one_or_none()
            )
            if user is None or user["status"] != "active":
                raise PrivacyError(409, "account_not_active", "账号当前不能进入删除等待期。")
            existing = connection.execute(
                select(PrivacyDeletionJob).where(
                    PrivacyDeletionJob.user_id == principal.user_id,
                    PrivacyDeletionJob.status == "waiting",
                )
            ).first()
            if existing is not None:
                raise PrivacyError(409, "deletion_already_pending", "账号删除已在等待期。")
            connection.execute(
                insert(PrivacyDeletionJob).values(
                    id=job_id,
                    user_id=principal.user_id,
                    status="waiting",
                    requested_at=now,
                    execute_after=now + self.CANCELLATION_WINDOW,
                )
            )
            connection.execute(
                update(InternalUser)
                .where(InternalUser.id == principal.user_id, InternalUser.status == "active")
                .values(status="deletion_pending", updated_at=now, deletion_requested_at=now)
            )
            connection.execute(
                insert(AccountStateEvent).values(
                    id=str(uuid4()),
                    user_id=principal.user_id,
                    actor_user_id=principal.user_id,
                    previous_status="active",
                    new_status="deletion_pending",
                    reason_code="privacy_deletion_requested",
                    occurred_at=now,
                )
            )
            connection.execute(
                update(ApplicationSession)
                .where(
                    ApplicationSession.user_id == principal.user_id,
                    ApplicationSession.revoked_at.is_(None),
                )
                .values(revoked_at=now, revocation_reason="privacy_deletion_requested")
            )
        return self.get_deletion_job(job_id)

    def cancel_deletion(self, *, user_id: str, reauthenticated_at: datetime) -> dict[str, Any]:
        now = self._now()
        if now - _aware(reauthenticated_at) > self.REAUTH_MAX_AGE:
            raise PrivacyError(
                403, "recent_reauthentication_required", "撤销删除需要最近的 MFA 认证。"
            )
        with self._engine.begin() as connection:
            job = (
                connection.execute(
                    select(PrivacyDeletionJob)
                    .where(
                        PrivacyDeletionJob.user_id == user_id,
                        PrivacyDeletionJob.status == "waiting",
                    )
                    .order_by(PrivacyDeletionJob.requested_at.desc())
                )
                .mappings()
                .first()
            )
            if job is None:
                raise PrivacyError(404, "deletion_job_not_found", "没有可撤销的删除作业。")
            if _aware(job["execute_after"]) <= now:
                raise PrivacyError(409, "deletion_cancellation_expired", "删除撤销期已经结束。")
            connection.execute(
                update(PrivacyDeletionJob)
                .where(PrivacyDeletionJob.id == job["id"], PrivacyDeletionJob.status == "waiting")
                .values(status="cancelled", cancelled_at=now)
            )
            connection.execute(
                update(InternalUser)
                .where(InternalUser.id == user_id, InternalUser.status == "deletion_pending")
                .values(status="active", updated_at=now, deletion_requested_at=None)
            )
            connection.execute(
                insert(AccountStateEvent).values(
                    id=str(uuid4()),
                    user_id=user_id,
                    actor_user_id=user_id,
                    previous_status="deletion_pending",
                    new_status="active",
                    reason_code="privacy_deletion_cancelled",
                    occurred_at=now,
                )
            )
        return self.get_deletion_job(str(job["id"]))

    def run_due_deletions(self) -> list[dict[str, Any]]:
        operator = current_principal()
        if operator.account_status != "active" or operator.role != "owner_operator":
            raise PrivacyError(403, "operator_required", "只有所有者运营角色可以执行到期删除。")
        now = self._now()
        with self._engine.connect() as connection:
            job_ids = list(
                connection.execute(
                    select(PrivacyDeletionJob.id).where(
                        PrivacyDeletionJob.status == "waiting",
                        PrivacyDeletionJob.execute_after <= now,
                    )
                ).scalars()
            )
        completed: list[dict[str, Any]] = []
        for job_id in job_ids:
            try:
                with self._engine.begin() as connection:
                    job = (
                        connection.execute(
                            select(PrivacyDeletionJob).where(
                                PrivacyDeletionJob.id == job_id,
                                PrivacyDeletionJob.status == "waiting",
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if job is None:
                        continue
                    self._purge_user(connection, str(job["user_id"]), now)
                    backup_expires_at = now + self.BACKUP_NATURAL_EXPIRY
                    connection.execute(
                        update(PrivacyDeletionJob)
                        .where(PrivacyDeletionJob.id == job_id)
                        .values(
                            status="completed",
                            completed_at=now,
                            backup_expires_at=backup_expires_at,
                            failure_code=None,
                        )
                    )
                    connection.execute(
                        insert(PrivacyDeletionTombstone).values(
                            id=str(uuid4()),
                            deletion_job_id=job_id,
                            user_id=job["user_id"],
                            completed_at=now,
                            backup_expires_at=backup_expires_at,
                            retain_until=now + self.TOMBSTONE_RETENTION,
                        )
                    )
                completed.append(self.get_deletion_job(str(job_id)))
            except Exception:
                with self._engine.begin() as connection:
                    connection.execute(
                        update(PrivacyDeletionJob)
                        .where(PrivacyDeletionJob.id == job_id)
                        .values(status="failed", failure_code="purge_transaction_failed")
                    )
                raise
        return completed

    def export_deletion_ledger(self) -> dict[str, Any]:
        operator = current_principal()
        if operator.account_status != "active" or operator.role != "owner_operator":
            raise PrivacyError(403, "operator_required", "只有所有者运营角色可以导出删除账本。")
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(PrivacyDeletionTombstone).order_by(
                    PrivacyDeletionTombstone.completed_at,
                    PrivacyDeletionTombstone.deletion_job_id,
                )
            ).mappings()
            records = [self._serialized_row(row) for row in rows]
        payload = {
            "format": "cloud-study-deletion-ledger",
            "version": "1.0.0",
            "generated_at": self._now(),
            "records": records,
            "integrity_note": "SHA-256 只检测意外损坏; 恢复流程还必须使用受控备份来源。",
        }
        payload["content_sha256"] = _canonical_sha256(payload)
        return payload

    def reapply_deletion_ledger(self, ledger: Mapping[str, Any]) -> int:
        operator = current_principal()
        if operator.account_status != "active" or operator.role != "owner_operator":
            raise PrivacyError(403, "operator_required", "只有所有者运营角色可以重放删除账本。")
        supplied_hash = ledger.get("content_sha256")
        unsigned = {key: value for key, value in ledger.items() if key != "content_sha256"}
        if not isinstance(supplied_hash, str) or supplied_hash != _canonical_sha256(unsigned):
            raise PrivacyError(422, "deletion_ledger_integrity_failed", "删除账本完整性校验失败。")
        if (
            ledger.get("format") != "cloud-study-deletion-ledger"
            or ledger.get("version") != "1.0.0"
        ):
            raise PrivacyError(422, "deletion_ledger_unsupported", "删除账本版本不受支持。")
        records = ledger.get("records")
        if not isinstance(records, list):
            raise PrivacyError(422, "deletion_ledger_invalid", "删除账本记录无效。")
        now = self._now()
        reapplied = 0
        with self._engine.begin() as connection:
            for record in records:
                if not isinstance(record, dict):
                    raise PrivacyError(422, "deletion_ledger_invalid", "删除账本记录无效。")
                user_id = str(record.get("user_id", ""))
                job_id = str(record.get("deletion_job_id", ""))
                if len(user_id) != 36 or len(job_id) != 36:
                    raise PrivacyError(
                        422, "deletion_ledger_invalid", "删除账本主体或作业标识无效。"
                    )
                user = connection.execute(
                    select(InternalUser.status).where(InternalUser.id == user_id)
                ).scalar_one_or_none()
                if user is not None:
                    self._purge_user(
                        connection, user_id, now, reason="restored_backup_deletion_reapplied"
                    )
                    reapplied += 1
                existing = connection.execute(
                    select(PrivacyDeletionTombstone.id).where(
                        PrivacyDeletionTombstone.deletion_job_id == job_id
                    )
                ).scalar_one_or_none()
                completed_at = datetime.fromisoformat(str(record["completed_at"]))
                backup_expires_at = datetime.fromisoformat(str(record["backup_expires_at"]))
                if existing is None:
                    connection.execute(
                        insert(PrivacyDeletionTombstone).values(
                            id=str(record.get("id") or uuid4()),
                            deletion_job_id=job_id,
                            user_id=user_id,
                            completed_at=completed_at,
                            backup_expires_at=backup_expires_at,
                            retain_until=datetime.fromisoformat(str(record["retain_until"])),
                            last_reapplied_at=now,
                        )
                    )
                else:
                    connection.execute(
                        update(PrivacyDeletionTombstone)
                        .where(PrivacyDeletionTombstone.id == existing)
                        .values(last_reapplied_at=now)
                    )
                existing_job = connection.execute(
                    select(PrivacyDeletionJob.id).where(PrivacyDeletionJob.id == job_id)
                ).scalar_one_or_none()
                if existing_job is None:
                    connection.execute(
                        insert(PrivacyDeletionJob).values(
                            id=job_id,
                            user_id=user_id,
                            status="completed",
                            requested_at=completed_at,
                            execute_after=completed_at,
                            completed_at=completed_at,
                            backup_expires_at=backup_expires_at,
                        )
                    )
                else:
                    connection.execute(
                        update(PrivacyDeletionJob)
                        .where(PrivacyDeletionJob.id == job_id)
                        .values(
                            status="completed",
                            completed_at=completed_at,
                            backup_expires_at=backup_expires_at,
                            failure_code=None,
                        )
                    )
        return reapplied

    def get_deletion_job(self, job_id: str) -> dict[str, Any]:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(PrivacyDeletionJob).where(PrivacyDeletionJob.id == job_id)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise PrivacyError(404, "deletion_job_not_found", "删除作业不存在。")
        return self._job_payload(row)

    def _record_request(self, request_type: str, scope: Any, now: datetime) -> None:
        principal = require_data_principal()
        with self._session_factory() as database:
            database.add(
                PrivacyRequest(
                    id=str(uuid4()),
                    user_id=principal.user_id,
                    request_type=request_type,
                    status="completed",
                    scope_sha256=_canonical_sha256(scope),
                    requested_at=now,
                    completed_at=now,
                )
            )
            database.commit()

    @staticmethod
    def _serialized_row(row: Mapping[str, Any] | RowMapping) -> dict[str, Any]:
        return {key: _json_value(value) for key, value in row.items()}

    @staticmethod
    def _job_payload(
        row: Mapping[str, Any] | RowMapping | PrivacyDeletionJob,
    ) -> dict[str, Any]:
        getter = row.get if isinstance(row, Mapping) else lambda key: getattr(row, key)

        def timestamp(key: str) -> datetime | None:
            value = getter(key)
            return _aware(value) if isinstance(value, datetime) else None

        return {
            "id": getter("id"),
            "status": getter("status"),
            "requested_at": timestamp("requested_at"),
            "execute_after": timestamp("execute_after"),
            "cancelled_at": timestamp("cancelled_at"),
            "completed_at": timestamp("completed_at"),
            "backup_expires_at": timestamp("backup_expires_at"),
            "failure_code": getter("failure_code"),
            "cancellable": getter("status") == "waiting",
        }

    @staticmethod
    def _private_tables() -> list[Table]:
        model_by_table = {
            cast(Table, mapper.local_table).name: mapper.class_ for mapper in Base.registry.mappers
        }
        return [
            table
            for table in Base.metadata.sorted_tables
            if isinstance(model_by_table.get(table.name), type)
            and issubclass(model_by_table[table.name], UserOwnedMixin)
        ]

    def _purge_user(
        self,
        connection: Any,
        user_id: str,
        now: datetime,
        *,
        reason: str = "privacy_deletion_completed",
    ) -> None:
        for table in reversed(self._private_tables()):
            connection.execute(delete(table).where(table.c.user_id == user_id))
        connection.execute(delete(ApplicationSession).where(ApplicationSession.user_id == user_id))
        connection.execute(delete(ExternalIdentity).where(ExternalIdentity.user_id == user_id))
        connection.execute(delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user_id))
        current_status = connection.execute(
            select(InternalUser.status).where(InternalUser.id == user_id)
        ).scalar_one_or_none()
        if current_status is not None and current_status != "deleted":
            connection.execute(
                update(InternalUser)
                .where(InternalUser.id == user_id)
                .values(
                    status="deleted",
                    updated_at=now,
                    deletion_requested_at=None,
                    deleted_at=now,
                )
            )
            connection.execute(
                insert(AccountStateEvent).values(
                    id=str(uuid4()),
                    user_id=user_id,
                    actor_user_id=None,
                    previous_status=current_status,
                    new_status="deleted",
                    reason_code=reason,
                    occurred_at=now,
                )
            )
