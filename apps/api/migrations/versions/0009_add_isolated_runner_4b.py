"""Add isolated Runner 1.1 invocations and verified evidence.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("activity_evaluations", recreate="always") as batch:
        batch.drop_constraint("ck_activity_evaluations_method", type_="check")
        batch.create_check_constraint(
            "ck_activity_evaluations_method",
            "method IN "
            "('deterministic', 'self_review', 'review_pending', 'not_executable', 'runner')",
        )
    with op.batch_alter_table("mastery_evidence", recreate="always") as batch:
        batch.drop_constraint("ck_mastery_evidence_strength", type_="check")
        batch.create_check_constraint(
            "ck_mastery_evidence_strength",
            "strength IN ('limited', 'supported', 'retained_limited', 'verified', 'retained')",
        )
    with op.batch_alter_table("mastery_snapshots", recreate="always") as batch:
        batch.drop_constraint("ck_mastery_snapshots_level", type_="check")
        batch.create_check_constraint(
            "ck_mastery_snapshots_level",
            "evidence_level IN ('none', 'limited', 'supported', 'verified', 'retained')",
        )
    op.create_table(
        "runner_invocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("singleton_key", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("protocol_version", sa.String(length=20), nullable=False),
        sa.Column("task_id", sa.String(length=100), nullable=False),
        sa.Column("runtime_profile_id", sa.String(length=100), nullable=False),
        sa.Column("runtime_profile_version", sa.String(length=50), nullable=False),
        sa.Column("runtime_image", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'passed', 'failed', 'timeout', "
            "'output_limit', 'infrastructure_error')",
            name="ck_runner_invocations_status",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["learning_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["learning_activities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["activity_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runner_invocations_run_id", "runner_invocations", ["run_id"])
    op.create_index(
        "ix_runner_invocations_activity_id",
        "runner_invocations",
        ["activity_id"],
    )
    op.create_index(
        "ix_runner_invocations_attempt_id",
        "runner_invocations",
        ["attempt_id"],
    )
    op.create_index(
        "uq_active_runner_invocation",
        "runner_invocations",
        ["singleton_key"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_runner_invocation", table_name="runner_invocations")
    op.drop_index("ix_runner_invocations_attempt_id", table_name="runner_invocations")
    op.drop_index("ix_runner_invocations_activity_id", table_name="runner_invocations")
    op.drop_index("ix_runner_invocations_run_id", table_name="runner_invocations")
    op.drop_table("runner_invocations")
    op.execute("DELETE FROM mastery_evidence WHERE strength IN ('verified', 'retained')")
    op.execute("DELETE FROM activity_evaluations WHERE method = 'runner'")
    op.execute(
        """
        UPDATE mastery_snapshots
        SET evidence_level = CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM mastery_evidence
                    WHERE mastery_evidence.run_id = mastery_snapshots.run_id
                      AND mastery_evidence.dimension = mastery_snapshots.dimension
                      AND mastery_evidence.superseded_at IS NULL
                      AND mastery_evidence.strength = 'supported'
                ) THEN 'supported'
                WHEN EXISTS (
                    SELECT 1
                    FROM mastery_evidence
                    WHERE mastery_evidence.run_id = mastery_snapshots.run_id
                      AND mastery_evidence.dimension = mastery_snapshots.dimension
                      AND mastery_evidence.superseded_at IS NULL
                      AND mastery_evidence.strength IN ('limited', 'retained_limited')
                ) THEN 'limited'
                ELSE 'none'
            END,
            evidence_count = (
                SELECT COUNT(*)
                FROM mastery_evidence
                WHERE mastery_evidence.run_id = mastery_snapshots.run_id
                  AND mastery_evidence.dimension = mastery_snapshots.dimension
                  AND mastery_evidence.superseded_at IS NULL
            )
        WHERE evidence_level IN ('verified', 'retained')
        """
    )
    with op.batch_alter_table("mastery_snapshots", recreate="always") as batch:
        batch.drop_constraint("ck_mastery_snapshots_level", type_="check")
        batch.create_check_constraint(
            "ck_mastery_snapshots_level",
            "evidence_level IN ('none', 'limited', 'supported')",
        )
    with op.batch_alter_table("mastery_evidence", recreate="always") as batch:
        batch.drop_constraint("ck_mastery_evidence_strength", type_="check")
        batch.create_check_constraint(
            "ck_mastery_evidence_strength",
            "strength IN ('limited', 'supported', 'retained_limited')",
        )
    with op.batch_alter_table("activity_evaluations", recreate="always") as batch:
        batch.drop_constraint("ck_activity_evaluations_method", type_="check")
        batch.create_check_constraint(
            "ck_activity_evaluations_method",
            "method IN ('deterministic', 'self_review', 'review_pending', 'not_executable')",
        )
