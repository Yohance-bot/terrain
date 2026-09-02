"""Replace distance ownership with append-only influence grants.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("source", sa.String(24), nullable=False, server_default="tracked"),
    )
    op.add_column(
        "territory_standings",
        sa.Column("active_influence", sa.Numeric(16, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "territory_standings",
        sa.Column("legacy_influence", sa.Numeric(16, 4), nullable=False, server_default="0"),
    )

    op.create_table(
        "influence_grants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column(
            "device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False
        ),
        sa.Column(
            "territory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("territories.id"),
            nullable=False,
        ),
        sa.Column("territory_version", sa.Integer(), nullable=False),
        sa.Column("pipeline_version", sa.Integer(), nullable=False),
        sa.Column("ruleset_version", sa.Integer(), nullable=False),
        sa.Column("activity", sa.String(16), nullable=False),
        sa.Column("distance_m", sa.Numeric(12, 2), nullable=False),
        sa.Column("moving_time_s", sa.Integer(), nullable=False),
        sa.Column("effort", sa.Numeric(16, 4), nullable=False),
        sa.Column("active_influence", sa.Numeric(16, 4), nullable=False),
        sa.Column("legacy_influence", sa.Numeric(16, 4), nullable=False),
        sa.Column("half_life_days", sa.Numeric(8, 3), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "territory_id", name="uq_influence_grant_run_territory"),
    )
    op.create_index("ix_influence_grants_run_id", "influence_grants", ["run_id"])
    op.create_index("ix_influence_grants_device_id", "influence_grants", ["device_id"])
    op.create_index("ix_influence_grants_territory_id", "influence_grants", ["territory_id"])
    op.create_index(
        "ix_influence_grants_territory_device_granted",
        "influence_grants",
        ["territory_id", "device_id", "granted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_influence_grants_territory_device_granted", table_name="influence_grants")
    op.drop_index("ix_influence_grants_territory_id", table_name="influence_grants")
    op.drop_index("ix_influence_grants_device_id", table_name="influence_grants")
    op.drop_index("ix_influence_grants_run_id", table_name="influence_grants")
    op.drop_table("influence_grants")
    op.drop_column("territory_standings", "legacy_influence")
    op.drop_column("territory_standings", "active_influence")
    op.drop_column("runs", "source")
