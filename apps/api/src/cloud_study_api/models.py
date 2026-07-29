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


class DiagnosticSession(Base):
    __tablename__ = "diagnostic_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'ended', 'failed', 'plan_saved')",
            name="ck_diagnostic_sessions_status",
        ),
        Index(
            "uq_active_diagnostic_skill_version",
            "skill_id",
            "skill_version",
            unique=True,
            sqlite_where=text("status = 'active'"),
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


class DiagnosticAnswer(Base):
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


class DiagnosticEvent(Base):
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


class PlanningProposal(Base):
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


class PlanningUnit(Base):
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


class PlanningUnitSource(Base):
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


class PlanningChangeEvent(Base):
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


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_notification_preferences_singleton"),
        CheckConstraint(
            "smtp_security IN ('starttls', 'ssl')",
            name="ck_notification_preferences_smtp_security",
        ),
        CheckConstraint(
            "email_delay_minutes >= 0",
            name="ck_notification_preferences_delay",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
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


class Notification(Base):
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


class EmailOutbox(Base):
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


class AiProviderProfile(Base):
    __tablename__ = "ai_provider_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
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


class LearningRun(Base):
    __tablename__ = "learning_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'retention_pending', 'completed', 'ended')",
            name="ck_learning_runs_status",
        ),
        Index(
            "uq_nonterminal_learning_run_skill_version",
            "skill_id",
            "skill_version",
            unique=True,
            sqlite_where=text("status IN ('active', 'retention_pending')"),
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
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(100))


class LearningRunLock(Base):
    __tablename__ = "learning_run_locks"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    lock_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    lock_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningUnitInstance(Base):
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


class LearningActivity(Base):
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


class ActivityAttempt(Base):
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


class ActivityEvaluation(Base):
    __tablename__ = "activity_evaluations"
    __table_args__ = (
        CheckConstraint(
            "method IN ('deterministic', 'self_review', 'review_pending', 'not_executable')",
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


class MasteryEvidence(Base):
    __tablename__ = "mastery_evidence"
    __table_args__ = (
        CheckConstraint(
            "dimension IN ('understanding', 'operation', 'transfer', "
            "'artifact', 'retention', 'correction')",
            name="ck_mastery_evidence_dimension",
        ),
        CheckConstraint(
            "strength IN ('limited', 'supported', 'retained_limited')",
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("activity_attempts.id"),
    )


class MasterySnapshot(Base):
    __tablename__ = "mastery_snapshots"
    __table_args__ = (
        CheckConstraint(
            "dimension IN ('understanding', 'operation', 'transfer', "
            "'artifact', 'retention', 'correction')",
            name="ck_mastery_snapshots_dimension",
        ),
        CheckConstraint(
            "evidence_level IN ('none', 'limited', 'supported')",
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


class ReviewTask(Base):
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


class LearningEvent(Base):
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
