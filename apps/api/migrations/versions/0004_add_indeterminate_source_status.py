"""Add an explicit indeterminate source-check status.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGINAL_STATUS_CHECK = (
    "status IN ('baseline_created', 'unchanged', 'changed', 'failed', 'manual')"
)
_INDETERMINATE_STATUS_CHECK = (
    "status IN ('baseline_created', 'unchanged', 'changed', 'failed', 'manual', 'indeterminate')"
)


def upgrade() -> None:
    with op.batch_alter_table("source_check_results", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "ck_source_check_results_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_source_check_results_status",
            _INDETERMINATE_STATUS_CHECK,
        )


def downgrade() -> None:
    op.execute("UPDATE source_check_results SET status = 'manual' WHERE status = 'indeterminate'")
    with op.batch_alter_table("source_check_results", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "ck_source_check_results_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_source_check_results_status",
            _ORIGINAL_STATUS_CHECK,
        )
