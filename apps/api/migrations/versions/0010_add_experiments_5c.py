"""Add governed milestone 5C local experiment records.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_policy_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=100), nullable=False),
        sa.Column("policy_version", sa.String(length=50), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id",
            "policy_version",
            name="uq_experiment_policy_snapshot",
        ),
    )
    op.create_table(
        "monetization_experiments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("goal_selection_id", sa.String(length=36), nullable=False),
        sa.Column("learning_run_id", sa.String(length=36), nullable=False),
        sa.Column("market_research_run_id", sa.String(length=36), nullable=True),
        sa.Column("policy_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=100), nullable=False),
        sa.Column("skill_version", sa.String(length=50), nullable=False),
        sa.Column("skill_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("capability_scope_id", sa.String(length=100), nullable=False),
        sa.Column("path", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("target_audience", sa.String(length=500), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("planned_action", sa.Text(), nullable=False),
        sa.Column("success_metric", sa.Text(), nullable=False),
        sa.Column("time_budget_minutes", sa.Integer(), nullable=False),
        sa.Column("cost_cap_minor", sa.Integer(), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("gate_level", sa.String(length=32), nullable=False),
        sa.Column("gate_reasons_json", sa.Text(), nullable=False),
        sa.Column("evidence_snapshot_json", sa.Text(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "path IN ('employment', 'freelancing', 'productization')",
            name="ck_monetization_experiments_path",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'rejected', 'blocked', 'approved', 'active', "
            "'paused', 'ended', 'completed')",
            name="ck_monetization_experiments_status",
        ),
        sa.CheckConstraint(
            "gate_level IN ('draft_only', 'local_ready', 'action_ready', 'blocked')",
            name="ck_monetization_experiments_gate",
        ),
        sa.CheckConstraint(
            "time_budget_minutes > 0 AND cost_cap_minor >= 0",
            name="ck_monetization_experiments_budgets",
        ),
        sa.ForeignKeyConstraint(
            ["goal_selection_id"],
            ["user_goal_selections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["learning_run_id"],
            ["learning_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_research_run_id"],
            ["market_research_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_snapshot_id"],
            ["experiment_policy_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("goal_selection_id", "learning_run_id", "market_research_run_id"):
        op.create_index(
            f"ix_monetization_experiments_{column}",
            "monetization_experiments",
            [column],
        )

    op.create_table(
        "experiment_independent_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("reviewer_relationship", sa.String(length=32), nullable=False),
        sa.Column("review_scope", sa.Text(), nullable=False),
        sa.Column("rubric_id", sa.String(length=100), nullable=False),
        sa.Column("rubric_version", sa.String(length=50), nullable=False),
        sa.Column("conclusion", sa.String(length=32), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "dimension IN ('transfer', 'artifact')",
            name="ck_experiment_reviews_dimension",
        ),
        sa.CheckConstraint(
            "reviewer_relationship IN "
            "('peer', 'mentor', 'instructor', 'employer', 'client', 'other')",
            name="ck_experiment_reviews_relationship",
        ),
        sa.CheckConstraint(
            "conclusion IN ('passed', 'needs_work')",
            name="ck_experiment_reviews_conclusion",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["monetization_experiments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experiment_independent_reviews_experiment_id",
        "experiment_independent_reviews",
        ["experiment_id"],
    )

    op.create_table(
        "experiment_action_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("action_kind", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("user_confirmed_external", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action_kind IN ('application', 'interview', 'networking', 'portfolio_share', 'other')",
            name="ck_experiment_actions_kind",
        ),
        sa.CheckConstraint(
            "result IN "
            "('pending', 'response', 'no_response', 'interview', 'rejected', "
            "'offer', 'withdrawn', 'other')",
            name="ck_experiment_actions_result",
        ),
        sa.CheckConstraint(
            "user_confirmed_external = 1",
            name="ck_experiment_actions_user_confirmed",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["monetization_experiments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experiment_action_records_experiment_id",
        "experiment_action_records",
        ["experiment_id"],
    )

    op.create_table(
        "experiment_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("hypothesis_result", sa.String(length=32), nullable=False),
        sa.Column("observable_result", sa.Text(), nullable=False),
        sa.Column("learning_gap_dimension", sa.String(length=32), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "hypothesis_result IN ('supported', 'not_supported', 'inconclusive')",
            name="ck_experiment_outcomes_result",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["monetization_experiments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experiment_outcomes_experiment_id",
        "experiment_outcomes",
        ["experiment_id"],
    )

    op.create_table(
        "experiment_income_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("redacted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "current_revision >= 1",
            name="ck_experiment_income_current_revision",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["monetization_experiments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experiment_income_records_experiment_id",
        "experiment_income_records",
        ["experiment_id"],
    )

    op.create_table(
        "experiment_income_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("income_record_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("amount_basis", sa.String(length=32), nullable=True),
        sa.Column("gross_amount_minor", sa.Integer(), nullable=True),
        sa.Column("platform_fee_minor", sa.Integer(), nullable=True),
        sa.Column("direct_cost_minor", sa.Integer(), nullable=True),
        sa.Column("received_amount_minor", sa.Integer(), nullable=True),
        sa.Column("verification_level", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("occurred_on", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_basis IS NULL OR amount_basis IN ('tax_inclusive', 'pre_tax')",
            name="ck_experiment_income_basis",
        ),
        sa.CheckConstraint(
            "verification_level IS NULL OR verification_level IN "
            "('self_reported', 'platform_record', 'received')",
            name="ck_experiment_income_verification",
        ),
        sa.CheckConstraint(
            "(gross_amount_minor IS NULL OR gross_amount_minor >= 0) AND "
            "(platform_fee_minor IS NULL OR platform_fee_minor >= 0) AND "
            "(direct_cost_minor IS NULL OR direct_cost_minor >= 0) AND "
            "(received_amount_minor IS NULL OR received_amount_minor >= 0)",
            name="ck_experiment_income_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["income_record_id"],
            ["experiment_income_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "income_record_id",
            "revision",
            name="uq_experiment_income_revision",
        ),
    )
    op.create_index(
        "ix_experiment_income_revisions_income_record_id",
        "experiment_income_revisions",
        ["income_record_id"],
    )

    op.create_table(
        "experiment_feedback_suggestions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("outcome_id", sa.String(length=36), nullable=True),
        sa.Column("suggestion_type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_refs_json", sa.Text(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("plan_impact", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "suggestion_type IN "
            "('diagnostic_question', 'correction', 'review', 'project', "
            "'supplemental_unit', 'replanning', 'source_review', 'pause_path')",
            name="ck_experiment_feedback_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'withdrawn')",
            name="ck_experiment_feedback_status",
        ),
        sa.CheckConstraint(
            "estimated_minutes >= 0",
            name="ck_experiment_feedback_minutes",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["monetization_experiments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["outcome_id"],
            ["experiment_outcomes.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experiment_feedback_suggestions_experiment_id",
        "experiment_feedback_suggestions",
        ["experiment_id"],
    )
    op.create_index(
        "ix_experiment_feedback_suggestions_outcome_id",
        "experiment_feedback_suggestions",
        ["outcome_id"],
    )

    op.create_table(
        "experiment_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["monetization_experiments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experiment_events_experiment_id",
        "experiment_events",
        ["experiment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_experiment_events_experiment_id", table_name="experiment_events")
    op.drop_table("experiment_events")
    op.drop_index(
        "ix_experiment_feedback_suggestions_outcome_id",
        table_name="experiment_feedback_suggestions",
    )
    op.drop_index(
        "ix_experiment_feedback_suggestions_experiment_id",
        table_name="experiment_feedback_suggestions",
    )
    op.drop_table("experiment_feedback_suggestions")
    op.drop_index(
        "ix_experiment_income_revisions_income_record_id",
        table_name="experiment_income_revisions",
    )
    op.drop_table("experiment_income_revisions")
    op.drop_index(
        "ix_experiment_income_records_experiment_id",
        table_name="experiment_income_records",
    )
    op.drop_table("experiment_income_records")
    op.drop_index("ix_experiment_outcomes_experiment_id", table_name="experiment_outcomes")
    op.drop_table("experiment_outcomes")
    op.drop_index(
        "ix_experiment_action_records_experiment_id",
        table_name="experiment_action_records",
    )
    op.drop_table("experiment_action_records")
    op.drop_index(
        "ix_experiment_independent_reviews_experiment_id",
        table_name="experiment_independent_reviews",
    )
    op.drop_table("experiment_independent_reviews")
    for column in ("market_research_run_id", "learning_run_id", "goal_selection_id"):
        op.drop_index(
            f"ix_monetization_experiments_{column}",
            table_name="monetization_experiments",
        )
    op.drop_table("monetization_experiments")
    op.drop_table("experiment_policy_snapshots")
