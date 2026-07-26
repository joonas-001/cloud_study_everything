"""Initialize the versioned local database.

Revision ID: 0001
Revises:
Create Date: 2026-07-27
"""

from collections.abc import Sequence


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Establish the initial migration revision."""


def downgrade() -> None:
    """Remove the initial migration revision."""
