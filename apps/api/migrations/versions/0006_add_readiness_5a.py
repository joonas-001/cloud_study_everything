"""Add the local deterministic milestone 5A readiness model.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_goal_selections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=100), nullable=False),
        sa.Column("skill_version", sa.String(length=50), nullable=False),
        sa.Column("capability_scope_id", sa.String(length=100), nullable=False),
        sa.Column("goal_kind", sa.String(length=32), nullable=False),
        sa.Column("custom_label", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "goal_kind IN ('learning', 'exam', 'employment', 'freelancing', "
            "'productization', 'other')",
            name="ck_user_goal_selections_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_active_user_goal_scope",
        "user_goal_selections",
        ["skill_id", "skill_version", "capability_scope_id"],
        unique=True,
        sqlite_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "readiness_policy_snapshots",
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
            name="uq_readiness_policy_snapshot",
        ),
    )

    op.create_table(
        "market_evidence_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fixture_id", sa.String(length=100), nullable=False),
        sa.Column("fixture_version", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("freshness_status", sa.String(length=32), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "synthetic = 1",
            name="ck_market_evidence_5a_synthetic",
        ),
        sa.CheckConstraint(
            "freshness_status IN ('current', 'stale', 'conflicted', 'indeterminate')",
            name="ck_market_evidence_freshness",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fixture_id",
            "fixture_version",
            name="uq_market_evidence_snapshot",
        ),
    )

    op.create_table(
        "readiness_evaluations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("goal_selection_id", sa.String(length=36), nullable=False),
        sa.Column("learning_run_id", sa.String(length=36), nullable=True),
        sa.Column("policy_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("market_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_codes_json", sa.Text(), nullable=False),
        sa.Column("evidence_snapshot_json", sa.Text(), nullable=False),
        sa.Column("limitations_json", sa.Text(), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('not_applicable', 'not_ready', 'review_required', "
            "'comparison_ready', 'experiment_ready')",
            name="ck_readiness_evaluations_status",
        ),
        sa.CheckConstraint(
            "status != 'experiment_ready'",
            name="ck_readiness_5a_no_experiment_ready",
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
            ["market_snapshot_id"],
            ["market_evidence_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_snapshot_id"],
            ["readiness_policy_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_readiness_evaluations_goal_selection_id",
        "readiness_evaluations",
        ["goal_selection_id"],
    )
    op.create_index(
        "ix_readiness_evaluations_learning_run_id",
        "readiness_evaluations",
        ["learning_run_id"],
    )

    op.create_table(
        "path_comparisons",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("evaluation_id", sa.String(length=36), nullable=False),
        sa.Column("market_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("comparison_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "synthetic = 1",
            name="ck_path_comparisons_5a_synthetic",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["readiness_evaluations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_snapshot_id"],
            ["market_evidence_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_id",
            name="uq_path_comparison_evaluation",
        ),
    )
    op.create_index(
        "ix_path_comparisons_evaluation_id",
        "path_comparisons",
        ["evaluation_id"],
    )

    op.create_table(
        "path_comparison_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("comparison_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected', 'deferred')",
            name="ck_path_comparison_decisions_value",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id"],
            ["path_comparisons.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comparison_id",
            "revision",
            name="uq_path_comparison_decision_revision",
        ),
    )
    op.create_index(
        "ix_path_comparison_decisions_comparison_id",
        "path_comparison_decisions",
        ["comparison_id"],
    )

    op.create_table(
        "readiness_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("goal_selection_id", sa.String(length=36), nullable=True),
        sa.Column("evaluation_id", sa.String(length=36), nullable=True),
        sa.Column("comparison_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["goal_selection_id"],
            ["user_goal_selections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["readiness_evaluations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id"],
            ["path_comparisons.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_readiness_events_goal_selection_id",
        "readiness_events",
        ["goal_selection_id"],
    )
    op.create_index(
        "ix_readiness_events_evaluation_id",
        "readiness_events",
        ["evaluation_id"],
    )
    op.create_index(
        "ix_readiness_events_comparison_id",
        "readiness_events",
        ["comparison_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_readiness_events_comparison_id", table_name="readiness_events")
    op.drop_index("ix_readiness_events_evaluation_id", table_name="readiness_events")
    op.drop_index("ix_readiness_events_goal_selection_id", table_name="readiness_events")
    op.drop_table("readiness_events")
    op.drop_index(
        "ix_path_comparison_decisions_comparison_id",
        table_name="path_comparison_decisions",
    )
    op.drop_table("path_comparison_decisions")
    op.drop_index("ix_path_comparisons_evaluation_id", table_name="path_comparisons")
    op.drop_table("path_comparisons")
    op.drop_index(
        "ix_readiness_evaluations_learning_run_id",
        table_name="readiness_evaluations",
    )
    op.drop_index(
        "ix_readiness_evaluations_goal_selection_id",
        table_name="readiness_evaluations",
    )
    op.drop_table("readiness_evaluations")
    op.drop_table("market_evidence_snapshots")
    op.drop_table("readiness_policy_snapshots")
    op.drop_index("uq_active_user_goal_scope", table_name="user_goal_selections")
    op.drop_table("user_goal_selections")
