"""Add source monitoring, planning previews, notifications, and provider profiles.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-27
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_check_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=100), nullable=False),
        sa.Column("skill_version", sa.String(length=50), nullable=False),
        sa.Column("local_date", sa.String(length=10), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("checked_count", sa.Integer(), nullable=False),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'completed_with_failures')",
            name="ck_source_check_runs_status",
        ),
        sa.CheckConstraint(
            "trigger IN ('automatic', 'manual')",
            name="ck_source_check_runs_trigger",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_automatic_source_check_local_date",
        "source_check_runs",
        ["skill_id", "skill_version", "local_date"],
        unique=True,
        sqlite_where=sa.text("trigger = 'automatic'"),
    )
    op.create_table(
        "source_check_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("source_title", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("etag", sa.String(length=500), nullable=True),
        sa.Column("last_modified", sa.String(length=500), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('baseline_created', 'unchanged', 'changed', 'failed', 'manual')",
            name="ck_source_check_results_status",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["source_check_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "source_id", name="uq_source_check_result_source"),
    )
    op.create_index(
        "ix_source_check_results_run_id",
        "source_check_results",
        ["run_id"],
    )
    op.create_table(
        "source_change_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=100), nullable=False),
        sa.Column("skill_version", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("source_title", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("change_kind", sa.String(length=100), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'dismissed', 'accepted')",
            name="ck_source_change_candidates_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_change_candidates_source_id",
        "source_change_candidates",
        ["source_id"],
    )
    op.create_table(
        "planning_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("diagnostic_session_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=100), nullable=False),
        sa.Column("skill_version", sa.String(length=50), nullable=False),
        sa.Column("template_id", sa.String(length=100), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("is_preview", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("limitations_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'saved_preview', 'rejected')",
            name="ck_planning_proposals_status",
        ),
        sa.ForeignKeyConstraint(["diagnostic_session_id"], ["diagnostic_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_planning_proposals_diagnostic_session_id",
        "planning_proposals",
        ["diagnostic_session_id"],
    )
    op.create_table(
        "planning_units",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("template_unit_id", sa.String(length=100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("completion_criteria_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["planning_proposals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", "sequence", name="uq_planning_unit_sequence"),
    )
    op.create_index("ix_planning_units_proposal_id", "planning_units", ["proposal_id"])
    op.create_table(
        "planning_unit_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("planning_unit_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["planning_unit_id"],
            ["planning_units.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "planning_unit_id",
            "source_id",
            name="uq_planning_unit_source",
        ),
    )
    op.create_index(
        "ix_planning_unit_sources_planning_unit_id",
        "planning_unit_sources",
        ["planning_unit_id"],
    )
    op.create_table(
        "planning_change_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["planning_proposals.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_planning_change_events_proposal_id",
        "planning_change_events",
        ["proposal_id"],
    )
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False),
        sa.Column("email_action_required", sa.Boolean(), nullable=False),
        sa.Column("email_warning", sa.Boolean(), nullable=False),
        sa.Column("email_delay_minutes", sa.Integer(), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=True),
        sa.Column("sender_email", sa.String(length=320), nullable=True),
        sa.Column("smtp_host", sa.String(length=255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("smtp_username", sa.String(length=320), nullable=True),
        sa.Column("smtp_security", sa.String(length=20), nullable=False),
        sa.Column("credential_reference", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_notification_preferences_singleton"),
        sa.CheckConstraint(
            "smtp_security IN ('starttls', 'ssl')",
            name="ck_notification_preferences_smtp_security",
        ),
        sa.CheckConstraint(
            "email_delay_minutes >= 0",
            name="ck_notification_preferences_delay",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "notification_preferences",
            sa.column("id", sa.Integer()),
            sa.column("email_enabled", sa.Boolean()),
            sa.column("email_action_required", sa.Boolean()),
            sa.column("email_warning", sa.Boolean()),
            sa.column("email_delay_minutes", sa.Integer()),
            sa.column("recipient_email", sa.String()),
            sa.column("sender_email", sa.String()),
            sa.column("smtp_host", sa.String()),
            sa.column("smtp_port", sa.Integer()),
            sa.column("smtp_username", sa.String()),
            sa.column("smtp_security", sa.String()),
            sa.column("credential_reference", sa.String()),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "email_enabled": False,
                "email_action_required": False,
                "email_warning": False,
                "email_delay_minutes": 10,
                "recipient_email": None,
                "sender_email": None,
                "smtp_host": None,
                "smtp_port": None,
                "smtp_username": None,
                "smtp_security": "starttls",
                "credential_reference": None,
                "updated_at": datetime.now(UTC),
            }
        ],
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("related_type", sa.String(length=100), nullable=True),
        sa.Column("related_id", sa.String(length=100), nullable=True),
        sa.Column("deduplication_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "severity IN ('required', 'action_required', 'warning', 'info')",
            name="ck_notifications_severity",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_deduplication_key",
        "notifications",
        ["deduplication_key"],
    )
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("notification_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'cancelled', 'failed')",
            name="ck_email_outbox_status",
        ),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id", name="uq_email_outbox_notification"),
    )
    op.create_table(
        "ai_provider_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("credential_reference", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_provider_profiles_provider_id",
        "ai_provider_profiles",
        ["provider_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_provider_profiles_provider_id", table_name="ai_provider_profiles")
    op.drop_table("ai_provider_profiles")
    op.drop_table("email_outbox")
    op.drop_index("ix_notifications_deduplication_key", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
    op.drop_index(
        "ix_planning_change_events_proposal_id",
        table_name="planning_change_events",
    )
    op.drop_table("planning_change_events")
    op.drop_index(
        "ix_planning_unit_sources_planning_unit_id",
        table_name="planning_unit_sources",
    )
    op.drop_table("planning_unit_sources")
    op.drop_index("ix_planning_units_proposal_id", table_name="planning_units")
    op.drop_table("planning_units")
    op.drop_index(
        "ix_planning_proposals_diagnostic_session_id",
        table_name="planning_proposals",
    )
    op.drop_table("planning_proposals")
    op.drop_index(
        "ix_source_change_candidates_source_id",
        table_name="source_change_candidates",
    )
    op.drop_table("source_change_candidates")
    op.drop_index("ix_source_check_results_run_id", table_name="source_check_results")
    op.drop_table("source_check_results")
    op.drop_index(
        "uq_automatic_source_check_local_date",
        table_name="source_check_runs",
    )
    op.drop_table("source_check_runs")
