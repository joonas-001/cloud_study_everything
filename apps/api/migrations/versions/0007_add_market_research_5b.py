"""Add governed real market research for milestone 5B.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_provider_profiles") as batch:
        batch.add_column(sa.Column("model_id", sa.String(length=100), nullable=True))

    op.create_table(
        "market_research_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("catalog_id", sa.String(length=100), nullable=False),
        sa.Column("catalog_version", sa.String(length=50), nullable=False),
        sa.Column("catalog_sha256", sa.String(length=64), nullable=False),
        sa.Column("catalog_snapshot_json", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.String(length=100), nullable=False),
        sa.Column("skill_version", sa.String(length=50), nullable=False),
        sa.Column("capability_scope_id", sa.String(length=100), nullable=False),
        sa.Column("goal_selection_id", sa.String(length=36), nullable=False),
        sa.Column("goal_kind", sa.String(length=32), nullable=False),
        sa.Column("goal_snapshot_json", sa.Text(), nullable=False),
        sa.Column("readiness_evaluation_id", sa.String(length=36), nullable=True),
        sa.Column("scope_json", sa.Text(), nullable=False),
        sa.Column("budget_policy_id", sa.String(length=100), nullable=False),
        sa.Column("budget_policy_version", sa.String(length=50), nullable=False),
        sa.Column("budget_policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("budget_policy_snapshot_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_profile_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("credential_reference", sa.String(length=255), nullable=False),
        sa.Column("external_ai_consent", sa.Boolean(), nullable=False),
        sa.Column("source_results_json", sa.Text(), nullable=False),
        sa.Column("synthesis_json", sa.Text(), nullable=True),
        sa.Column("synthesis_valid", sa.Boolean(), nullable=False),
        sa.Column("synthesis_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("synthesis_invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost_accounted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("estimated_cost_micros", sa.Integer(), nullable=False),
        sa.Column("actual_cost_micros", sa.Integer(), nullable=False),
        sa.Column("accounted_cost_micros", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('source_pending', 'synthesis_pending', 'synthesis_in_progress', "
            "'recovery_required', 'review_pending', 'completed', 'blocked', 'failed')",
            name="ck_market_research_runs_status",
        ),
        sa.CheckConstraint(
            "review_status IN "
            "('not_ready', 'not_requested', 'pending', 'accepted', 'rejected')",
            name="ck_market_research_runs_review_status",
        ),
        sa.CheckConstraint(
            "estimated_cost_micros >= 0 AND actual_cost_micros >= 0 "
            "AND accounted_cost_micros >= 0",
            name="ck_market_research_runs_nonnegative_cost",
        ),
        sa.ForeignKeyConstraint(
            ["provider_profile_id"],
            ["ai_provider_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["goal_selection_id"],
            ["user_goal_selections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["readiness_evaluation_id"],
            ["readiness_evaluations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_market_research_runs_goal_selection_id",
        "market_research_runs",
        ["goal_selection_id"],
    )
    op.create_index(
        "ix_market_research_runs_readiness_evaluation_id",
        "market_research_runs",
        ["readiness_evaluation_id"],
    )
    op.create_index(
        "ix_market_research_runs_provider_profile_id",
        "market_research_runs",
        ["provider_profile_id"],
    )
    op.create_index(
        "uq_active_market_research_run",
        "market_research_runs",
        ["catalog_id", "catalog_version"],
        unique=True,
        sqlite_where=sa.text(
            "status IN ('source_pending', 'synthesis_pending', "
            "'synthesis_in_progress', 'review_pending')"
        ),
    )
    op.create_table(
        "market_research_synthesis_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("budget_policy_id", sa.String(length=100), nullable=False),
        sa.Column("budget_policy_version", sa.String(length=50), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("reserved_cost_micros", sa.Integer(), nullable=False),
        sa.Column("accounted_cost_micros", sa.Integer(), nullable=False),
        sa.Column("charge_status", sa.String(length=32), nullable=False),
        sa.Column("response_sha256", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatch_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accounted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "phase IN ('claimed', 'dispatch_started', 'response_received', "
            "'accounted', 'recovery_required', 'failed')",
            name="ck_market_research_attempts_phase",
        ),
        sa.CheckConstraint(
            "reserved_cost_micros >= 0 AND accounted_cost_micros >= 0",
            name="ck_market_research_attempts_nonnegative_cost",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["market_research_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_market_research_attempt_run"),
    )
    op.create_index(
        "ix_market_research_synthesis_attempts_run_id",
        "market_research_synthesis_attempts",
        ["run_id"],
    )
    op.create_table(
        "market_research_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["market_research_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_market_research_events_run_id",
        "market_research_events",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_research_synthesis_attempts_run_id",
        table_name="market_research_synthesis_attempts",
    )
    op.drop_table("market_research_synthesis_attempts")
    op.drop_index("ix_market_research_events_run_id", table_name="market_research_events")
    op.drop_table("market_research_events")
    op.drop_index("uq_active_market_research_run", table_name="market_research_runs")
    op.drop_index(
        "ix_market_research_runs_readiness_evaluation_id",
        table_name="market_research_runs",
    )
    op.drop_index(
        "ix_market_research_runs_goal_selection_id",
        table_name="market_research_runs",
    )
    op.drop_index(
        "ix_market_research_runs_provider_profile_id",
        table_name="market_research_runs",
    )
    op.drop_table("market_research_runs")
    with op.batch_alter_table("ai_provider_profiles") as batch:
        batch.drop_column("model_id")
