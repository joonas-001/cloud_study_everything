"""Add version locks and the fourth-milestone learning execution model.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLANNING_STATUS_0004 = "status IN ('draft', 'saved_preview', 'rejected')"
_PLANNING_STATUS_0005 = "status IN ('draft', 'saved_preview', 'rejected', 'frozen_preview')"


def upgrade() -> None:
    with op.batch_alter_table("planning_proposals", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_planning_proposals_status", type_="check")
        batch_op.create_check_constraint(
            "ck_planning_proposals_status",
            _PLANNING_STATUS_0005,
        )

    op.execute(
        """
        INSERT INTO diagnostic_events (
            session_id, event_type, payload_json, occurred_at
        )
        SELECT id,
               'version_intake_closed',
               '{"reason":"version_intake_closed","skill_version":"0.1.0"}',
               CURRENT_TIMESTAMP
        FROM diagnostic_sessions
        WHERE skill_id = 'algorithm'
          AND skill_version = '0.1.0'
          AND status = 'active'
        """
    )
    op.execute(
        """
        UPDATE diagnostic_sessions
        SET status = 'ended',
            end_reason = 'version_intake_closed',
            ended_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP,
            last_activity_at = CURRENT_TIMESTAMP
        WHERE skill_id = 'algorithm'
          AND skill_version = '0.1.0'
          AND status = 'active'
        """
    )
    op.execute(
        """
        INSERT INTO planning_change_events (
            proposal_id, event_type, payload_json, occurred_at
        )
        SELECT id,
               'planning_preview_frozen',
               '{"reason":"version_intake_closed","skill_version":"0.1.0"}',
               CURRENT_TIMESTAMP
        FROM planning_proposals
        WHERE skill_id = 'algorithm'
          AND skill_version = '0.1.0'
          AND status = 'draft'
        """
    )
    op.execute(
        """
        UPDATE planning_proposals
        SET status = 'frozen_preview',
            updated_at = CURRENT_TIMESTAMP
        WHERE skill_id = 'algorithm'
          AND skill_version = '0.1.0'
          AND status = 'draft'
        """
    )

    op.create_table(
        "skill_version_content_locks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=100), nullable=False),
        sa.Column("skill_version", sa.String(length=50), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_lock_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_lock_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "skill_id",
            "skill_version",
            name="uq_skill_version_content_lock",
        ),
    )
    op.create_table(
        "learning_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("planning_proposal_id", sa.String(length=36), nullable=False),
        sa.Column("diagnostic_session_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=100), nullable=False),
        sa.Column("skill_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_preview", sa.Boolean(), nullable=False),
        sa.Column("selected_historical_plan", sa.Boolean(), nullable=False),
        sa.Column("reused_from_run_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'retention_pending', 'completed', 'ended')",
            name="ck_learning_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["diagnostic_session_id"],
            ["diagnostic_sessions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["planning_proposal_id"],
            ["planning_proposals.id"],
        ),
        sa.ForeignKeyConstraint(["reused_from_run_id"], ["learning_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_runs_planning_proposal_id",
        "learning_runs",
        ["planning_proposal_id"],
    )
    op.create_index(
        "ix_learning_runs_diagnostic_session_id",
        "learning_runs",
        ["diagnostic_session_id"],
    )
    op.create_index(
        "uq_nonterminal_learning_run_skill_version",
        "learning_runs",
        ["skill_id", "skill_version"],
        unique=True,
        sqlite_where=sa.text("status IN ('active', 'retention_pending')"),
    )
    op.create_table(
        "learning_run_locks",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("lock_sha256", sa.String(length=64), nullable=False),
        sa.Column("lock_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["learning_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_table(
        "learning_unit_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("template_unit_id", sa.String(length=100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'completed')",
            name="ck_learning_unit_instances_status",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["learning_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_learning_unit_instance_sequence",
        ),
    )
    op.create_index(
        "ix_learning_unit_instances_run_id",
        "learning_unit_instances",
        ["run_id"],
    )
    op.create_table(
        "learning_activities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("unit_instance_id", sa.String(length=36), nullable=False),
        sa.Column("template_activity_id", sa.String(length=150), nullable=False),
        sa.Column("activity_type", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "activity_type IN "
            "('study', 'explanation', 'structured_check', 'code_text', 'transfer', "
            "'correction', 'project_evidence', 'review')",
            name="ck_learning_activities_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'available', 'completed', 'correction_required')",
            name="ck_learning_activities_status",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["learning_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unit_instance_id"],
            ["learning_unit_instances.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_learning_activity_sequence",
        ),
    )
    op.create_index(
        "ix_learning_activities_run_id",
        "learning_activities",
        ["run_id"],
    )
    op.create_index(
        "ix_learning_activities_unit_instance_id",
        "learning_activities",
        ["unit_instance_id"],
    )
    op.create_table(
        "activity_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("submission_json", sa.Text(), nullable=False),
        sa.Column("corrects_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["learning_activities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["corrects_attempt_id"],
            ["activity_attempts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "activity_id",
            "revision",
            name="uq_activity_attempt_revision",
        ),
    )
    op.create_index(
        "ix_activity_attempts_activity_id",
        "activity_attempts",
        ["activity_id"],
    )
    op.create_table(
        "activity_evaluations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("rubric_id", sa.String(length=100), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "method IN ('deterministic', 'self_review', 'review_pending', 'not_executable')",
            name="ck_activity_evaluations_method",
        ),
        sa.CheckConstraint(
            "result IN ('passed', 'failed', 'submitted', 'uncertain', "
            "'review_pending', 'not_executable')",
            name="ck_activity_evaluations_result",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["activity_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_activity_evaluations_attempt_id",
        "activity_evaluations",
        ["attempt_id"],
    )
    op.create_table(
        "mastery_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("evaluation_id", sa.String(length=36), nullable=False),
        sa.Column("criterion_id", sa.String(length=100), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("strength", sa.String(length=32), nullable=False),
        sa.Column("review_flags_json", sa.Text(), nullable=False),
        sa.Column("rubric_version", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_attempt_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "dimension IN ('understanding', 'operation', 'transfer', "
            "'artifact', 'retention', 'correction')",
            name="ck_mastery_evidence_dimension",
        ),
        sa.CheckConstraint(
            "strength IN ('limited', 'supported', 'retained_limited')",
            name="ck_mastery_evidence_strength",
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
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["activity_evaluations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["learning_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_attempt_id"],
            ["activity_attempts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mastery_evidence_run_id",
        "mastery_evidence",
        ["run_id"],
    )
    op.create_table(
        "mastery_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("evidence_level", sa.String(length=32), nullable=False),
        sa.Column("review_flags_json", sa.Text(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "dimension IN ('understanding', 'operation', 'transfer', "
            "'artifact', 'retention', 'correction')",
            name="ck_mastery_snapshots_dimension",
        ),
        sa.CheckConstraint(
            "evidence_level IN ('none', 'limited', 'supported')",
            name="ck_mastery_snapshots_level",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["learning_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "dimension",
            name="uq_mastery_snapshot_dimension",
        ),
    )
    op.create_index(
        "ix_mastery_snapshots_run_id",
        "mastery_snapshots",
        ["run_id"],
    )
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("activity_id", sa.String(length=36), nullable=True),
        sa.Column("checkpoint_index", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("policy_id", sa.String(length=100), nullable=False),
        sa.Column("policy_version", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('scheduled', 'available', 'passed', 'failed')",
            name="ck_review_tasks_status",
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
        sa.UniqueConstraint(
            "run_id",
            "checkpoint_index",
            "attempt_number",
            name="uq_review_task_checkpoint_attempt",
        ),
    )
    op.create_index(
        "ix_review_tasks_run_id",
        "review_tasks",
        ["run_id"],
    )
    op.create_table(
        "learning_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["learning_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_events_run_id",
        "learning_events",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_learning_events_run_id", table_name="learning_events")
    op.drop_table("learning_events")
    op.drop_index("ix_review_tasks_run_id", table_name="review_tasks")
    op.drop_table("review_tasks")
    op.drop_index("ix_mastery_snapshots_run_id", table_name="mastery_snapshots")
    op.drop_table("mastery_snapshots")
    op.drop_index("ix_mastery_evidence_run_id", table_name="mastery_evidence")
    op.drop_table("mastery_evidence")
    op.drop_index(
        "ix_activity_evaluations_attempt_id",
        table_name="activity_evaluations",
    )
    op.drop_table("activity_evaluations")
    op.drop_index("ix_activity_attempts_activity_id", table_name="activity_attempts")
    op.drop_table("activity_attempts")
    op.drop_index(
        "ix_learning_activities_unit_instance_id",
        table_name="learning_activities",
    )
    op.drop_index("ix_learning_activities_run_id", table_name="learning_activities")
    op.drop_table("learning_activities")
    op.drop_index(
        "ix_learning_unit_instances_run_id",
        table_name="learning_unit_instances",
    )
    op.drop_table("learning_unit_instances")
    op.drop_table("learning_run_locks")
    op.drop_index(
        "uq_nonterminal_learning_run_skill_version",
        table_name="learning_runs",
    )
    op.drop_index(
        "ix_learning_runs_diagnostic_session_id",
        table_name="learning_runs",
    )
    op.drop_index(
        "ix_learning_runs_planning_proposal_id",
        table_name="learning_runs",
    )
    op.drop_table("learning_runs")
    op.drop_table("skill_version_content_locks")

    op.execute(
        """
        UPDATE planning_proposals
        SET status = 'rejected'
        WHERE status = 'frozen_preview'
        """
    )
    with op.batch_alter_table("planning_proposals", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_planning_proposals_status", type_="check")
        batch_op.create_check_constraint(
            "ck_planning_proposals_status",
            _PLANNING_STATUS_0004,
        )
