"""Pin-drop races between friends, with sharing scoped to the race itself.

A race reuses the friend-sharing channel rather than adding a second one: while
it runs, each side gets a temporary grant that expires with the race, leaving
their standing choices untouched.

Arrival is a proximity radius, not an exact point. Asking someone to hit an
exact coordinate is asking them to stare at a phone while moving.
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

SQL = """
CREATE TABLE races (
 id uuid PRIMARY KEY,
 challenger_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 opponent_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 pin_lat double precision NOT NULL CHECK (pin_lat BETWEEN -90 AND 90),
 pin_lon double precision NOT NULL CHECK (pin_lon BETWEEN -180 AND 180),
 pin_label varchar(80),
 radius_m double precision NOT NULL DEFAULT 25 CHECK (radius_m BETWEEN 10 AND 100),
 status varchar(16) NOT NULL CHECK (status IN
   ('pending','running','finished','declined','cancelled','expired')),
 accept_deadline timestamptz NOT NULL,
 started_at timestamptz,
 -- An abandoned race simply lapses; nobody is told they lost by walking away.
 expires_at timestamptz,
 winner_id uuid REFERENCES accounts(id) ON DELETE SET NULL,
 finished_at timestamptz,
 created_at timestamptz DEFAULT now() NOT NULL,
 updated_at timestamptz DEFAULT now() NOT NULL,
 CHECK (challenger_id <> opponent_id)
);
CREATE INDEX ix_races_challenger ON races(challenger_id, status);
CREATE INDEX ix_races_opponent ON races(opponent_id, status);
CREATE INDEX ix_races_open ON races(status, expires_at);

ALTER TABLE races ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON races FROM anon, authenticated;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.drop_table("races")
