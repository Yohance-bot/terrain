# Backend — Milestone 1

Territories, run ingestion, route matching, and the placeholder ownership rule.

Ownership here is raw cumulative distance and nothing else. The influence model in
`docs/01_CORE_MECHANICS` is deliberately not implemented, not even partially.

## Setup

PostgreSQL with PostGIS, running locally:

```bash
brew install postgis postgresql@17
brew services start postgresql@17
createdb run_prototype
psql -d run_prototype -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

Then, from this directory:

```bash
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run python scripts/seed_territories.py
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` matters: the phone reaches the backend over the LAN, and the app
resolves the host from the Metro bundler address.

## Reviewed territory publishing

`seed_territories.py` remains a development-only convenience script. It may
replace a local area set and must not be used as an operator release tool.

Apply reviewed Stage 13 gameplay output through the guarded publisher instead.
It validates the paired published GeoJSON/manifest and stable UUID semantics,
prints and records a dry-run by default, and refuses removals. Applying requires
an explicit hash confirmation, operator reference, and change reason:

```bash
uv run python scripts/publish_territories.py
uv run python scripts/publish_territories.py --apply \
  --actor operator@example.com --reason "Reviewed release R42" \
  --confirm-publish <published_hash>
```

Audit JSON is written under `data/operator-audit/territory-publishes/` and an
`audit_events` row is added only on a successful apply. There is intentionally
no admin UI or retirement workflow in this milestone.

## Tests

```bash
uv run pytest
```

These run against the real database, because the things worth testing here are
PostGIS behaviours — that distance comes back in metres rather than degrees, that
minimum presence excludes a run that only clips a corner, and that ownership
changes hands when a rival covers more ground.

## Layout

```
app/
  api/v1/          Routers. Thin; no logic.
  core/            Config and database session.
  models.py        Six tables. No influence model.
  schemas.py       Request and response shapes.
  services/
    ingest.py      Accept a run, derive everything, apply the result.
    matching.py    Route to territory clipping. Simplified for this milestone.
    ownership.py   THE PLACEHOLDER RULE. Isolated on purpose.
migrations/        Alembic.
scripts/           Seeding.
```

## The one rule worth protecting

`app/services/ownership.py` is the only file that knows how a territory's owner is
decided. Nothing else may contain that assumption. When the real model replaces
the placeholder, that file is rewritten and nothing else moves.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/territories` | Boundaries as GeoJSON, with attribution |
| `GET` | `/v1/territories/state` | Current owner per territory |
| `POST` | `/v1/runs` | Submit a finished run; idempotent on `run_id` |
| `GET` | `/v1/runs/{id}` | Result for the post-run reveal |

Every request carries an `X-Device-Id` header. That is not authentication and does
not pretend to be — accounts are out of scope for this milestone.

## Notes for whoever picks this up next

Matching runs synchronously inside `POST /v1/runs`. Clipping one route against ten
polygons takes milliseconds, so a queue would be premature. The service boundary is
drawn so moving it to a worker later is a call-site change.

There is no H3 index. With ten territories an exact geometry clip is instant.
`03_MAP_AND_TERRITORY_PIPELINE` commits to H3 as the lookup layer for the real
system; this milestone implements only the exact-geometry path, which is the same
path the production design falls back to for ambiguous boundary cases.

Raw traces are kept in `runs.raw_payload` in full. They are the dataset for
designing the real route-matching algorithm, which `03` leaves open. Do not prune
them.
