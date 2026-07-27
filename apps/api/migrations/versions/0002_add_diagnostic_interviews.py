"""Add privacy settings and diagnostic interview persistence.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-27
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "external_ai_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "inactivity_timeout_minutes",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_app_settings_singleton"),
        sa.CheckConstraint(
            "inactivity_timeout_minutes >= 1",
            name="ck_app_settings_positive_timeout",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "app_settings",
            sa.column("id", sa.Integer()),
            sa.column("external_ai_enabled", sa.Boolean()),
            sa.column("inactivity_timeout_minutes", sa.Integer()),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "external_ai_enabled": False,
                "inactivity_timeout_minutes": 120,
                "updated_at": datetime.now(UTC),
            }
        ],
    )

    op.create_table(
        "diagnostic_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=100), nullable=False),
        sa.Column("skill_version", sa.String(length=50), nullable=False),
        sa.Column("is_preview", sa.Boolean(), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("credential_reference", sa.String(length=255), nullable=True),
        sa.Column("external_ai_consent", sa.Boolean(), nullable=False),
        sa.Column("external_ai_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_question_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'ended', 'failed', 'plan_saved')",
            name="ck_diagnostic_sessions_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_active_diagnostic_skill_version",
        "diagnostic_sessions",
        ["skill_id", "skill_version"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "diagnostic_answers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=100), nullable=False),
        sa.Column("response_kind", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_answer_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "response_kind IN ('answered', 'skipped', 'uncertain')",
            name="ck_diagnostic_answers_response_kind",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["diagnostic_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_answer_id"],
            ["diagnostic_answers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "question_id",
            "revision",
            name="uq_diagnostic_answer_revision",
        ),
    )
    op.create_index(
        "ix_diagnostic_answers_session_id",
        "diagnostic_answers",
        ["session_id"],
    )

    op.create_table(
        "diagnostic_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["diagnostic_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_diagnostic_events_session_id",
        "diagnostic_events",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_diagnostic_events_session_id", table_name="diagnostic_events")
    op.drop_table("diagnostic_events")
    op.drop_index("ix_diagnostic_answers_session_id", table_name="diagnostic_answers")
    op.drop_table("diagnostic_answers")
    op.drop_index(
        "uq_active_diagnostic_skill_version",
        table_name="diagnostic_sessions",
    )
    op.drop_table("diagnostic_sessions")
    op.drop_table("app_settings")
