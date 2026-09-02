"""Add device-scoped Home selection for S4 progression.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_profiles",
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            primary_key=True,
        ),
        sa.Column(
            "home_territory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("territories.id"),
            nullable=True,
        ),
        sa.Column("home_selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("home_change_available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("home_selection_source", sa.String(24), nullable=True),
        sa.Column("home_selection_note", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_device_profiles_home_territory_id",
        "device_profiles",
        ["home_territory_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_device_profiles_home_territory_id", table_name="device_profiles")
    op.drop_table("device_profiles")
