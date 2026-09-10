"""Opt-in live sharing, the live position channel, and the in-app event feed.

Sharing is stored per direction, per friendship, and per capability: choosing to
be seen on the map and choosing to announce a run start are separate columns
because they are separate decisions (`02_WHAT_WE_REFUSE_TO_BECOME`, on
competition never becoming surveillance).

`location_expires_at` is what lets a race scope sharing to its own duration
without touching a player's persistent toggles.
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

SQL = """
CREATE TABLE friend_share_settings (
 -- owner is the person being seen; viewer is the friend allowed to see them.
 owner_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 viewer_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 share_location boolean NOT NULL DEFAULT false,
 notify_on_run_start boolean NOT NULL DEFAULT false,
 -- NULL means "until turned off". A timestamp is a temporary grant, which is
 -- how a race shares position without changing the persistent toggle.
 location_expires_at timestamptz,
 updated_at timestamptz DEFAULT now() NOT NULL,
 PRIMARY KEY (owner_id, viewer_id),
 CHECK (owner_id <> viewer_id)
);
CREATE INDEX ix_share_settings_viewer ON friend_share_settings(viewer_id, share_location);

-- One row per account, overwritten in place. Location history belongs to runs;
-- this table is a presence channel and deliberately keeps no trail.
CREATE TABLE live_positions (
 account_id uuid PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
 lat double precision NOT NULL,
 lon double precision NOT NULL,
 accuracy_m double precision,
 heading double precision,
 speed_mps double precision,
 is_running boolean NOT NULL DEFAULT false,
 run_id uuid,
 updated_at timestamptz DEFAULT now() NOT NULL
);

-- In-app delivery for every social feature. Push notifications would add a
-- transport on top of this table rather than replace it.
CREATE TABLE social_events (
 id bigserial PRIMARY KEY,
 account_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 kind varchar(32) NOT NULL,
 actor_id uuid REFERENCES accounts(id) ON DELETE CASCADE,
 subject_id uuid,
 body varchar(240) NOT NULL,
 created_at timestamptz DEFAULT now() NOT NULL,
 read_at timestamptz
);
CREATE INDEX ix_social_events_inbox ON social_events(account_id, created_at DESC);

ALTER TABLE friend_share_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE live_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE social_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON friend_share_settings, live_positions, social_events FROM anon, authenticated;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    for name in ("social_events", "live_positions", "friend_share_settings"):
        op.drop_table(name)
