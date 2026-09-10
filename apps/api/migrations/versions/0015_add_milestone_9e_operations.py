"""Add milestone 9E support and operations controls.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_support_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute('ALTER TABLE "support_cases" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "support_cases" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "support_cases_owner" ON "support_cases" '
        "USING (user_id = current_setting('cloud_study.user_id', true)) "
        "WITH CHECK (user_id = current_setting('cloud_study.user_id', true))"
    )


def _install_immutable_audit_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER operations_audit_events_no_update BEFORE UPDATE ON "
            "operations_audit_events BEGIN SELECT RAISE(ABORT, "
            "'operations audit is append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER operations_audit_events_no_delete BEFORE DELETE ON "
            "operations_audit_events BEGIN SELECT RAISE(ABORT, "
            "'operations audit is append-only'); END"
        )
    elif dialect == "postgresql":
        op.execute(
            "CREATE FUNCTION cloud_study_operations_audit_immutable() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
            "'operations audit is append-only'; END; $$"
        )
        op.execute(
            "CREATE TRIGGER operations_audit_events_immutable BEFORE UPDATE OR DELETE ON "
            "operations_audit_events FOR EACH ROW EXECUTE FUNCTION "
            "cloud_study_operations_audit_immutable()"
        )


def upgrade() -> None:
    op.create_table(
        "support_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            "category IN ('product_support', 'account_recovery', 'security_vulnerability', "
            "'privacy_request', 'content_correction', 'abuse_appeal')",
            name="ck_support_cases_category",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'waiting_user', 'resolved', 'closed')",
            name="ck_support_cases_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_cases_user_id", "support_cases", ["user_id"])
    op.create_table(
        "support_access_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=True),
        sa.Column("target_user_id", sa.String(length=36), nullable=False),
        sa.Column("support_user_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("incident_reference", sa.String(length=80), nullable=True),
        sa.Column("emergency", sa.Boolean(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("post_notice_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('requested', 'active', 'denied', 'revoked', 'expired')",
            name="ck_support_access_grants_status",
        ),
        sa.CheckConstraint(
            "scope IN ('ticket_metadata', 'case_content')",
            name="ck_support_access_grants_scope",
        ),
        sa.CheckConstraint(
            "expires_at > requested_at", name="ck_support_access_grants_positive_lifetime"
        ),
        sa.CheckConstraint(
            "(status != 'active') OR (approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_support_access_grants_active_approval",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["support_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["support_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_access_grants_case_id", "support_access_grants", ["case_id"])
    op.create_index(
        "ix_support_access_grants_target_user_id", "support_access_grants", ["target_user_id"]
    )
    op.create_index(
        "ix_support_access_grants_support_user_id", "support_access_grants", ["support_user_id"]
    )
    op.create_table(
        "operations_controls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_mode", sa.String(length=24), nullable=False),
        sa.Column("invitations_enabled", sa.Boolean(), nullable=False),
        sa.Column("runner_enabled", sa.Boolean(), nullable=False),
        sa.Column("external_ai_enabled", sa.Boolean(), nullable=False),
        sa.Column("external_sources_enabled", sa.Boolean(), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_operations_controls_singleton"),
        sa.CheckConstraint(
            "service_mode IN ('normal', 'read_only', 'stopped')",
            name="ck_operations_controls_service_mode",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_operations_controls_positive_revision"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "operations_quota_buckets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.Column("principal_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("active_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("used_count >= 0", name="ck_operations_quota_nonnegative_usage"),
        sa.CheckConstraint("active_count >= 0", name="ck_operations_quota_nonnegative_active"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "capability", "principal_hash", name="uq_operations_quota_capability_principal"
        ),
    )
    op.create_table(
        "operations_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_hash", sa.String(length=64), nullable=False),
        sa.Column("target_hash", sa.String(length=64), nullable=True),
        sa.Column("case_id", sa.String(length=36), nullable=True),
        sa.Column("grant_id", sa.String(length=36), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("position"),
        sa.UniqueConstraint("event_hash"),
    )
    op.create_index("ix_operations_audit_events_case_id", "operations_audit_events", ["case_id"])
    op.create_index("ix_operations_audit_events_grant_id", "operations_audit_events", ["grant_id"])
    op.create_index(
        "ix_operations_audit_events_occurred_at", "operations_audit_events", ["occurred_at"]
    )
    op.create_table(
        "operations_metrics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("principal_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operations_metrics_principal_hash", "operations_metrics", ["principal_hash"]
    )
    op.create_index("ix_operations_metrics_occurred_at", "operations_metrics", ["occurred_at"])
    _enable_support_rls()
    _install_immutable_audit_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS operations_audit_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS operations_audit_events_no_delete")
    elif dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS operations_audit_events_immutable ON operations_audit_events"
        )
        op.execute("DROP FUNCTION IF EXISTS cloud_study_operations_audit_immutable()")
        op.execute('DROP POLICY IF EXISTS "support_cases_owner" ON "support_cases"')
    op.drop_index("ix_operations_metrics_occurred_at", table_name="operations_metrics")
    op.drop_index("ix_operations_metrics_principal_hash", table_name="operations_metrics")
    op.drop_table("operations_metrics")
    op.drop_index("ix_operations_audit_events_occurred_at", table_name="operations_audit_events")
    op.drop_index("ix_operations_audit_events_grant_id", table_name="operations_audit_events")
    op.drop_index("ix_operations_audit_events_case_id", table_name="operations_audit_events")
    op.drop_table("operations_audit_events")
    op.drop_table("operations_quota_buckets")
    op.drop_table("operations_controls")
    op.drop_index("ix_support_access_grants_support_user_id", table_name="support_access_grants")
    op.drop_index("ix_support_access_grants_target_user_id", table_name="support_access_grants")
    op.drop_index("ix_support_access_grants_case_id", table_name="support_access_grants")
    op.drop_table("support_access_grants")
    op.drop_index("ix_support_cases_user_id", table_name="support_cases")
    op.drop_table("support_cases")
