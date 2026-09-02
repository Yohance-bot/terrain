"""Add run lifecycle, configuration, and audit foundations.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("ruleset_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "runs",
        sa.Column("lifecycle_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("runs", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "run_lifecycle_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("actor_kind", sa.String(32), nullable=False, server_default="system"),
        sa.Column("actor_ref", sa.String(128), nullable=True),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_lifecycle_sequence"),
    )
    op.create_index("ix_run_lifecycle_events_run_id", "run_lifecycle_events", ["run_id"])

    op.create_table(
        "configuration_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("created_by_kind", sa.String(32), nullable=False, server_default="system"),
        sa.Column("created_by_ref", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("namespace", "version", name="uq_configuration_namespace_version"),
    )
    op.create_index(
        "ix_configuration_revisions_namespace_status",
        "configuration_revisions",
        ["namespace", "status"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor_kind", sa.String(32), nullable=False),
        sa.Column("actor_ref", sa.String(128), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_ref", sa.String(128), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_events_target", "audit_events", ["target_type", "target_ref"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_target", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(
        "ix_configuration_revisions_namespace_status",
        table_name="configuration_revisions",
    )
    op.drop_table("configuration_revisions")
    op.drop_index("ix_run_lifecycle_events_run_id", table_name="run_lifecycle_events")
    op.drop_table("run_lifecycle_events")
    op.drop_column("runs", "processed_at")
    op.drop_column("runs", "lifecycle_version")
    op.drop_column("runs", "ruleset_version")
