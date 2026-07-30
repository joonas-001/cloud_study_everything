"""Audit the response-declared model for market synthesis.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("market_research_runs") as batch:
        batch.add_column(sa.Column("response_model_id", sa.String(length=100), nullable=True))
    with op.batch_alter_table("market_research_synthesis_attempts") as batch:
        batch.add_column(sa.Column("response_model_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("market_research_synthesis_attempts") as batch:
        batch.drop_column("response_model_id")
    with op.batch_alter_table("market_research_runs") as batch:
        batch.drop_column("response_model_id")
