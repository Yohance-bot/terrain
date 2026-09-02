# Territory generation pipeline

Build-time tooling that turns OpenStreetMap and Overture data into the
territories the game is played on. Run by a person, never by the app.

Design contract: [`docs/09_TERRITORY_GENERATION_PIPELINE.md`](../../docs/09_TERRITORY_GENERATION_PIPELINE.md).

## Current state

Stages **01–13** are implemented:

**Reality engine (parcels)**

- **01** pinned Overture + Geofabrik downloads, checksums, manifest
- **02** separator extraction into `intermediate/02_separators.geojson`
- **03** named landmarks: eligible parks/lakes/stadiums/campuses are atomic;
  only landmarks at least 50 acres are protected
- **04** noded/snapped boundary graph in working CRS into `04_boundary_graph.geojson`
- **05** polygonize + carve every atomic landmark whole into `05_faces.geojson`
- **06** scrap merge + oversized fabric flags into `06_normalized.geojson`
- **07** names, slugs, and stable `territory_id` into `07_named.geojson`
- **08** fail-closed validation → `staging/candidates.geojson` + `validation_report.json`
- **09** parcel publish → `published/territories.geojson` + `publish_manifest.json`
  (exact copy of candidates; gated on `staging/APPROVED`)

**Gameplay abstraction**

- **10** barrier-aware agglomerative clustering → `staging/gameplay_candidates.geojson`
  + `gameplay_cluster_report.json` + `gameplay_validation_report.json`
- **11** beautification critic + GIS apply → `staging/gameplay_beautified.geojson`
  + metrics / suggestions / apply report (auto-applies high-confidence merges only)
- **12** gameplay review gate → `staging/gameplay_review.json`
  (gated on `staging/GAMEPLAY_APPROVED`; reviews beautified output)
- **13** gameplay publish → `published/gameplay_territories.geojson`
  + `gameplay_publish_manifest.json` (phone / seed source)

`staging/` holds human review checkpoints. Parcel `APPROVED` and
`GAMEPLAY_APPROVED` are independent. Hard validation failures write the report
only and raise; candidates are withheld.

Stages 02–03 need the `osmium` CLI on PATH to clip the Geofabrik extract
(`brew install osmium-tool`).

## Running it

```bash
uv sync

uv run python run_pipeline.py --list
uv run python run_pipeline.py --region bengaluru_jayanagar_lalbagh
uv run python run_pipeline.py --region bengaluru_jayanagar_lalbagh --from-stage 10 --to-stage 13
uv run python run_pipeline.py --region bengaluru_jayanagar_lalbagh --dry-run

uv run pytest
uv run ruff check .
```

A full run stops at stage 09 with `blocked` until a human creates
`staging/APPROVED`, then clusters + beautifies at stages 10–11 and stops at
stage 12 until `staging/GAMEPLAY_APPROVED` exists. Those waits are the expected
resting states, not failures.

### Gameplay area and landmark contract

- Ordinary territories have a hard publish floor of **250 acres**
  (`1,011,714.1056 m²`), target **300 acres** (`1,214,056.92672 m²`), and may
  absorb leftovers up to the hard **500-acre** ceiling
  (`2,023,428.2112 m²`).
- Non-legendary territories (ordinary only) must have at most **10 exterior
  corners** after Stage 11 (vertices on a legendary perimeter are exempt from
  the count; legendary coordinates stay frozen). Mosaic-safe peels that cannot
  hit 10 without opening gaps soft-flag leftovers for review (temporary).
- **Legendary** = source-protected landmark already ≥50 acres that never annexes
  outside land (e.g. Lalbagh). Exempt from the corner budget; geometry stays
  byte-stable.
- **Ordinary** = everything else (fabric + absorbed sub-50-acre atomics).
- Every named eligible landmark is atomic. Landmarks at or above **50 acres**
  stay source-protected (legendary). Smaller ones are **absorbed whole** into
  adjacent ordinary fabric (never expanded into a prize class).
- Stage 10/11 must absorb ordinary dust, road strips, and near-enclave islands
  so every ordinary border touches a neighbour. Stage 11 never invents vertices
  (corner budget prefers shared-edge deletion + whole-merge; free-arc peels must
  repair the mosaic or are rejected).
- Phone seed: `published/gameplay_territories.geojson`.

## Layout

```
config/
  regions/*.yaml       one file per area of interest; the only place geography is named
  highway_classes.yaml which real-world features may become territory borders
  thresholds.yaml      sizing, validation, gameplay.*, and beautify.* numbers
lib/
  config.py            typed loaders that fail loud on a missing key
  contracts.py         ArtifactSpec, PipelineContext, Stage, StageResult
  artifacts.py         every file the pipeline reads or writes, declared once
  cluster.py           Stage 10 barrier-aware agglomerative clustering
  beautify_metrics.py  Stage 11 design metrics
  beautify_critic.py   Stage 11 heuristic critic (LLM stub)
  beautify_apply.py    Stage 11 GIS apply toolbox
  crs.py               projection and metre-accurate measurement
  determinism.py       stable ids, canonical JSON, content hashing
  io.py                canonical reads and writes
  publish.py           Stage 09 parcel publish
  publish_gameplay.py  Stage 13 gameplay publish
  postgis.py           publish-time database access
  registry.py          loads stages/0N_*.py by path
stages/
  01_download_data.py .. 13_publish_gameplay.py
run_pipeline.py        orchestrator
tests/
```

Output goes to `data/pipeline/{city}/{area}/` at the repo root: `raw/`,
`intermediate/`, `staging/`, `published/`. Raw extracts and intermediates are
gitignored; staging and published output is the audit trail and is committed.

## Implementing a stage

Read `docs/09_TERRITORY_GENERATION_PIPELINE.md`, then the docstring of the stage
file. It states the inputs, the outputs, the invariants and the non-goals.

Replace the body of `run()` below the `PHASE B` comment. Do not change:

- `NUMBER`, `NAME`, `REQUIRES`, `PRODUCES`
- the orchestrator, `lib/contracts.py`, or `lib/artifacts.py`
- any config **key** (values are yours to tune)
- anything under `backend/` or `src/`

The contract tests exist to catch exactly those changes.

Three rules that are easy to break and expensive to discover:

1. **Measure in metres.** Use `lib.crs.to_work` before any area or length
   calculation. Shapely's `.area` on EPSG:4326 coordinates returns square
   degrees, which will be compared against a threshold in square metres and
   silently produce a wrong map.
2. **Sort before writing.** Most GIS operations return geometry in an
   unspecified order. Use `lib.determinism.stable_sort`, or a re-run produces a
   different file from identical inputs.
3. **Never hash geometry into an identifier.** `lib.determinism.territory_id`
   takes city, area and slug only. Its docstring explains why.

## Directory and stage numbering

Stage files start with digits so `ls stages/` shows the pipeline order. That is
not an importable module name, so `lib/registry.py` loads them by path. This is
contained entirely in that one file.
