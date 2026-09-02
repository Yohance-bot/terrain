"""Add additive player accounts and local-only developer action logging.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.String(length=32), nullable=False),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="player"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "account_auth_methods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "provider_subject", name="uq_account_auth_provider_subject"),
    )
    op.create_index("ix_account_auth_methods_account_id", "account_auth_methods", ["account_id"])
    op.create_table(
        "device_links",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_device_links_account_id", "device_links", ["account_id"])
    op.create_table(
        "account_deletion_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_account_deletion_requests_account_id", "account_deletion_requests", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_account_deletion_requests_account_id", table_name="account_deletion_requests")
    op.drop_table("account_deletion_requests")
    op.drop_index("ix_device_links_account_id", table_name="device_links")
    op.drop_table("device_links")
    op.drop_index("ix_account_auth_methods_account_id", table_name="account_auth_methods")
    op.drop_table("account_auth_methods")
    op.drop_table("accounts")
