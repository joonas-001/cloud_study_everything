"""Add milestone 8D scoped execution and branch-gate review data.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_nonterminal_learning_run_skill_version", table_name="learning_runs")
    with op.batch_alter_table("learning_runs", recreate="always") as batch:
        batch.drop_constraint("ck_learning_runs_status", type_="check")
        batch.add_column(sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("pause_reason", sa.String(length=500), nullable=True))
        batch.create_check_constraint(
            "ck_learning_runs_status",
            "status IN ('active', 'paused', 'retention_pending', 'completed', 'ended')",
        )
    op.create_index(
        "uq_nonterminal_learning_run_skill_version",
        "learning_runs",
        ["skill_id", "skill_version"],
        unique=True,
        sqlite_where=sa.text("status IN ('active', 'paused', 'retention_pending')"),
    )

    with op.batch_alter_table("mastery_evidence", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "capability_ids_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )
        batch.add_column(
            sa.Column(
                "language",
                sa.String(length=20),
                nullable=False,
                server_default="none",
            )
        )

    op.create_table(
        "learning_independent_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("activity_id", sa.String(length=36), nullable=True),
        sa.Column("capability_ids_json", sa.Text(), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("reviewer_relationship", sa.String(length=200), nullable=False),
        sa.Column("rubric_id", sa.String(length=100), nullable=False),
        sa.Column("rubric_version", sa.String(length=50), nullable=False),
        sa.Column("conclusion", sa.String(length=32), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "dimension IN ('understanding', 'operation', 'transfer', "
            "'artifact', 'retention', 'correction')",
            name="ck_learning_independent_reviews_dimension",
        ),
        sa.CheckConstraint(
            "conclusion IN ('meets', 'needs_work', 'uncertain')",
            name="ck_learning_independent_reviews_conclusion",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["learning_activities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["learning_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_independent_reviews_run_id",
        "learning_independent_reviews",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_learning_independent_reviews_run_id",
        table_name="learning_independent_reviews",
    )
    op.drop_table("learning_independent_reviews")

    with op.batch_alter_table("mastery_evidence", recreate="always") as batch:
        batch.drop_column("language")
        batch.drop_column("capability_ids_json")

    op.execute(
        "UPDATE learning_runs "
        "SET status = 'ended', ended_at = CURRENT_TIMESTAMP, "
        "end_reason = 'milestone_8d_migration_downgrade' "
        "WHERE status = 'paused'"
    )
    op.drop_index("uq_nonterminal_learning_run_skill_version", table_name="learning_runs")
    with op.batch_alter_table("learning_runs", recreate="always") as batch:
        batch.drop_constraint("ck_learning_runs_status", type_="check")
        batch.drop_column("pause_reason")
        batch.drop_column("paused_at")
        batch.create_check_constraint(
            "ck_learning_runs_status",
            "status IN ('active', 'retention_pending', 'completed', 'ended')",
        )
    op.create_index(
        "uq_nonterminal_learning_run_skill_version",
        "learning_runs",
        ["skill_id", "skill_version"],
        unique=True,
        sqlite_where=sa.text("status IN ('active', 'retention_pending')"),
    )
