"""The athlete's side of a run: what it measured, what they wrote, what they wore.

Everything a training profile shows is derived from runs the ledger already
holds, so nothing here changes how a run is scored or matched:

- `run_metrics` / `run_best_efforts` cache numbers computed from a run's own
  samples (moving time, splits, best efforts, elevation). They are rebuilt when
  `metrics_version` moves, which is why they live beside the run, not on it.
- Altitude and weather were never captured. They arrive with new runs; older
  runs simply have no elevation, which the profile says rather than guesses.
- Titles, notes, shoes, weekly goals and body weight are the athlete's own
  entries, owned by the account rather than a device.
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

TABLES = (
    "run_metrics",
    "run_best_efforts",
    "shoes",
    "run_annotations",
    "weekly_goals",
    "athlete_settings",
)

SQL = """
ALTER TABLE runs
  ADD COLUMN sample_altitude_m double precision[],
  ADD COLUMN temperature_c double precision,
  ADD COLUMN weather_code integer;

CREATE TABLE run_metrics (
 run_id uuid PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
 metrics_version integer NOT NULL,
 moving_s integer NOT NULL,
 elevation_gain_m double precision,
 elevation_loss_m double precision,
 splits jsonb NOT NULL DEFAULT '[]'::jsonb,
 pace_series jsonb NOT NULL DEFAULT '[]'::jsonb,
 elevation_series jsonb NOT NULL DEFAULT '[]'::jsonb,
 computed_at timestamptz DEFAULT now() NOT NULL
);

CREATE TABLE run_best_efforts (
 run_id uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
 distance_m integer NOT NULL,
 elapsed_s double precision NOT NULL CHECK (elapsed_s > 0),
 PRIMARY KEY (run_id, distance_m)
);
CREATE INDEX ix_run_best_efforts_distance ON run_best_efforts(distance_m, elapsed_s);

CREATE TABLE shoes (
 id uuid PRIMARY KEY,
 account_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 name varchar(48) NOT NULL,
 is_default boolean NOT NULL DEFAULT false,
 retired boolean NOT NULL DEFAULT false,
 created_at timestamptz DEFAULT now() NOT NULL
);
CREATE INDEX ix_shoes_account ON shoes(account_id);
-- One default pair per athlete, so a new run is never ambiguous about its shoes.
CREATE UNIQUE INDEX ux_shoes_one_default ON shoes(account_id) WHERE is_default;

CREATE TABLE run_annotations (
 run_id uuid PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
 title varchar(80),
 note varchar(1000),
 shoe_id uuid REFERENCES shoes(id) ON DELETE SET NULL,
 updated_at timestamptz DEFAULT now() NOT NULL
);
CREATE INDEX ix_run_annotations_shoe ON run_annotations(shoe_id);

CREATE TABLE weekly_goals (
 account_id uuid PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
 metric varchar(16) NOT NULL CHECK (metric IN ('distance', 'time', 'runs')),
 target double precision NOT NULL CHECK (target > 0),
 updated_at timestamptz DEFAULT now() NOT NULL
);

CREATE TABLE athlete_settings (
 account_id uuid PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
 weight_kg double precision CHECK (weight_kg IS NULL OR (weight_kg >= 25 AND weight_kg <= 300)),
 updated_at timestamptz DEFAULT now() NOT NULL
);
"""


def upgrade():
    op.execute(SQL)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {table} FROM anon, authenticated")


def downgrade():
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute(
        "ALTER TABLE runs DROP COLUMN IF EXISTS sample_altitude_m, "
        "DROP COLUMN IF EXISTS temperature_c, DROP COLUMN IF EXISTS weather_code"
    )
