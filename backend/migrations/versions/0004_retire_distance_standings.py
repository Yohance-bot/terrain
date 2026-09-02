"""Clear non-replayable M1 distance standings.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A raw-distance balance cannot be converted into a valid influence grant:
    # it has neither the contemporaneous share nor the activity/decay inputs.
    # Retaining it would leave an owner selected by a superseded rule, so Phase 1
    # begins neutral until server-authoritative grants are earned.
    op.execute(
        """
        UPDATE territory_ownership
        SET previous_owner_id = owner_device_id,
            owner_device_id = NULL,
            since = NOW()
        WHERE owner_device_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE territory_standings
        SET total_distance_m = 0,
            active_influence = 0,
            legacy_influence = 0,
            updated_at = NOW()
        """
    )


def downgrade() -> None:
    # The discarded raw-distance leaderboard is intentionally not recoverable.
    pass
