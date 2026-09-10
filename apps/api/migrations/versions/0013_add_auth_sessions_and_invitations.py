"""Add milestone 9C authentication, session, and invitation state.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_invitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("accepted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('user', 'support_restricted')",
            name="ck_account_invitations_role",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_account_invitations_positive_lifetime",
        ),
        sa.CheckConstraint(
            "(accepted_at IS NULL AND accepted_by_user_id IS NULL) OR "
            "(accepted_at IS NOT NULL AND accepted_by_user_id IS NOT NULL)",
            name="ck_account_invitations_acceptance_pair",
        ),
        sa.CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL",
            name="ck_account_invitations_single_terminal_state",
        ),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_sha256"),
    )
    op.create_index(
        "ix_account_invitations_created_by_user_id",
        "account_invitations",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_account_invitations_accepted_by_user_id",
        "account_invitations",
        ["accepted_by_user_id"],
    )
    op.create_table(
        "application_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mfa_authenticated", sa.Boolean(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_application_sessions_idle_within_absolute",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_sha256"),
    )
    op.create_index("ix_application_sessions_user_id", "application_sessions", ["user_id"])
    op.create_table(
        "oidc_login_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("state_sha256", sa.String(length=64), nullable=False),
        sa.Column("nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("encrypted_pkce_verifier", sa.Text(), nullable=False),
        sa.Column("invitation_id", sa.String(length=36), nullable=True),
        sa.Column("prior_session_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_oidc_login_transactions_positive_lifetime",
        ),
        sa.ForeignKeyConstraint(["invitation_id"], ["account_invitations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["prior_session_id"], ["application_sessions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_sha256"),
    )
    op.create_index(
        "ix_oidc_login_transactions_invitation_id",
        "oidc_login_transactions",
        ["invitation_id"],
    )
    op.create_index(
        "ix_oidc_login_transactions_prior_session_id",
        "oidc_login_transactions",
        ["prior_session_id"],
    )
    op.create_table(
        "auth_security_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_security_events_user_id", "auth_security_events", ["user_id"])
    op.create_index(
        "ix_auth_security_events_correlation_id",
        "auth_security_events",
        ["correlation_id"],
    )
    op.create_table(
        "auth_rate_limit_buckets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("key_sha256", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "attempt_count >= 1",
            name="ck_auth_rate_limit_buckets_positive_attempts",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action", "key_sha256", name="uq_auth_rate_limit_bucket"),
    )


def downgrade() -> None:
    op.drop_table("auth_rate_limit_buckets")
    op.drop_index("ix_auth_security_events_correlation_id", table_name="auth_security_events")
    op.drop_index("ix_auth_security_events_user_id", table_name="auth_security_events")
    op.drop_table("auth_security_events")
    op.drop_index(
        "ix_oidc_login_transactions_prior_session_id",
        table_name="oidc_login_transactions",
    )
    op.drop_index(
        "ix_oidc_login_transactions_invitation_id",
        table_name="oidc_login_transactions",
    )
    op.drop_table("oidc_login_transactions")
    op.drop_index("ix_application_sessions_user_id", table_name="application_sessions")
    op.drop_table("application_sessions")
    op.drop_index("ix_account_invitations_accepted_by_user_id", table_name="account_invitations")
    op.drop_index("ix_account_invitations_created_by_user_id", table_name="account_invitations")
    op.drop_table("account_invitations")
