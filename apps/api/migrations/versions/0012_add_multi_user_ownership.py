"""Add milestone 9B internal subjects and object ownership.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-05
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_OWNER_USER_ID = "8f369a6e-8b7d-4a45-9f40-39bcfd6ac789"
LEGACY_OWNER_IDENTITY_ID = "f77938bb-bce8-45e8-9340-ab9908462e19"
LEGACY_OWNER_EVENT_ID = "54f318bc-ad3d-4908-9ad7-13325cd6bb80"

USER_OWNED_TABLES = (
    "user_settings",
    "diagnostic_sessions",
    "diagnostic_answers",
    "diagnostic_events",
    "planning_proposals",
    "planning_units",
    "planning_unit_sources",
    "planning_change_events",
    "notification_preferences",
    "notifications",
    "email_outbox",
    "ai_provider_profiles",
    "learning_runs",
    "learning_run_locks",
    "learning_unit_instances",
    "learning_activities",
    "activity_attempts",
    "activity_evaluations",
    "mastery_evidence",
    "mastery_snapshots",
    "review_tasks",
    "learning_events",
    "learning_independent_reviews",
    "runner_invocations",
    "user_goal_selections",
    "readiness_evaluations",
    "path_comparisons",
    "path_comparison_decisions",
    "readiness_events",
    "market_research_runs",
    "market_research_synthesis_attempts",
    "market_research_events",
    "monetization_experiments",
    "experiment_independent_reviews",
    "experiment_action_records",
    "experiment_outcomes",
    "experiment_income_records",
    "experiment_income_revisions",
    "experiment_feedback_suggestions",
    "experiment_events",
)

LEGACY_USER_OWNED_TABLES = tuple(
    table_name for table_name in USER_OWNED_TABLES if table_name != "user_settings"
)

SCOPED_PARTIAL_INDEXES = (
    (
        "uq_active_diagnostic_skill_version",
        "diagnostic_sessions",
        ("user_id", "skill_id", "skill_version"),
        "status = 'active'",
    ),
    (
        "uq_nonterminal_learning_run_skill_version",
        "learning_runs",
        ("user_id", "skill_id", "skill_version"),
        "status IN ('active', 'paused', 'retention_pending')",
    ),
    (
        "uq_active_user_goal_scope",
        "user_goal_selections",
        ("user_id", "skill_id", "skill_version", "capability_scope_id"),
        "superseded_at IS NULL",
    ),
    (
        "uq_active_market_research_run",
        "market_research_runs",
        ("user_id", "catalog_id", "catalog_version"),
        "status IN ('source_pending', 'synthesis_pending', "
        "'synthesis_in_progress', 'review_pending')",
    ),
)

GLOBAL_PARTIAL_INDEXES = (
    (
        "uq_automatic_source_check_local_date",
        "source_check_runs",
        ("skill_id", "skill_version", "local_date"),
        "trigger = 'automatic'",
    ),
    (
        "uq_active_runner_invocation",
        "runner_invocations",
        ("singleton_key",),
        "status IN ('queued', 'running')",
    ),
)


def _create_subject_tables() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'deletion_pending', 'deleted')",
            name="ck_users_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "external_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identity_subject"),
    )
    op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"])
    op.create_table(
        "user_role_assignments",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'owner_operator', 'support_restricted')",
            name="ck_user_role_assignments_role",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "account_state_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('active', 'suspended', 'deletion_pending', 'deleted')",
            name="ck_account_state_events_previous_status",
        ),
        sa.CheckConstraint(
            "new_status IN ('active', 'suspended', 'deletion_pending', 'deleted')",
            name="ck_account_state_events_new_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_account_state_events_user_id", "account_state_events", ["user_id"])
    op.create_index(
        "ix_account_state_events_actor_user_id", "account_state_events", ["actor_user_id"]
    )


def _seed_legacy_owner() -> None:
    migrated_at = datetime.now(UTC)
    op.bulk_insert(
        sa.table(
            "users",
            sa.column("id", sa.String()),
            sa.column("status", sa.String()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": LEGACY_OWNER_USER_ID,
                "status": "active",
                "created_at": migrated_at,
                "updated_at": migrated_at,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "user_role_assignments",
            sa.column("user_id", sa.String()),
            sa.column("role", sa.String()),
            sa.column("assigned_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "user_id": LEGACY_OWNER_USER_ID,
                "role": "owner_operator",
                "assigned_at": migrated_at,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "account_state_events",
            sa.column("id", sa.String()),
            sa.column("user_id", sa.String()),
            sa.column("actor_user_id", sa.String()),
            sa.column("previous_status", sa.String()),
            sa.column("new_status", sa.String()),
            sa.column("reason_code", sa.String()),
            sa.column("occurred_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": LEGACY_OWNER_EVENT_ID,
                "user_id": LEGACY_OWNER_USER_ID,
                "actor_user_id": None,
                "previous_status": None,
                "new_status": "active",
                "reason_code": "milestone_9b_legacy_backfill",
                "occurred_at": migrated_at,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "external_identities",
            sa.column("id", sa.String()),
            sa.column("user_id", sa.String()),
            sa.column("issuer", sa.String()),
            sa.column("subject", sa.String()),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": LEGACY_OWNER_IDENTITY_ID,
                "user_id": LEGACY_OWNER_USER_ID,
                "issuer": "urn:cloud-study:legacy",
                "subject": "owner",
                "created_at": migrated_at,
            }
        ],
    )


def _create_user_settings() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("external_ai_enabled", sa.Boolean(), nullable=False),
        sa.Column("inactivity_timeout_minutes", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "inactivity_timeout_minutes >= 1",
            name="ck_user_settings_positive_timeout",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_settings_user"),
    )
    op.create_index("ix_user_settings_user_id", "user_settings", ["user_id"])
    op.execute(
        "INSERT INTO user_settings ("
        "user_id, external_ai_enabled, inactivity_timeout_minutes, updated_at"
        ") SELECT "
        f"'{LEGACY_OWNER_USER_ID}', external_ai_enabled, inactivity_timeout_minutes, updated_at "
        "FROM app_settings WHERE id = 1"
    )


def _add_ownership(table_name: str) -> None:
    op.add_column(table_name, sa.Column("user_id", sa.String(length=36), nullable=True))
    op.execute(
        f"UPDATE \"{table_name}\" SET user_id = '{LEGACY_OWNER_USER_ID}' WHERE user_id IS NULL"
    )
    with op.batch_alter_table(table_name, recreate="auto") as batch:
        batch.alter_column("user_id", existing_type=sa.String(length=36), nullable=False)
        batch.create_foreign_key(
            f"fk_{table_name}_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(f"ix_{table_name}_user_id", ["user_id"])
        if table_name == "notification_preferences":
            batch.drop_constraint("ck_notification_preferences_singleton", type_="check")
            batch.create_unique_constraint("uq_notification_preferences_user", ["user_id"])


def _configure_postgresql_integer_ids() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name in ("user_settings", "notification_preferences"):
        op.execute(
            sa.text(
                f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                f'COALESCE((SELECT MAX(id) FROM "{table_name}"), 0) + 1, false)'
            )
        )


def _configure_postgresql_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name in USER_OWNED_TABLES:
        op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE POLICY "pl_{table_name}_user_isolation" ON "{table_name}" '
                "USING (user_id = current_setting('cloud_study.user_id', true)) "
                "WITH CHECK (user_id = current_setting('cloud_study.user_id', true))"
            )
        )


def _drop_partial_indexes() -> None:
    for name, table_name, _columns, _predicate in (
        *SCOPED_PARTIAL_INDEXES,
        *GLOBAL_PARTIAL_INDEXES,
    ):
        op.drop_index(name, table_name=table_name)


def _create_partial_indexes(scoped: bool) -> None:
    for name, table_name, scoped_columns, predicate in SCOPED_PARTIAL_INDEXES:
        columns = scoped_columns if scoped else tuple(scoped_columns[1:])
        options = {"sqlite_where": sa.text(predicate)}
        if scoped:
            options["postgresql_where"] = sa.text(predicate)
        op.create_index(name, table_name, list(columns), unique=True, **options)
    for name, table_name, columns, predicate in GLOBAL_PARTIAL_INDEXES:
        options = {"sqlite_where": sa.text(predicate)}
        if scoped:
            options["postgresql_where"] = sa.text(predicate)
        op.create_index(name, table_name, list(columns), unique=True, **options)


def upgrade() -> None:
    _create_subject_tables()
    _seed_legacy_owner()
    _create_user_settings()
    _drop_partial_indexes()
    for table_name in LEGACY_USER_OWNED_TABLES:
        _add_ownership(table_name)
    _create_partial_indexes(scoped=True)
    _configure_postgresql_integer_ids()
    _configure_postgresql_rls()


def _assert_owner_only() -> None:
    other_users = (
        op.get_bind()
        .execute(
            sa.text("SELECT COUNT(*) FROM users WHERE id <> :owner"),
            {"owner": LEGACY_OWNER_USER_ID},
        )
        .scalar_one()
    )
    if other_users:
        raise RuntimeError(
            "0012 downgrade refused: restore the pre-9B snapshot instead of collapsing "
            "multiple user histories into the legacy single-user schema"
        )


def _drop_ownership(table_name: str) -> None:
    with op.batch_alter_table(table_name, recreate="auto") as batch:
        if table_name == "notification_preferences":
            batch.drop_constraint("uq_notification_preferences_user", type_="unique")
            batch.create_check_constraint("ck_notification_preferences_singleton", "id = 1")
        batch.drop_index(f"ix_{table_name}_user_id")
        batch.drop_constraint(f"fk_{table_name}_user_id_users", type_="foreignkey")
        batch.drop_column("user_id")


def downgrade() -> None:
    _assert_owner_only()
    _drop_partial_indexes()
    if op.get_bind().dialect.name == "postgresql":
        for table_name in USER_OWNED_TABLES:
            op.execute(sa.text(f'DROP POLICY "pl_{table_name}_user_isolation" ON "{table_name}"'))
            op.execute(sa.text(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY'))
    for table_name in reversed(LEGACY_USER_OWNED_TABLES):
        _drop_ownership(table_name)
    op.drop_index("ix_user_settings_user_id", table_name="user_settings")
    op.drop_table("user_settings")
    _create_partial_indexes(scoped=False)
    op.drop_index("ix_account_state_events_user_id", table_name="account_state_events")
    op.drop_index("ix_account_state_events_actor_user_id", table_name="account_state_events")
    op.drop_table("account_state_events")
    op.drop_table("user_role_assignments")
    op.drop_index("ix_external_identities_user_id", table_name="external_identities")
    op.drop_table("external_identities")
    op.drop_table("users")
