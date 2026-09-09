"""Named console accounts, shared notes and revocable login sessions."""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SQL = """
CREATE TABLE console_users (
 id uuid PRIMARY KEY, display_name varchar(64) NOT NULL,
 role varchar(16) NOT NULL CHECK (role IN ('owner','admin')),
 active boolean NOT NULL, created_at timestamptz DEFAULT now() NOT NULL
);
CREATE TABLE login_credentials (
 id uuid PRIMARY KEY, scope varchar(16) NOT NULL CHECK (scope IN ('app','admin')),
 principal_id uuid NOT NULL, username varchar(32) NOT NULL, password_hash varchar(512) NOT NULL,
 UNIQUE(scope, username), UNIQUE(scope, principal_id)
);
CREATE TABLE auth_sessions (
 token_hash varchar(64) PRIMARY KEY, scope varchar(16) NOT NULL CHECK (scope IN ('app','admin')),
 principal_id uuid NOT NULL, expires_at timestamptz NOT NULL,
 created_at timestamptz DEFAULT now() NOT NULL
);
CREATE INDEX ix_auth_sessions_principal_id ON auth_sessions(principal_id);
CREATE TABLE console_notes (
 id uuid PRIMARY KEY, author_id uuid NOT NULL REFERENCES console_users(id),
 title varchar(120) NOT NULL, body text NOT NULL,
 status varchar(16) NOT NULL CHECK (status IN ('open','done')),
 created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz DEFAULT now() NOT NULL
);
ALTER TABLE console_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE login_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE console_notes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON console_users, login_credentials, auth_sessions, console_notes FROM anon, authenticated;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    for name in ("console_notes", "auth_sessions", "login_credentials", "console_users"):
        op.drop_table(name)
