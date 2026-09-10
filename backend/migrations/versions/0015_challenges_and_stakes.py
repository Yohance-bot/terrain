"""Head-to-head challenges, and loop closures staked on their outcome.

Only metrics the pipeline already measures are available as challenge
conditions; nothing here introduces a new tracked quantity.

Stakes are restricted to captured areas on purpose. `territory_ownership` is a
derived projection that `services/ownership.recompute_ownership` rebuilds from
the influence ledger, so a wagered transfer written there would be silently
reverted by the next applied run. A captured area has real stored ownership,
which is what makes it transferable.
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

SQL = """
CREATE TABLE challenges (
 id uuid PRIMARY KEY,
 challenger_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 opponent_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 -- Every value here maps to a column the run pipeline already writes.
 metric varchar(24) NOT NULL CHECK (metric IN
   ('distance','runs','moving_time','captured_area','territories')),
 -- 'most' compares totals at the end of the window; 'fastest_to' compares who
 -- passed target_value first.
 comparison varchar(16) NOT NULL CHECK (comparison IN ('most','fastest_to')),
 target_value double precision,
 window_start timestamptz NOT NULL,
 window_end timestamptz NOT NULL,
 goal_text varchar(240) NOT NULL,
 status varchar(16) NOT NULL CHECK (status IN
   ('pending','accepted','declined','cancelled','expired','resolved')),
 accept_deadline timestamptz NOT NULL,
 outcome varchar(16) CHECK (outcome IN ('challenger','opponent','draw','nobody')),
 winner_id uuid REFERENCES accounts(id) ON DELETE SET NULL,
 challenger_value double precision,
 opponent_value double precision,
 resolved_at timestamptz,
 created_at timestamptz DEFAULT now() NOT NULL,
 updated_at timestamptz DEFAULT now() NOT NULL,
 CHECK (challenger_id <> opponent_id),
 CHECK (window_end > window_start),
 CHECK (comparison <> 'fastest_to' OR target_value IS NOT NULL)
);
CREATE INDEX ix_challenges_challenger ON challenges(challenger_id, status);
CREATE INDEX ix_challenges_opponent ON challenges(opponent_id, status);
-- The resolver's working set: everything still open, ordered by when it is due.
CREATE INDEX ix_challenges_due ON challenges(status, window_end);

CREATE TABLE challenge_stakes (
 challenge_id uuid PRIMARY KEY REFERENCES challenges(id) ON DELETE CASCADE,
 -- The challenger's own loop closure, put up for the outcome.
 staked_area_id uuid REFERENCES captured_areas(id) ON DELETE SET NULL,
 -- The opponent must already hold this much enclosed area to be allowed to
 -- accept. Checked at accept time, against their area as it stands then.
 require_opponent_area_m2 double precision,
 transferred_at timestamptz
);

-- A transferred area keeps its run linkage; only ownership moves, and the move
-- is recorded so a transfer can always be traced back to the challenge.
ALTER TABLE captured_areas ADD COLUMN transferred_from_device_id uuid REFERENCES devices(id);
ALTER TABLE captured_areas ADD COLUMN transferred_at timestamptz;
ALTER TABLE captured_areas ADD COLUMN transferred_by_challenge_id uuid REFERENCES challenges(id);

ALTER TABLE challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE challenge_stakes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON challenges, challenge_stakes FROM anon, authenticated;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute(
        """
        ALTER TABLE captured_areas DROP COLUMN IF EXISTS transferred_by_challenge_id;
        ALTER TABLE captured_areas DROP COLUMN IF EXISTS transferred_at;
        ALTER TABLE captured_areas DROP COLUMN IF EXISTS transferred_from_device_id;
        DROP TABLE IF EXISTS challenge_stakes;
        DROP TABLE IF EXISTS challenges;
        """
    )
