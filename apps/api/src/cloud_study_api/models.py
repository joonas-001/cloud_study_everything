from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UserOwnedMixin:
    """Marker and required owner column for every private business object."""

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class InternalUser(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended', 'deletion_pending', 'deleted')",
            name="ck_users_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_external_identity_subject"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserRoleAssignment(Base):
    __tablename__ = "user_role_assignments"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'owner_operator', 'support_restricted')",
            name="ck_user_role_assignments_role",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountStateEvent(Base):
    __tablename__ = "account_state_events"
    __table_args__ = (
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('active', 'suspended', 'deletion_pending', 'deleted')",
            name="ck_account_state_events_previous_status",
        ),
        CheckConstraint(
            "new_status IN ('active', 'suspended', 'deletion_pending', 'deleted')",
            name="ck_account_state_events_new_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    previous_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountInvitation(Base):
    __tablename__ = "account_invitations"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'support_restricted')",
            name="ck_account_invitations_role",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_account_invitations_positive_lifetime",
        ),
        CheckConstraint(
            "(accepted_at IS NULL AND accepted_by_user_id IS NULL) OR "
            "(accepted_at IS NOT NULL AND accepted_by_user_id IS NOT NULL)",
            name="ck_account_invitations_acceptance_pair",
        ),
        CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL",
            name="ck_account_invitations_single_terminal_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    accepted_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OidcLoginTransaction(Base):
    __tablename__ = "oidc_login_transactions"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at",
            name="ck_oidc_login_transactions_positive_lifetime",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    nonce_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_pkce_verifier: Mapped[str] = mapped_column(Text, nullable=False)
    invitation_id: Mapped[str | None] = mapped_column(
        ForeignKey("account_invitations.id", ondelete="RESTRICT"), index=True
    )
    prior_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("application_sessions.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationSession(Base):
    __tablename__ = "application_sessions"
    __table_args__ = (
        CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_application_sessions_idle_within_absolute",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mfa_authenticated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(100))


class AuthSecurityEvent(Base):
    __tablename__ = "auth_security_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthRateLimitBucket(Base):
    __tablename__ = "auth_rate_limit_buckets"
    __table_args__ = (
        UniqueConstraint("action", "key_sha256", name="uq_auth_rate_limit_bucket"),
        CheckConstraint(
            "attempt_count >= 1",
            name="ck_auth_rate_limit_buckets_positive_attempts",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    key_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)


class PrivacyPolicyAcceptance(UserOwnedMixin, Base):
    __tablename__ = "privacy_policy_acceptances"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "document_type",
            "document_version",
            "content_sha256",
            name="uq_privacy_policy_acceptance_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    document_version: Mapped[str] = mapped_column(String(40), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PrivacyChoice(UserOwnedMixin, Base):
    __tablename__ = "privacy_choices"
    __table_args__ = (
        UniqueConstraint("user_id", "purpose", name="uq_privacy_choice_purpose"),
        CheckConstraint(
            "purpose IN ('external_ai', 'external_sources', 'email_notifications', "
            "'support_diagnostics')",
            name="ck_privacy_choices_purpose",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notice_version: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PrivacyRequest(UserOwnedMixin, Base):
    __tablename__ = "privacy_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('access', 'correction', 'export')",
            name="ck_privacy_requests_type",
        ),
        CheckConstraint(
            "status IN ('completed', 'failed')",
            name="ck_privacy_requests_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PrivacyDeletionJob(Base):
    __tablename__ = "privacy_deletion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting', 'cancelled', 'completed', 'failed')",
            name="ck_privacy_deletion_jobs_status",
        ),
        Index(
            "uq_privacy_deletion_job_waiting_user",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'waiting'"),
            postgresql_where=text("status = 'waiting'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Deliberately opaque and without a foreign key so the minimal deletion ledger
    # remains enforceable even after identity bindings and private rows are removed.
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    execute_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backup_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))


class PrivacyDeletionTombstone(Base):
    __tablename__ = "privacy_deletion_tombstones"
    __table_args__ = (
        UniqueConstraint("deletion_job_id", name="uq_privacy_deletion_tombstone_job"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    deletion_job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    backup_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_reapplied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportCase(UserOwnedMixin, Base):
    __tablename__ = "support_cases"
    __table_args__ = (
        CheckConstraint(
            "category IN ('product_support', 'account_recovery', 'security_vulnerability', "
            "'privacy_request', 'content_correction', 'abuse_appeal')",
            name="ck_support_cases_category",
        ),
        CheckConstraint(
            "status IN ('open', 'waiting_user', 'resolved', 'closed')",
            name="ck_support_cases_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    summary: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportAccessGrant(Base):
    __tablename__ = "support_access_grants"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'active', 'denied', 'revoked', 'expired')",
            name="ck_support_access_grants_status",
        ),
        CheckConstraint(
            "scope IN ('ticket_metadata', 'case_content')",
            name="ck_support_access_grants_scope",
        ),
        CheckConstraint(
            "expires_at > requested_at",
            name="ck_support_access_grants_positive_lifetime",
        ),
        CheckConstraint(
            "(status != 'active') OR (approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_support_access_grants_active_approval",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("support_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    support_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    incident_reference: Mapped[str | None] = mapped_column(String(80))
    emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post_notice_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationsControl(Base):
    __tablename__ = "operations_controls"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_operations_controls_singleton"),
        CheckConstraint(
            "service_mode IN ('normal', 'read_only', 'stopped')",
            name="ck_operations_controls_service_mode",
        ),
        CheckConstraint("revision >= 1", name="ck_operations_controls_positive_revision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    service_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="normal")
    invitations_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    runner_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    external_ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    external_sources_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationsQuotaBucket(Base):
    __tablename__ = "operations_quota_buckets"
    __table_args__ = (
        UniqueConstraint(
            "capability", "principal_hash", name="uq_operations_quota_capability_principal"
        ),
        CheckConstraint("used_count >= 0", name="ck_operations_quota_nonnegative_usage"),
        CheckConstraint("active_count >= 0", name="ck_operations_quota_nonnegative_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
    principal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationsAuditEvent(Base):
    __tablename__ = "operations_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_hash: Mapped[str | None] = mapped_column(String(64))
    case_id: Mapped[str | None] = mapped_column(String(36), index=True)
    grant_id: Mapped[str | None] = mapped_column(String(36), index=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class OperationsMetric(Base):
    __tablename__ = "operations_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    principal_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_app_settings_singleton"),
        CheckConstraint(
            "inactivity_timeout_minutes >= 1",
            name="ck_app_settings_positive_timeout",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    external_ai_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    inactivity_timeout_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=120,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class UserSettings(UserOwnedMixin, Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_settings_user"),
        CheckConstraint(
            "inactivity_timeout_minutes >= 1",
            name="ck_user_settings_positive_timeout",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    inactivity_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class DiagnosticSession(UserOwnedMixin, Base):
    __tablename__ = "diagnostic_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'ended', 'failed', 'plan_saved')",
            name="ck_diagnostic_sessions_status",
        ),
        Index(
            "uq_active_diagnostic_skill_version",
            "user_id",
            "skill_id",
            "skill_version",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    is_preview: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    credential_reference: Mapped[str | None] = mapped_column(String(255))
    external_ai_consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    external_ai_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
    )
    current_question_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(100))


class DiagnosticAnswer(UserOwnedMixin, Base):
    __tablename__ = "diagnostic_answers"
    __table_args__ = (
        CheckConstraint(
            "response_kind IN ('answered', 'skipped', 'uncertain')",
            name="ck_diagnostic_answers_response_kind",
        ),
        UniqueConstraint(
            "session_id",
            "question_id",
            "revision",
            name="uq_diagnostic_answer_revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("diagnostic_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[str] = mapped_column(String(100), nullable=False)
    response_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_answer_id: Mapped[str | None] = mapped_column(ForeignKey("diagnostic_answers.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class DiagnosticEvent(UserOwnedMixin, Base):
    __tablename__ = "diagnostic_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("diagnostic_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class SourceCheckRun(Base):
    __tablename__ = "source_check_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'completed_with_failures')",
            name="ck_source_check_runs_status",
        ),
        Index(
            "uq_automatic_source_check_local_date",
            "skill_id",
            "skill_version",
            "local_date",
            unique=True,
            sqlite_where=text("trigger = 'automatic'"),
            postgresql_where=text("trigger = 'automatic'"),
        ),
        CheckConstraint(
            "trigger IN ('automatic', 'manual')",
            name="ck_source_check_runs_trigger",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    local_date: Mapped[str] = mapped_column(String(10), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    checked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceCheckResult(Base):
    __tablename__ = "source_check_results"
    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('baseline_created', 'unchanged', 'changed', 'failed', 'manual', 'indeterminate')",
            name="ck_source_check_results_status",
        ),
        UniqueConstraint("run_id", "source_id", name="uq_source_check_result_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("source_check_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(String(500))
    last_modified: Mapped[str | None] = mapped_column(String(500))
    final_url: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceChangeCandidate(Base):
    __tablename__ = "source_change_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'dismissed', 'accepted')",
            name="ck_source_change_candidates_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    change_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanningProposal(UserOwnedMixin, Base):
    __tablename__ = "planning_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'saved_preview', 'rejected', 'frozen_preview')",
            name="ck_planning_proposals_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    diagnostic_session_id: Mapped[str] = mapped_column(
        ForeignKey("diagnostic_sessions.id"),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    template_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    is_preview: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    limitations_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlanningUnit(UserOwnedMixin, Base):
    __tablename__ = "planning_units"
    __table_args__ = (
        UniqueConstraint("proposal_id", "sequence", name="uq_planning_unit_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("planning_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_unit_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_criteria_json: Mapped[str] = mapped_column(Text, nullable=False)


class PlanningUnitSource(UserOwnedMixin, Base):
    __tablename__ = "planning_unit_sources"
    __table_args__ = (
        UniqueConstraint(
            "planning_unit_id",
            "source_id",
            name="uq_planning_unit_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    planning_unit_id: Mapped[str] = mapped_column(
        ForeignKey("planning_units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)


class PlanningChangeEvent(UserOwnedMixin, Base):
    __tablename__ = "planning_change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("planning_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NotificationPreference(UserOwnedMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_notification_preferences_user"),
        CheckConstraint(
            "smtp_security IN ('starttls', 'ssl')",
            name="ck_notification_preferences_smtp_security",
        ),
        CheckConstraint(
            "email_delay_minutes >= 0",
            name="ck_notification_preferences_delay",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_action_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    email_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    recipient_email: Mapped[str | None] = mapped_column(String(320))
    sender_email: Mapped[str | None] = mapped_column(String(320))
    smtp_host: Mapped[str | None] = mapped_column(String(255))
    smtp_port: Mapped[int | None] = mapped_column(Integer)
    smtp_username: Mapped[str | None] = mapped_column(String(320))
    smtp_security: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="starttls",
    )
    credential_reference: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Notification(UserOwnedMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('required', 'action_required', 'warning', 'info')",
            name="ck_notifications_severity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    related_type: Mapped[str | None] = mapped_column(String(100))
    related_id: Mapped[str | None] = mapped_column(String(100))
    deduplication_key: Mapped[str | None] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailOutbox(UserOwnedMixin, Base):
    __tablename__ = "email_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'sent', 'cancelled', 'failed')",
            name="ck_email_outbox_status",
        ),
        UniqueConstraint("notification_id", name="uq_email_outbox_notification"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    notification_id: Mapped[str] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiProviderProfile(UserOwnedMixin, Base):
    __tablename__ = "ai_provider_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(100))
    base_url: Mapped[str | None] = mapped_column(Text)
    credential_reference: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SkillVersionContentLock(Base):
    __tablename__ = "skill_version_content_locks"
    __table_args__ = (
        UniqueConstraint(
            "skill_id",
            "skill_version",
            name="uq_skill_version_content_lock",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_lock_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_lock_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningRun(UserOwnedMixin, Base):
    __tablename__ = "learning_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused', 'retention_pending', 'completed', 'ended')",
            name="ck_learning_runs_status",
        ),
        Index(
            "uq_nonterminal_learning_run_skill_version",
            "user_id",
            "skill_id",
            "skill_version",
            unique=True,
            sqlite_where=text("status IN ('active', 'paused', 'retention_pending')"),
            postgresql_where=text("status IN ('active', 'paused', 'retention_pending')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    planning_proposal_id: Mapped[str] = mapped_column(
        ForeignKey("planning_proposals.id"),
        nullable=False,
        index=True,
    )
    diagnostic_session_id: Mapped[str] = mapped_column(
        ForeignKey("diagnostic_sessions.id"),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_preview: Mapped[bool] = mapped_column(Boolean, nullable=False)
    selected_historical_plan: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reused_from_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_runs.id"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pause_reason: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(100))


class LearningRunLock(UserOwnedMixin, Base):
    __tablename__ = "learning_run_locks"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    lock_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    lock_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningUnitInstance(UserOwnedMixin, Base):
    __tablename__ = "learning_unit_instances"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'completed')",
            name="ck_learning_unit_instances_status",
        ),
        UniqueConstraint("run_id", "sequence", name="uq_learning_unit_instance_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    template_unit_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningActivity(UserOwnedMixin, Base):
    __tablename__ = "learning_activities"
    __table_args__ = (
        CheckConstraint(
            "activity_type IN "
            "('study', 'explanation', 'structured_check', 'code_text', 'transfer', "
            "'correction', 'project_evidence', 'review')",
            name="ck_learning_activities_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'available', 'completed', 'correction_required')",
            name="ck_learning_activities_status",
        ),
        UniqueConstraint("run_id", "sequence", name="uq_learning_activity_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    unit_instance_id: Mapped[str] = mapped_column(
        ForeignKey("learning_unit_instances.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    template_activity_id: Mapped[str] = mapped_column(String(150), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityAttempt(UserOwnedMixin, Base):
    __tablename__ = "activity_attempts"
    __table_args__ = (
        UniqueConstraint("activity_id", "revision", name="uq_activity_attempt_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("learning_activities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    submission_json: Mapped[str] = mapped_column(Text, nullable=False)
    corrects_attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("activity_attempts.id"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActivityEvaluation(UserOwnedMixin, Base):
    __tablename__ = "activity_evaluations"
    __table_args__ = (
        CheckConstraint(
            "method IN "
            "('deterministic', 'self_review', 'review_pending', 'not_executable', 'runner')",
            name="ck_activity_evaluations_method",
        ),
        CheckConstraint(
            "result IN ('passed', 'failed', 'submitted', 'uncertain', "
            "'review_pending', 'not_executable')",
            name="ck_activity_evaluations_result",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("activity_attempts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    rubric_id: Mapped[str | None] = mapped_column(String(100))
    detail_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MasteryEvidence(UserOwnedMixin, Base):
    __tablename__ = "mastery_evidence"
    __table_args__ = (
        CheckConstraint(
            "dimension IN ('understanding', 'operation', 'transfer', "
            "'artifact', 'retention', 'correction')",
            name="ck_mastery_evidence_dimension",
        ),
        CheckConstraint(
            "strength IN ('limited', 'supported', 'retained_limited', 'verified', 'retained')",
            name="ck_mastery_evidence_strength",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("learning_activities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("activity_attempts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("activity_evaluations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    criterion_id: Mapped[str] = mapped_column(String(100), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    strength: Mapped[str] = mapped_column(String(32), nullable=False)
    review_flags_json: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(50), nullable=False)
    capability_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("activity_attempts.id"),
    )


class MasterySnapshot(UserOwnedMixin, Base):
    __tablename__ = "mastery_snapshots"
    __table_args__ = (
        CheckConstraint(
            "dimension IN ('understanding', 'operation', 'transfer', "
            "'artifact', 'retention', 'correction')",
            name="ck_mastery_snapshots_dimension",
        ),
        CheckConstraint(
            "evidence_level IN ('none', 'limited', 'supported', 'verified', 'retained')",
            name="ck_mastery_snapshots_level",
        ),
        UniqueConstraint("run_id", "dimension", name="uq_mastery_snapshot_dimension"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_level: Mapped[str] = mapped_column(String(32), nullable=False)
    review_flags_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewTask(UserOwnedMixin, Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'available', 'passed', 'failed')",
            name="ck_review_tasks_status",
        ),
        UniqueConstraint(
            "run_id",
            "checkpoint_index",
            "attempt_number",
            name="uq_review_task_checkpoint_attempt",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    activity_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_activities.id", ondelete="RESTRICT"),
    )
    checkpoint_index: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningEvent(UserOwnedMixin, Base):
    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningIndependentReview(UserOwnedMixin, Base):
    __tablename__ = "learning_independent_reviews"
    __table_args__ = (
        CheckConstraint(
            "dimension IN ('understanding', 'operation', 'transfer', "
            "'artifact', 'retention', 'correction')",
            name="ck_learning_independent_reviews_dimension",
        ),
        CheckConstraint(
            "conclusion IN ('meets', 'needs_work', 'uncertain')",
            name="ck_learning_independent_reviews_conclusion",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    activity_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_activities.id", ondelete="RESTRICT")
    )
    capability_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_relationship: Mapped[str] = mapped_column(String(200), nullable=False)
    rubric_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(50), nullable=False)
    conclusion: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunnerInvocation(UserOwnedMixin, Base):
    __tablename__ = "runner_invocations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'passed', 'failed', 'timeout', "
            "'output_limit', 'infrastructure_error')",
            name="ck_runner_invocations_status",
        ),
        Index(
            "uq_active_runner_invocation",
            "singleton_key",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    singleton_key: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("learning_activities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("activity_attempts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    protocol_version: Mapped[str] = mapped_column(String(20), nullable=False)
    task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    runtime_profile_id: Mapped[str] = mapped_column(String(100), nullable=False)
    runtime_profile_version: Mapped[str] = mapped_column(String(50), nullable=False)
    runtime_image: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    result_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserGoalSelection(UserOwnedMixin, Base):
    __tablename__ = "user_goal_selections"
    __table_args__ = (
        CheckConstraint(
            "goal_kind IN ('learning', 'exam', 'employment', 'freelancing', "
            "'productization', 'other')",
            name="ck_user_goal_selections_kind",
        ),
        Index(
            "uq_active_user_goal_scope",
            "user_id",
            "skill_id",
            "skill_version",
            "capability_scope_id",
            unique=True,
            sqlite_where=text("superseded_at IS NULL"),
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    capability_scope_id: Mapped[str] = mapped_column(String(100), nullable=False)
    goal_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    custom_label: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReadinessPolicySnapshot(Base):
    __tablename__ = "readiness_policy_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "policy_id",
            "policy_version",
            name="uq_readiness_policy_snapshot",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketEvidenceSnapshot(Base):
    __tablename__ = "market_evidence_snapshots"
    __table_args__ = (
        CheckConstraint("synthetic = true", name="ck_market_evidence_5a_synthetic"),
        CheckConstraint(
            "freshness_status IN ('current', 'stale', 'conflicted', 'indeterminate')",
            name="ck_market_evidence_freshness",
        ),
        UniqueConstraint(
            "fixture_id",
            "fixture_version",
            name="uq_market_evidence_snapshot",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fixture_id: Mapped[str] = mapped_column(String(100), nullable=False)
    fixture_version: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    freshness_status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReadinessEvaluation(UserOwnedMixin, Base):
    __tablename__ = "readiness_evaluations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('not_applicable', 'not_ready', 'review_required', "
            "'comparison_ready', 'experiment_ready')",
            name="ck_readiness_evaluations_status",
        ),
        CheckConstraint(
            "status != 'experiment_ready'",
            name="ck_readiness_5a_no_experiment_ready",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    goal_selection_id: Mapped[str] = mapped_column(
        ForeignKey("user_goal_selections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    learning_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        index=True,
    )
    policy_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("readiness_policy_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    market_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("market_evidence_snapshots.id", ondelete="RESTRICT"),
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    limitations_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PathComparison(UserOwnedMixin, Base):
    __tablename__ = "path_comparisons"
    __table_args__ = (
        CheckConstraint("synthetic = true", name="ck_path_comparisons_5a_synthetic"),
        UniqueConstraint("evaluation_id", name="uq_path_comparison_evaluation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("readiness_evaluations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    market_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("market_evidence_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    comparison_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PathComparisonDecision(UserOwnedMixin, Base):
    __tablename__ = "path_comparison_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('accepted', 'rejected', 'deferred')",
            name="ck_path_comparison_decisions_value",
        ),
        UniqueConstraint(
            "comparison_id",
            "revision",
            name="uq_path_comparison_decision_revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    comparison_id: Mapped[str] = mapped_column(
        ForeignKey("path_comparisons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReadinessEvent(UserOwnedMixin, Base):
    __tablename__ = "readiness_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_selection_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_goal_selections.id", ondelete="RESTRICT"),
        index=True,
    )
    evaluation_id: Mapped[str | None] = mapped_column(
        ForeignKey("readiness_evaluations.id", ondelete="RESTRICT"),
        index=True,
    )
    comparison_id: Mapped[str | None] = mapped_column(
        ForeignKey("path_comparisons.id", ondelete="RESTRICT"),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketResearchRun(UserOwnedMixin, Base):
    __tablename__ = "market_research_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('source_pending', 'synthesis_pending', 'synthesis_in_progress', "
            "'recovery_required', 'review_pending', 'completed', 'blocked', 'failed')",
            name="ck_market_research_runs_status",
        ),
        CheckConstraint(
            "review_status IN ('not_ready', 'not_requested', 'pending', 'accepted', 'rejected')",
            name="ck_market_research_runs_review_status",
        ),
        CheckConstraint(
            "estimated_cost_micros >= 0 AND actual_cost_micros >= 0 AND accounted_cost_micros >= 0",
            name="ck_market_research_runs_nonnegative_cost",
        ),
        Index(
            "uq_active_market_research_run",
            "user_id",
            "catalog_id",
            "catalog_version",
            unique=True,
            sqlite_where=text(
                "status IN ('source_pending', 'synthesis_pending', "
                "'synthesis_in_progress', 'review_pending')"
            ),
            postgresql_where=text(
                "status IN ('source_pending', 'synthesis_pending', "
                "'synthesis_in_progress', 'review_pending')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(String(100), nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(50), nullable=False)
    catalog_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    capability_scope_id: Mapped[str] = mapped_column(String(100), nullable=False)
    goal_selection_id: Mapped[str] = mapped_column(
        ForeignKey("user_goal_selections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    goal_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    goal_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    readiness_evaluation_id: Mapped[str | None] = mapped_column(
        ForeignKey("readiness_evaluations.id", ondelete="RESTRICT"),
        index=True,
    )
    scope_json: Mapped[str] = mapped_column(Text, nullable=False)
    budget_policy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    budget_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    budget_policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    budget_policy_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_profile_id: Mapped[str] = mapped_column(
        ForeignKey("ai_provider_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    response_model_id: Mapped[str | None] = mapped_column(String(100))
    credential_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    external_ai_consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_results_json: Mapped[str] = mapped_column(Text, nullable=False)
    synthesis_json: Mapped[str | None] = mapped_column(Text)
    synthesis_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    synthesis_attempt_id: Mapped[str | None] = mapped_column(String(36))
    synthesis_invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_accounted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    estimated_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accounted_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketResearchSynthesisAttempt(UserOwnedMixin, Base):
    __tablename__ = "market_research_synthesis_attempts"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('claimed', 'dispatch_started', 'response_received', "
            "'accounted', 'recovery_required', 'failed')",
            name="ck_market_research_attempts_phase",
        ),
        CheckConstraint(
            "reserved_cost_micros >= 0 AND accounted_cost_micros >= 0",
            name="ck_market_research_attempts_nonnegative_cost",
        ),
        UniqueConstraint("run_id", name="uq_market_research_attempt_run"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("market_research_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    response_model_id: Mapped[str | None] = mapped_column(String(100))
    budget_policy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    budget_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    reserved_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False)
    accounted_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    charge_status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_sha256: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatch_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accounted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketResearchEvent(UserOwnedMixin, Base):
    __tablename__ = "market_research_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("market_research_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentPolicySnapshot(Base):
    __tablename__ = "experiment_policy_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "policy_id",
            "policy_version",
            name="uq_experiment_policy_snapshot",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MonetizationExperiment(UserOwnedMixin, Base):
    __tablename__ = "monetization_experiments"
    __table_args__ = (
        CheckConstraint(
            "path IN ('employment', 'freelancing', 'productization')",
            name="ck_monetization_experiments_path",
        ),
        CheckConstraint(
            "status IN ('draft', 'rejected', 'blocked', 'approved', 'active', "
            "'paused', 'ended', 'completed')",
            name="ck_monetization_experiments_status",
        ),
        CheckConstraint(
            "gate_level IN ('draft_only', 'local_ready', 'action_ready', 'blocked')",
            name="ck_monetization_experiments_gate",
        ),
        CheckConstraint(
            "time_budget_minutes > 0 AND cost_cap_minor >= 0",
            name="ck_monetization_experiments_budgets",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    goal_selection_id: Mapped[str] = mapped_column(
        ForeignKey("user_goal_selections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    learning_run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    market_research_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("market_research_runs.id", ondelete="RESTRICT"),
        index=True,
    )
    policy_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("experiment_policy_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    skill_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_scope_id: Mapped[str] = mapped_column(String(100), nullable=False)
    path: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    target_audience: Mapped[str] = mapped_column(String(500), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    planned_action: Mapped[str] = mapped_column(Text, nullable=False)
    success_metric: Mapped[str] = mapped_column(Text, nullable=False)
    time_budget_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_cap_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    gate_level: Mapped[str] = mapped_column(String(32), nullable=False)
    gate_reasons_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExperimentIndependentReview(UserOwnedMixin, Base):
    __tablename__ = "experiment_independent_reviews"
    __table_args__ = (
        CheckConstraint(
            "dimension IN ('transfer', 'artifact')",
            name="ck_experiment_reviews_dimension",
        ),
        CheckConstraint(
            "reviewer_relationship IN "
            "('peer', 'mentor', 'instructor', 'employer', 'client', 'other')",
            name="ck_experiment_reviews_relationship",
        ),
        CheckConstraint(
            "conclusion IN ('passed', 'needs_work')",
            name="ck_experiment_reviews_conclusion",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("monetization_experiments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_relationship: Mapped[str] = mapped_column(String(32), nullable=False)
    review_scope: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(50), nullable=False)
    conclusion: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentActionRecord(UserOwnedMixin, Base):
    __tablename__ = "experiment_action_records"
    __table_args__ = (
        CheckConstraint(
            "action_kind IN ('application', 'interview', 'networking', 'portfolio_share', 'other')",
            name="ck_experiment_actions_kind",
        ),
        CheckConstraint(
            "result IN "
            "('pending', 'response', 'no_response', 'interview', 'rejected', "
            "'offer', 'withdrawn', 'other')",
            name="ck_experiment_actions_result",
        ),
        CheckConstraint(
            "user_confirmed_external = true",
            name="ck_experiment_actions_user_confirmed",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("monetization_experiments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    user_confirmed_external: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentOutcome(UserOwnedMixin, Base):
    __tablename__ = "experiment_outcomes"
    __table_args__ = (
        CheckConstraint(
            "hypothesis_result IN ('supported', 'not_supported', 'inconclusive')",
            name="ck_experiment_outcomes_result",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("monetization_experiments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    hypothesis_result: Mapped[str] = mapped_column(String(32), nullable=False)
    observable_result: Mapped[str] = mapped_column(Text, nullable=False)
    learning_gap_dimension: Mapped[str | None] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentIncomeRecord(UserOwnedMixin, Base):
    __tablename__ = "experiment_income_records"
    __table_args__ = (
        CheckConstraint(
            "current_revision >= 1",
            name="ck_experiment_income_current_revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("monetization_experiments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExperimentIncomeRevision(UserOwnedMixin, Base):
    __tablename__ = "experiment_income_revisions"
    __table_args__ = (
        UniqueConstraint(
            "income_record_id",
            "revision",
            name="uq_experiment_income_revision",
        ),
        CheckConstraint(
            "amount_basis IS NULL OR amount_basis IN ('tax_inclusive', 'pre_tax')",
            name="ck_experiment_income_basis",
        ),
        CheckConstraint(
            "verification_level IS NULL OR verification_level IN "
            "('self_reported', 'platform_record', 'received')",
            name="ck_experiment_income_verification",
        ),
        CheckConstraint(
            "(gross_amount_minor IS NULL OR gross_amount_minor >= 0) AND "
            "(platform_fee_minor IS NULL OR platform_fee_minor >= 0) AND "
            "(direct_cost_minor IS NULL OR direct_cost_minor >= 0) AND "
            "(received_amount_minor IS NULL OR received_amount_minor >= 0)",
            name="ck_experiment_income_nonnegative",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    income_record_id: Mapped[str] = mapped_column(
        ForeignKey("experiment_income_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    amount_basis: Mapped[str | None] = mapped_column(String(32))
    gross_amount_minor: Mapped[int | None] = mapped_column(Integer)
    platform_fee_minor: Mapped[int | None] = mapped_column(Integer)
    direct_cost_minor: Mapped[int | None] = mapped_column(Integer)
    received_amount_minor: Mapped[int | None] = mapped_column(Integer)
    verification_level: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    occurred_on: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentFeedbackSuggestion(UserOwnedMixin, Base):
    __tablename__ = "experiment_feedback_suggestions"
    __table_args__ = (
        CheckConstraint(
            "suggestion_type IN "
            "('diagnostic_question', 'correction', 'review', 'project', "
            "'supplemental_unit', 'replanning', 'source_review', 'pause_path')",
            name="ck_experiment_feedback_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'withdrawn')",
            name="ck_experiment_feedback_status",
        ),
        CheckConstraint(
            "estimated_minutes >= 0",
            name="ck_experiment_feedback_minutes",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("monetization_experiments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    outcome_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiment_outcomes.id", ondelete="RESTRICT"),
        index=True,
    )
    suggestion_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs_json: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_impact: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExperimentEvent(UserOwnedMixin, Base):
    __tablename__ = "experiment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("monetization_experiments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
