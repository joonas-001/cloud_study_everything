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
