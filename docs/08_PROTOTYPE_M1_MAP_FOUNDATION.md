# 08 — Prototype Milestone 1: Map and Territory Foundation

**Status:** Implementation Plan v1

**Scope:** The first working prototype. Map renders, hand-picked territories display, a foreground run is recorded, the route is matched against territories after the run, and ownership changes under a deliberately temporary placeholder rule.

**Not a design document.** Design is settled in `00` through `07`. This document decides structure, stack and build order for one milestone, applying those decisions rather than revisiting them.

---

## Conflicts Flagged Before Proceeding

Raised rather than silently resolved, per instruction.

**1. `03_MAP_PIPELINE_DUE_DILIGENCE` does not exist.** It is named as authoritative material and is referenced three times inside `03_MAP_AND_TERRITORY_PIPELINE`, but there is no such file in `/docs`. Provider comparison, cost projections and the full licensing rationale are therefore only partially recorded — the ODbL attribution requirement and the OpenFreeMap-to-PMTiles migration trigger survive in `03`, but the reasoning behind vendor choice does not exist in writing anywhere. Nothing in this milestone depends on it. It should be written before the tile-hosting migration is actually executed.
"Acknowledged. 03_MAP_PIPELINE_DUE_DILIGENCE is missing from the repo. For this milestone, continue applying the decisions already present in 03_MAP_AND_TERRITORY_PIPELINE


**2. The stack of record is not in `/docs`.** Python, FastAPI, PostgreSQL with PostGIS and h3-pg, Redis, Arq, AWS ap-south-1, FCM, phone OTP — these are decided, but they live in the TerraRun Statement of Work, which `07_ROADMAP_AND_LAUNCH` references without recording. `03` only names FastAPI and PostGIS, incidentally, inside a pipeline diagram. This milestone applies the SOW stack as given. Recommend the stack table be written into `03` or its own document so "already decided" is verifiable from the repository alone.
"Acknowledged. Apply the SOW stack as the source of truth for now. A future documentation pass will consolidate the stack decisions into the repo docs.

**3. Anti-cheat is out of scope, but `05_ANTICHEAT_AND_TRUST` Principle 2 calls sensor capture "the only genuinely irreversible decision" and requires it from the first run.** These do not actually conflict, because prototype data is throwaway and will not seed production standings. But the resolution is deliberate and worth stating: **this milestone captures the per-sample evidence fields anyway** — horizontal accuracy, provider, mock-provider flag, reported speed — because doing so costs almost nothing, exercises the schema shape that production needs, and means the traces recorded in Jayanagar are usable later. No detection logic is built. Capture only.
"Agreed. Capture evidence fields only. No anti-cheat logic should be implemented in this milestone."

**4. Server-side matching is not optional.** `05` Principle 1 states the client asserts nothing and the server derives every fact that matters; `03` Runtime Responsibilities states the mobile application should never implement gameplay rules that belong on the server. A device-only prototype with on-phone matching would be faster to build and would directly contradict both. This milestone therefore includes a backend, kept deliberately small. Flagging because "prototype" would normally argue for the opposite choice.
Agreed. Keep route matching server-side. Prototype backend remains minimal but authoritative.

**5. Chapter reference drift.** The milestone brief cites `01_CORE_MECHANICS` Chapters 9 and 11 for the post-run reveal and the no-live-feedback rule. In `01` v2 those are Chapters 10 and 12 — Chapter 9 is Seasons and Chapter 11 is Checkpoints. The substance is unaffected; the rule being applied is the correct one.
Acknowledged. Correct the references. No design change required.

**One deliberate deviation, not a conflict.** `03` requires hysteresis and segment-level assignment for route matching. This milestone implements minimum-presence filtering and exact geometry clipping only, with no hysteresis. That is a subset of the committed design, not a contradiction — and the open problem in `03` explicitly says the real algorithm should be settled against real traces from the launch area. **The traces recorded during this milestone are that dataset.** Every raw payload is retained for that purpose.
Approved. Use the simplified matching algorithm for Milestone 1. Raw traces should be retained for future route-matching evaluation.

---

## Tech Stack

Applied from prior decisions. Nothing here is newly chosen except where noted.

| Layer | Choice | Source of decision |
| --- | --- | --- |
| Mobile | React Native, Expo SDK 54, Expo Router, TypeScript | Existing repository; `04_APPLICATION_ARCHITECTURE` |
| Map renderer | MapLibre via `@maplibre/maplibre-react-native` | `03` — MapLibre is committed |
| Tiles | OpenFreeMap | `03` — OpenFreeMap in development, PMTiles in production |
| Location | `expo-location`, foreground watch only | Milestone scope |
| Device storage | `expo-sqlite` | New, minimal — durable run persistence |
| Backend | Python 3.12, FastAPI | SOW; `03` pipeline diagram |
| Database | PostgreSQL 16 + PostGIS | `03` |
| Local orchestration | Docker Compose | New, development only |

**Not used in this milestone, deliberately:** h3-pg, Redis, Arq, any cloud deployment, any state management library, any data-fetching library. Ten territories do not need an index, four endpoints do not need a query cache, and synchronous matching of a 3,000-point route against ten polygons completes in milliseconds.

**Practical constraint.** MapLibre React Native is a native module, so Expo Go cannot run this app. A custom development client is required from day one. Compatibility of the MapLibre binding with React Native 0.81 and the new architecture is listed as unverified in `04` and is the first thing this milestone proves.

---

## Repository Structure

Single repository. The Expo application stays at the repository root because that is where Expo Router expects it and the existing app already works there.

```
/
├── app/                        Expo Router routes — thin, no logic
│   ├── _layout.tsx
│   ├── index.tsx               Map screen
│   └── run/
│       └── [id].tsx            Post-run summary
│
├── src/                        Mobile source, aliased @/*
│   ├── features/
│   │   ├── map/                MapLibre view, territory layers, location marker
│   │   ├── recorder/           Foreground GPS session, sample buffer
│   │   └── run-summary/        Post-run reveal
│   ├── services/
│   │   ├── api/                Backend client
│   │   └── territories/        Bundled GeoJSON loader and cache
│   ├── lib/
│   │   ├── db/                 SQLite schema and access
│   │   └── device/             Anonymous device identity
│   ├── store/                  Recorder session state
│   ├── theme/
│   └── types/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/v1/             Routers
│   │   ├── core/               Config, database session
│   │   ├── models/             SQLAlchemy
│   │   ├── schemas/            Pydantic
│   │   └── services/
│   │       ├── matching.py     Route → per-territory segments
│   │       └── ownership.py    PLACEHOLDER RULE — isolated on purpose
│   ├── migrations/             Alembic
│   ├── tests/
│   └── pyproject.toml
│
├── data/
│   └── territories/
│       └── bengaluru/jayanagar/v1/
│           ├── manifest.json
│           └── *.geojson       Hand-picked, spot-checked, committed
│
├── tools/
│   └── territory-import/       One-off OSM extraction script
│
├── docs/
└── docker-compose.yml          Postgres + PostGIS for local development
```

**On the asymmetry** of mobile at root and backend in a subdirectory: it is not elegant, and moving to `apps/mobile` and `apps/api` costs an afternoon of Expo configuration. The right moment to pay that is when the admin console from `06_ADMIN_AND_OPERATIONS` arrives and there are three applications rather than two. Not now.

---

## The Isolation Rule

**`backend/app/services/ownership.py` is the only file in the codebase that knows how ownership is decided.**

For this milestone it contains one function whose entire logic is: the owner of a territory is the device with the highest `total_distance_m`. No decay, no diminishing returns, no shares, no Legacy, no momentum.

When the real model from `01_CORE_MECHANICS` replaces it, that file is rewritten and nothing else moves. No other module — not matching, not the API layer, not the mobile app — may contain any assumption about how a winner is determined.

This is the single most important structural decision in the milestone, because the placeholder is guaranteed to be thrown away.

---

## Database Schema

Six tables. No influence column exists anywhere.

```sql
territories
  id                 uuid primary key      -- immutable, never reused
  version            int not null          -- per 03 territory versioning
  slug               text unique
  name               text
  city               text
  kind               text                  -- park | lake | block | landmark
  geom               geography(Polygon, 4326)
  created_at         timestamptz

devices                                     -- stands in for users; NOT an account
  id                 uuid primary key      -- generated on device
  label              text                  -- optional, for tester identification
  created_at         timestamptz

runs
  id                 uuid primary key      -- client-generated, idempotency key
  device_id          uuid references devices
  started_at         timestamptz
  ended_at           timestamptz
  duration_s         int
  distance_m         numeric               -- server-computed, never client-asserted
  geom               geography(LineString, 4326)
  sample_ts          bigint[]              -- epoch ms, parallel to geom vertices
  sample_accuracy_m  real[]                -- parallel to geom vertices
  raw_payload        jsonb                 -- retained; object storage later
  status             text                  -- 'submitted' | 'applied'
  pipeline_version   int
  created_at         timestamptz

run_territory_segments                      -- APPEND-ONLY. The ledger, in embryo.
  id                 bigserial primary key
  run_id             uuid references runs
  device_id          uuid references devices
  territory_id       uuid references territories
  territory_version  int
  distance_m         numeric
  seconds_in         int
  created_at         timestamptz

territory_standings                         -- DERIVED, fully rebuildable from segments
  territory_id       uuid
  device_id          uuid
  total_distance_m   numeric
  updated_at         timestamptz
  primary key (territory_id, device_id)

territory_ownership
  territory_id       uuid primary key
  owner_device_id    uuid null
  since              timestamptz
  previous_owner_id  uuid null
```

Four decisions inside this schema are carried from committed architecture because they are free now and expensive later:

**Territory identity is immutable and versioned**, per `03`. Even with ten hand-picked polygons.

**Segments are append-only and standings are derived.** `05` Principle 4 requires an append-only ledger with rebuildable standings. Storing a running total instead would be marginally simpler and would establish exactly the habit the production system cannot tolerate.

**The route is one row, not one row per point.** A LineString plus parallel arrays for timestamps and accuracy. Per-point rows are called out as a mistake in the architecture review and would be a mistake here too, at any scale.

**Runs carry `status` and `pipeline_version` from the first migration**, per `05` requirement 1. Only two states are used now.

**Device identity is not an account.** A UUID generated on first launch and stored on the device, sent as a request header. It exists solely so that two testers can contest the same territory. It has no authentication, no recovery and no privacy surface, and it is replaced wholesale when accounts arrive.

---

## API

Four endpoints. Versioned path from the start.

```
GET  /v1/territories?city=bengaluru&area=jayanagar
     → GeoJSON FeatureCollection + dataset version

GET  /v1/territories/state
     → current owner per territory, for map fills

POST /v1/runs
     → accepts client-generated run id; idempotent on retry
     → server computes distance, matches territories, updates standings and ownership
     → returns run id and result

GET  /v1/runs/{id}
     → per-territory segments and any ownership changes, for the summary screen
```

Matching runs synchronously inside the POST for this milestone. `03` and `07` both put it in a worker eventually; the service module boundary is drawn so that moving it later is a call-site change, not a rewrite.

---

## Territory Data Pipeline

Manual and one-off. The generation pipeline in `03` is explicitly not built here.

**Selection.** Five to ten real, meaningful, physically runnable locations in and around Jayanagar. Candidates to verify against OSM before use — a park, a lake, and several recognised named blocks:

- Lalbagh Botanical Garden
- Jayanagar 4th Block
- Jayanagar 9th Block
- Madhavan Park
- Krishna Rao Park
- Ragigudda
- Sarakki Lake
- Puttenahalli Lake
- South End Circle surrounds

These are candidates, not decisions. Each must be checked in OSM for whether usable geometry exists, whether the boundary is approximately correct, and whether the name is the one locals actually use — the same check `03` calls the Bengaluru data-quality validation, applied to ten features instead of a city.

**Extraction.** A one-off script in `tools/territory-import/`, run by hand, never by the application. Either a single Overpass query or a Geofabrik extract processed with osmium. Note that `03`'s prohibition on Overpass is specifically about production runtime traffic — a one-time development-time extraction does not violate it.

**Output.** Static GeoJSON committed to `data/territories/bengaluru/jayanagar/v1/`, with a manifest carrying id, version, name and kind per feature. Spot-checked visually against satellite imagery before use.

**Consumption.** Seeded into PostGIS by a script for matching, and bundled into the application for offline rendering, per the offline map strategy in `04`.

**Attribution is not optional.** `03` requires "© OpenStreetMap contributors" visible in the interface at all times, with no exceptions. It appears in the prototype, and it is in the acceptance criteria below.

---

## Build Order

**M1.0 — Platform spikes. Both before anything else.**
Two questions that change everything if the answer is no, and both are cheap to ask. First: does MapLibre React Native render OpenFreeMap tiles in a custom development client on a real device, on Expo SDK 54 with the new architecture? Second: does `expo-location` foreground watching produce a usable roughly-1 Hz track on a real Android device with the screen on? Same reasoning as the GPS reality test in `07` — discovering a platform incompatibility in week four is far more expensive than discovering it in week one.

**M1.1 — Territory data.** Select, verify, extract, spot-check, commit. Independent of all code and the long pole for correctness, so it starts immediately and runs in parallel.

**M1.2 — Backend skeleton.** Docker Compose with Postgres and PostGIS, Alembic migrations for the six tables, seed script, `GET /v1/territories` returning real polygons.

**M1.3 — Map screen.** Tiles, territory fills from bundled GeoJSON, ownership colouring from `/v1/territories/state`, foreground location marker, ODbL attribution. **First moment the thing looks like a product.**

**M1.4 — Recorder.** Start and stop, foreground sampling with the evidence fields captured, samples written to SQLite continuously rather than held in memory, session survives app backgrounding without losing what was already recorded.

**M1.5 — Submission and matching.** `POST /v1/runs` with idempotency, route clipping against territory geometry in PostGIS, minimum-presence filtering, segment writes, standings recompute, ownership recompute through the isolated module.

**M1.6 — Post-run summary.** Which territories the run touched, distance inside each, whether ownership changed. No live feedback during the run, per `01` — this screen is the only place territory information appears.

**M1.7 — Stability.** Ten consecutive cycles of open, run, stop, review without a crash. Fix what that surfaces.

---

## Deliberately Postponed

**Not built:** H3 indexing, background location, accounts and authentication, the influence model in any partial form, anti-cheat detection, the territory generation pipeline, Redis and background workers, self-hosted PMTiles, cloud deployment, the admin console, clubs, offline upload queue beyond simple retry, multi-city support.

**Built now because retrofitting is expensive:** territory identity and versioning, the append-only segment ledger with derived standings, server-authoritative matching, run status and pipeline version columns, per-sample evidence capture, ODbL attribution, and the ownership isolation boundary.

The distinction between those two lists is the whole point of the milestone. Everything in the first list is additive. Everything in the second is structural, and adding it later means a migration, a reprocessing, or a habit that has to be unlearned across the codebase.

---

## Acceptance Criteria

- [ ] The app opens and displays a map centred on Jayanagar.
- [ ] Five to ten hand-picked territory boundaries render correctly and match reality when compared against satellite imagery.
- [ ] The user's current location appears while the app is in the foreground.
- [ ] A run can be started, recorded as a GPS route, and stopped.
- [ ] The recorded route is matched against territories after the run ends, on the server.
- [ ] Cumulative distance per territory per device is stored and updated.
- [ ] Ownership is determined solely by highest cumulative distance, computed in one isolated module.
- [ ] A post-run screen shows which territories were affected and whether ownership changed.
- [ ] No territory information appears at any point during a run.
- [ ] OpenStreetMap attribution is visible in the interface.
- [ ] Ten consecutive open-run-stop-review cycles complete without a crash.
- [ ] Every raw trace recorded during the milestone is retained, for use in designing the real route-matching algorithm.

---

## What This Milestone Produces Beyond A Working Prototype

Real GPS traces from real runs in a real Bengaluru neighbourhood, recorded against known territory boundaries.

`03` names the exact route-matching algorithm as an open problem and states it should be settled against real traces from the launch area before the influence engine is built. This milestone generates that dataset as a by-product. It is arguably the more valuable output.
