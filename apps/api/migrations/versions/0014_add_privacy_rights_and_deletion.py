"""Add milestone 9D privacy rights and deletion lifecycle state.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIVATE_TABLES = (
    "privacy_policy_acceptances",
    "privacy_choices",
    "privacy_requests",
)


def _enable_rls(table_name: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY "{table_name}_owner" ON "{table_name}" '
        "USING (user_id = current_setting('cloud_study.user_id', true)) "
        "WITH CHECK (user_id = current_setting('cloud_study.user_id', true))"
    )


def upgrade() -> None:
    op.create_table(
        "privacy_policy_acceptances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("document_version", sa.String(length=40), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "document_type",
            "document_version",
            "content_sha256",
            name="uq_privacy_policy_acceptance_version",
        ),
    )
    op.create_index(
        "ix_privacy_policy_acceptances_user_id", "privacy_policy_acceptances", ["user_id"]
    )
    op.create_table(
        "privacy_choices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("notice_version", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('external_ai', 'external_sources', 'email_notifications', "
            "'support_diagnostics')",
            name="ck_privacy_choices_purpose",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "purpose", name="uq_privacy_choice_purpose"),
    )
    op.create_index("ix_privacy_choices_user_id", "privacy_choices", ["user_id"])
    op.create_table(
        "privacy_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("scope_sha256", sa.String(length=64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            "request_type IN ('access', 'correction', 'export')",
            name="ck_privacy_requests_type",
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'failed')",
            name="ck_privacy_requests_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privacy_requests_user_id", "privacy_requests", ["user_id"])
    op.create_table(
        "privacy_deletion_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execute_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backup_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "status IN ('waiting', 'cancelled', 'completed', 'failed')",
            name="ck_privacy_deletion_jobs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privacy_deletion_jobs_user_id", "privacy_deletion_jobs", ["user_id"])
    op.create_index(
        "uq_privacy_deletion_job_waiting_user",
        "privacy_deletion_jobs",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'waiting'"),
        postgresql_where=sa.text("status = 'waiting'"),
    )
    op.create_table(
        "privacy_deletion_tombstones",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("deletion_job_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("backup_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reapplied_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deletion_job_id", name="uq_privacy_deletion_tombstone_job"),
    )
    op.create_index(
        "ix_privacy_deletion_tombstones_user_id", "privacy_deletion_tombstones", ["user_id"]
    )
    for table_name in PRIVATE_TABLES:
        _enable_rls(table_name)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table_name in PRIVATE_TABLES:
            op.execute(f'DROP POLICY IF EXISTS "{table_name}_owner" ON "{table_name}"')
    op.drop_index(
        "ix_privacy_deletion_tombstones_user_id", table_name="privacy_deletion_tombstones"
    )
    op.drop_table("privacy_deletion_tombstones")
    op.drop_index("uq_privacy_deletion_job_waiting_user", table_name="privacy_deletion_jobs")
    op.drop_index("ix_privacy_deletion_jobs_user_id", table_name="privacy_deletion_jobs")
    op.drop_table("privacy_deletion_jobs")
    op.drop_index("ix_privacy_requests_user_id", table_name="privacy_requests")
    op.drop_table("privacy_requests")
    op.drop_index("ix_privacy_choices_user_id", table_name="privacy_choices")
    op.drop_table("privacy_choices")
    op.drop_index("ix_privacy_policy_acceptances_user_id", table_name="privacy_policy_acceptances")
    op.drop_table("privacy_policy_acceptances")
