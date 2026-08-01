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


class MasteryEvidence(Base):
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


class RunnerInvocation(Base):
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


class UserGoalSelection(Base):
    __tablename__ = "user_goal_selections"
    __table_args__ = (
        CheckConstraint(
            "goal_kind IN ('learning', 'exam', 'employment', 'freelancing', "
            "'productization', 'other')",
            name="ck_user_goal_selections_kind",
        ),
        Index(
            "uq_active_user_goal_scope",
            "skill_id",
            "skill_version",
            "capability_scope_id",
            unique=True,
            sqlite_where=text("superseded_at IS NULL"),
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
        CheckConstraint("synthetic = 1", name="ck_market_evidence_5a_synthetic"),
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


class ReadinessEvaluation(Base):
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


class PathComparison(Base):
    __tablename__ = "path_comparisons"
    __table_args__ = (
        CheckConstraint("synthetic = 1", name="ck_path_comparisons_5a_synthetic"),
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


class PathComparisonDecision(Base):
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


class ReadinessEvent(Base):
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


class MarketResearchRun(Base):
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
            "catalog_id",
            "catalog_version",
            unique=True,
            sqlite_where=text(
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


class MarketResearchSynthesisAttempt(Base):
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


class MarketResearchEvent(Base):
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
