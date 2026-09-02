"""Index device-scoped internal review queue lookups.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_runs_review_queue",
        "runs",
        ["device_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_runs_review_queue", table_name="runs")
