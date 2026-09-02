"""Add public loop-area overlays independent of fixed territories.

Revision ID: 0009
Revises: 0008
"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "captured_areas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False, unique=True),
        sa.Column("owner_device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("geom", geoalchemy2.Geography(geometry_type="POLYGON", srid=4326, spatial_index=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_captured_areas_geom", "captured_areas", ["geom"], postgresql_using="gist")
    op.create_index("ix_captured_areas_owner", "captured_areas", ["owner_device_id"])


def downgrade() -> None:
    op.drop_index("ix_captured_areas_owner", table_name="captured_areas")
    op.drop_index("ix_captured_areas_geom", table_name="captured_areas")
    op.drop_table("captured_areas")
