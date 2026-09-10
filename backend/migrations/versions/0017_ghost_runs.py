"""Recorded runs saved as reusable ghosts, and the attempts to beat them.

A ghost keeps its own copy of the route. The retention service erases raw traces
from `runs` after the policy window (`0006_privacy_retention`), and a benchmark
that quietly disappears when a trace is culled would be worse than not offering
one.

A broadcast ghost exposes recorded history only. Whether the runner is out there
right now is a separate decision, kept in `share_live_location`, and never
implied by publishing the ghost.
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

SQL = """
CREATE TABLE ghost_runs (
 id uuid PRIMARY KEY,
 account_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 run_id uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
 name varchar(80) NOT NULL,
 -- [[lon, lat, ms_from_start], ...]: position and pacing, which is everything
 -- needed to replay the ghost on a client without another round trip.
 path jsonb NOT NULL,
 distance_m double precision NOT NULL,
 duration_s integer NOT NULL,
 -- Denormalised so "ghosts near me" is a bounding-box scan, not a geometry join.
 start_lat double precision NOT NULL,
 start_lon double precision NOT NULL,
 is_public boolean NOT NULL DEFAULT false,
 share_live_location boolean NOT NULL DEFAULT false,
 created_at timestamptz DEFAULT now() NOT NULL,
 UNIQUE (run_id)
);
CREATE INDEX ix_ghost_runs_owner ON ghost_runs(account_id, created_at DESC);
CREATE INDEX ix_ghost_runs_public ON ghost_runs(is_public, start_lat, start_lon);

-- A ghost is a benchmark, not a duel: it is never consumed by being raced, and
-- any number of people can attempt it any number of times.
CREATE TABLE ghost_attempts (
 id uuid PRIMARY KEY,
 ghost_id uuid NOT NULL REFERENCES ghost_runs(id) ON DELETE CASCADE,
 account_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 run_id uuid REFERENCES runs(id) ON DELETE SET NULL,
 started_at timestamptz DEFAULT now() NOT NULL,
 finished_at timestamptz,
 elapsed_s integer,
 beat_ghost boolean
);
CREATE INDEX ix_ghost_attempts_ghost ON ghost_attempts(ghost_id, elapsed_s);
CREATE INDEX ix_ghost_attempts_account ON ghost_attempts(account_id, started_at DESC);

ALTER TABLE ghost_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ghost_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ghost_runs, ghost_attempts FROM anon, authenticated;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    for name in ("ghost_attempts", "ghost_runs"):
        op.drop_table(name)
