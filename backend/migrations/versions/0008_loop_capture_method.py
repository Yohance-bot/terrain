"""Persist the authoritative route-to-territory capture method.

Revision ID: 0008
Revises: 0007
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("run_territory_segments", sa.Column("capture_method", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("run_territory_segments", "capture_method")
