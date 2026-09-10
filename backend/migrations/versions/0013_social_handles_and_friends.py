"""Findable account handles and the friendship graph every social feature gates on.

Handles are assigned by a database trigger rather than by the sign-up code paths.
Account creation happens in three places (provider auth, developer login, local
accounts) and none of them should have to know about social features; a trigger
also guarantees that accounts created before this migration — and any created by
a future path — are findable without a backfill task per code path.
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

SQL = """
ALTER TABLE accounts ADD COLUMN handle varchar(24);

-- Shared by the insert trigger and the one-time backfill below so a handle is
-- derived exactly one way. Collisions resolve to a numeric suffix, and only
-- fall back to randomness once a name is contested enough to be unreadable.
CREATE FUNCTION next_account_handle(source text) RETURNS text AS $$
DECLARE base text; candidate text; suffix int := 0;
BEGIN
  base := lower(regexp_replace(coalesce(source, ''), '[^a-zA-Z0-9_]', '', 'g'));
  base := left(base, 18);
  IF length(base) < 3 THEN base := 'runner' || base; END IF;
  candidate := base;
  WHILE EXISTS (SELECT 1 FROM accounts WHERE handle = candidate) LOOP
    suffix := suffix + 1;
    IF suffix > 50 THEN
      candidate := base || floor(random() * 1000000)::int::text;
    ELSE
      candidate := base || suffix::text;
    END IF;
  END LOOP;
  RETURN candidate;
END $$ LANGUAGE plpgsql;

CREATE FUNCTION assign_account_handle() RETURNS trigger AS $$
BEGIN
  IF NEW.handle IS NULL THEN
    NEW.handle := next_account_handle(NEW.display_name);
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER accounts_assign_handle BEFORE INSERT ON accounts
  FOR EACH ROW EXECUTE FUNCTION assign_account_handle();

DO $$
DECLARE row record;
BEGIN
  FOR row IN SELECT id, display_name FROM accounts WHERE handle IS NULL LOOP
    UPDATE accounts SET handle = next_account_handle(row.display_name) WHERE id = row.id;
  END LOOP;
END $$;

ALTER TABLE accounts ALTER COLUMN handle SET NOT NULL;
CREATE UNIQUE INDEX ux_accounts_handle ON accounts(handle);

-- One row per pair of accounts for the lifetime of that pair. The unique index
-- is on the *ordered* pair, so A→B and B→A cannot both exist as open requests
-- and a block cannot be escaped by re-requesting from the other side.
CREATE TABLE friendships (
 id uuid PRIMARY KEY,
 requester_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 addressee_id uuid NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 status varchar(16) NOT NULL CHECK (status IN ('pending','accepted','declined','blocked')),
 -- Set only for 'blocked'. Kept explicit because either side of an existing
 -- friendship can be the one who blocks, which the row's direction cannot say.
 blocked_by uuid REFERENCES accounts(id) ON DELETE CASCADE,
 created_at timestamptz DEFAULT now() NOT NULL,
 updated_at timestamptz DEFAULT now() NOT NULL,
 CHECK (requester_id <> addressee_id)
);
CREATE UNIQUE INDEX ux_friendships_pair ON friendships
 (LEAST(requester_id, addressee_id), GREATEST(requester_id, addressee_id));
CREATE INDEX ix_friendships_requester ON friendships(requester_id, status);
CREATE INDEX ix_friendships_addressee ON friendships(addressee_id, status);

ALTER TABLE friendships ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON friendships FROM anon, authenticated;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute(
        """
        DROP TABLE IF EXISTS friendships;
        DROP TRIGGER IF EXISTS accounts_assign_handle ON accounts;
        DROP FUNCTION IF EXISTS assign_account_handle();
        DROP FUNCTION IF EXISTS next_account_handle(text);
        DROP INDEX IF EXISTS ux_accounts_handle;
        ALTER TABLE accounts DROP COLUMN IF EXISTS handle;
        """
    )
