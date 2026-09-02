# run

A location-based fitness game prototype. The real world is divided into
territories — real parks, lakes and named neighbourhood blocks, never arbitrary
grids — and running through them can change who owns them.

**Current milestone: 1 — Map and Territory Foundation.** See
[`docs/08_PROTOTYPE_M1_MAP_FOUNDATION.md`](docs/08_PROTOTYPE_M1_MAP_FOUNDATION.md)
for scope, decisions and build order, and `docs/00` through `docs/07` for the
design that milestone applies.

Ownership in this milestone is **raw cumulative distance and nothing else**. The
influence model in `docs/01_CORE_MECHANICS` is deliberately not implemented.

## Requirements

Expo Go cannot run this app — MapLibre is a native module, so a custom
development client is required.

## Running it

**Backend** (see [`backend/README.md`](backend/README.md) for detail):

```bash
brew install postgis postgresql@17 && brew services start postgresql@17
createdb run_prototype && psql -d run_prototype -c "CREATE EXTENSION postgis;"

cd backend
cp .env.example .env && uv sync
uv run alembic upgrade head
uv run python scripts/seed_territories.py
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Mobile:**

```bash
npm install
npx expo run:android    # or: npx expo run:ios
```

The app finds the backend at the Metro host on port 8000 during local
development. A physical device or Release build that leaves the home network
must use a public HTTPS API URL. The value is embedded when the app is bundled,
so set it before creating/installing the iOS build:

```bash
cp .env.example .env.local
# Replace the value with the HTTPS address printed by the tunnel command below.
```

For an outside-the-house test, keep the backend running and expose it through a
temporary Cloudflare Tunnel in a second terminal:

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```

Copy the resulting `https://…trycloudflare.com` URL into
`EXPO_PUBLIC_API_URL` in `.env.local`, then build/install the Release app. The
app stores an unreachable run locally and retries submission when it returns to
the foreground and every 30 seconds while open. Do not place secrets in an
`EXPO_PUBLIC_` variable.

## Scripts

| Script | Description |
| --- | --- |
| `npm start` | Start the Expo dev server |
| `npm run android` / `npm run ios` | Build and launch the dev client |
| `npm run lint` | ESLint |
| `npm run typecheck` | TypeScript |

## Structure

```
app/                    Expo Router routes only. Thin; no logic.
  index.tsx             Map, run controls
  run/[id].tsx          Post-run reveal
src/
  features/
    map/                MapLibre rendering. Draws geometry, decides nothing.
    recorder/           Foreground GPS session
  services/
    api/                Backend client
    territories/        Territory loading and device-side cache
  lib/
    db/                 SQLite, for run durability
    device/             Anonymous device id (not an account)
  theme/  types/  utils/  constants/
backend/                FastAPI + PostGIS. See backend/README.md.
data/territories/       Hand-picked, verified GeoJSON. Committed on purpose.
tools/territory-import/ One-off OSM extraction. Run by hand, never by the app.
tools/pipeline/         Milestone 2 territory generation. Build-time only, and
                        the eventual replacement for territory-import.
docs/                   Design and milestone documents.
```

`@/*` resolves to `src/*`.

## Things that look optional and are not

**OpenStreetMap attribution.** ODbL requires it visible at all times, no
exceptions. It is rendered in `src/features/map/TerritoryMap.tsx` and returned by
the territories endpoint.

**`backend/app/services/ownership.py`.** The only file that knows how a
territory's owner is decided. The rule in it is a placeholder that will be
deleted; the isolation is the point.

**Raw GPS traces in `runs.raw_payload`.** These are the dataset for designing the
real route-matching algorithm, which `docs/03` leaves as an open problem. Do not
prune them.
