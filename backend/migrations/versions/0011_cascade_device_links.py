"""Cascade links when disposable local test devices are removed.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("device_links_device_id_fkey", "device_links", type_="foreignkey")
    op.create_foreign_key(
        "device_links_device_id_fkey",
        "device_links",
        "devices",
        ["device_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("device_links_device_id_fkey", "device_links", type_="foreignkey")
    op.create_foreign_key(
        "device_links_device_id_fkey", "device_links", "devices", ["device_id"], ["id"]
    )
