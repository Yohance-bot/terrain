"""Disposable test accounts for the console's test lab.

This table is the allowlist that makes session minting safe. An operator
endpoint can issue a real player session, which is the only way the console can
exercise the same endpoints the phone calls — so it must be impossible to point
that endpoint at a real player. A session is only ever minted for an account
listed here, and only the lab ever inserts into it.

It doubles as the teardown manifest: everything the lab created is reachable
from these rows.
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

SQL = """
CREATE TABLE sandbox_accounts (
 account_id uuid PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
 -- The device the lab drives this runner through. Kept here so teardown can
 -- find the run ledger without trusting a naming convention.
 device_id uuid NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 label varchar(64) NOT NULL,
 created_by varchar(128),
 created_at timestamptz DEFAULT now() NOT NULL
);
CREATE INDEX ix_sandbox_accounts_device ON sandbox_accounts(device_id);

ALTER TABLE sandbox_accounts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sandbox_accounts FROM anon, authenticated;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.drop_table("sandbox_accounts")
