"""Milestone 1 initial schema.

Territories, devices, runs, the append-only segment ledger, derived standings,
and ownership. No influence model.

Revision ID: 0001
Revises:
"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "territories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("city", sa.String(64), nullable=False),
        sa.Column("area", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geography(
                geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("slug", "version", name="uq_territory_slug_version"),
    )
    op.create_index("ix_territories_geom", "territories", ["geom"], postgresql_using="gist")
    op.create_index("ix_territories_city_area", "territories", ["city", "area"])

    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("label", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column(
            "geom",
            geoalchemy2.Geography(geometry_type="LINESTRING", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("sample_ts", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("sample_accuracy_m", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="submitted"),
        sa.Column("pipeline_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_runs_device_id", "runs", ["device_id"])
    op.create_index("ix_runs_geom", "runs", ["geom"], postgresql_using="gist")

    op.create_table(
        "run_territory_segments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=False,
        ),
        sa.Column(
            "territory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("territories.id"),
            nullable=False,
        ),
        sa.Column("territory_version", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Numeric(12, 2), nullable=False),
        sa.Column("seconds_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "caused_ownership_change", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_segments_run_id", "run_territory_segments", ["run_id"])
    op.create_index("ix_segments_device_id", "run_territory_segments", ["device_id"])
    op.create_index("ix_segments_territory_id", "run_territory_segments", ["territory_id"])

    op.create_table(
        "territory_standings",
        sa.Column(
            "territory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("territories.id"),
            primary_key=True,
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            primary_key=True,
        ),
        sa.Column("total_distance_m", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "territory_ownership",
        sa.Column(
            "territory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("territories.id"),
            primary_key=True,
        ),
        sa.Column(
            "owner_device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=True,
        ),
        sa.Column(
            "previous_owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=True,
        ),
        sa.Column("since", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("territory_ownership")
    op.drop_table("territory_standings")
    op.drop_table("run_territory_segments")
    op.drop_table("runs")
    op.drop_table("devices")
    op.drop_table("territories")
