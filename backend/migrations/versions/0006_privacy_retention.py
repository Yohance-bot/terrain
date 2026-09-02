"""Add server-enforced raw-trace retention and device deletion markers.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("privacy_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("raw_trace_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("route_reduced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_runs_raw_trace_retention",
        "runs",
        ["ended_at"],
        postgresql_where=sa.text("raw_trace_deleted_at IS NULL"),
    )
    op.create_index(
        "ix_runs_route_reduction",
        "runs",
        ["ended_at"],
        postgresql_where=sa.text("route_reduced_at IS NULL AND geom IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_runs_route_reduction", table_name="runs")
    op.drop_index("ix_runs_raw_trace_retention", table_name="runs")
    op.drop_column("runs", "route_reduced_at")
    op.drop_column("runs", "raw_trace_deleted_at")
    op.drop_column("devices", "privacy_deleted_at")
