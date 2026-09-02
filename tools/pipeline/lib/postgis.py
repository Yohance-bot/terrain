"""Database access for the publish stage.

Only stage 09 touches the database, and only the Milestone 1 `territories`
table. The pipeline does not create schema, does not run migrations, and does
not write ownership, standings or run data -- those belong to the backend and
to gameplay, both explicitly out of scope for Milestone 2.

Connection resolution is implemented here because it is small and shared. The
actual upsert is left to Phase B, with its contract spelled out below.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATABASE_URL = "postgresql://localhost:5432/run_prototype"


def resolve_database_url(repo_root: Path) -> str:
    """Find the database the backend is already using.

    Order: `DATABASE_URL` in the environment, then `backend/.env`, then the
    local default. Reading the backend's env file means the pipeline cannot
    publish into a different database than the API serves from, which would be
    a confusing way to lose an afternoon.

    The SQLAlchemy driver prefix the backend uses (`postgresql+psycopg://`) is
    stripped, since psycopg connects with a plain libpq URL.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        env_file = repo_root / "backend" / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "DATABASE_URL":
                    url = value.strip().strip('"').strip("'")
                    break
    url = url or DEFAULT_DATABASE_URL
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def upsert_territories(database_url: str, rows: list[dict]) -> int:
    """Write published territories into the existing `territories` table.

    PHASE B CONTRACT -- implement this without changing the signature.

    Each row carries exactly the Milestone 1 columns:
        id (uuid), version (int), slug, name, city, area, kind, geom (WKT, 4326)

    Requirements:

    - Upsert on `id`, not on `slug`. Identity is permanent; the slug is not.
    - Bump `version` only when the geometry hash differs from what is stored.
      Republishing an unchanged territory must be a no-op, so that a re-run
      does not churn versions and invalidate nothing.
    - Insert geometry with `ST_GeomFromText(:geom, 4326)` cast to
      `geography(MULTIPOLYGON)`, matching `backend/app/models.py`. Promote
      single polygons with `ST_Multi`.
    - Run inside one transaction. A partially published AOI is a broken game
      map, so it is all or nothing.
    - Do not delete territories that vanished from the new run. Report them in
      the publish manifest and let a human decide -- an ownership row pointing
      at a deleted territory is data loss.

    Returns the number of rows written.
    """
    raise NotImplementedError(
        "Phase B: implement the territories upsert. See this docstring for the contract."
    )
