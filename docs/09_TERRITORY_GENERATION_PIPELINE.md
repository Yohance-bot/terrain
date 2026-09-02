# 09 — Territory Generation Pipeline (Milestone 2)

Milestone 1 proved the loop works: a map loads, a run is recorded, the server
matches it against territories, ownership changes. It also proved the thing we
already suspected. The hand-drawn Lalbagh territory read as a real place. The
hand-drawn Jayanagar blocks read as boxes.

That difference is the entire product. `00_PROJECT_VISION` says the map is not
the product and the feeling of changing the map is the product — and nobody
feels anything about capturing a box. Milestone 2 replaces hand-drawing with a
pipeline that produces territories corresponding to real places, exhaustively,
deterministically, and with a human signing off before anything goes live.

This document is the **contract** for that pipeline. It describes what each
stage takes in, what it puts out, and what must be true of the result. It is
deliberately not a GIS tutorial.

---

## Scope

**In:** the Jayanagar → Lalbagh corridor of Bengaluru, defined by a bbox in
`tools/pipeline/config/regions/bengaluru_jayanagar_lalbagh.yaml`. Extending to
another district is a new config file, not new code.

**Out:** gameplay, ownership, influence, anti-cheat, H3 indexing, AI-assisted
naming, the `corridor` territory kind, the admin console, PMTiles, and any
city-wide run. The output of this pipeline is static game data. Nothing about
how that data is played with changes here.

---

## Decisions taken relative to the earlier documents

These are scoped deviations from `03`, `06` and `07`, made on purpose.

| Topic | Earlier documents | Milestone 2 |
| --- | --- | --- |
| Sizing | No fixed area; ~1–2 territories per normal run | Meaningful geography first. Soft fabric band 20k–80k m², scraps under 5k m² merged. Landmarks and named places stay whole at any size |
| Naming | LLM assists naming and importance | No AI. Source attributes first, deterministic street-pair fallback, then a review flag |
| H3 | Rebuild `territory_cells` on publish | Deferred. Publish writes territories and GeoJSON only |
| Review UI | Admin console on the critical path (`06`) | File-based review. A person opens the candidates GeoJSON and creates an `APPROVED` file |
| Gameplay parameters | `influence_capacity`, decay rates per territory | Not computed. The Milestone 1 schema is preserved exactly |
| `kind` | `area` \| `corridor` | Milestone 1 kinds only; `corridor` deferred |
| Determinism | Published artifact is frozen | Stronger: identical source inputs must produce identical output |

The area key is `jayanagar_lalbagh`, deliberately different from Milestone 1's
`jayanagar`. The hand-made data stays in place, so rolling back a bad publish is
a config change and a re-seed rather than an archaeology exercise.

---

## Architecture

```mermaid
flowchart TD
  sources[Overture and Geofabrik] --> download[01 download_data]
  download --> extract[02 extract_features]
  download --> landmarks[03 extract_landmarks]
  extract --> graph[04 build_boundary_graph]
  landmarks --> candidates[05 polygonize_and_carve]
  graph --> candidates
  candidates --> normalize[06 normalize_sizes]
  normalize --> names[07 assign_names]
  names --> validate[08 validate]
  validate --> staging[staging/candidates.geojson]
  staging --> human[Human review -> APPROVED]
  human --> publish[09 publish parcels]
  publish --> parcels[published/territories.geojson]
  parcels --> cluster[10 cluster_gameplay]
  extract --> cluster
  cluster --> gameplayStaging[staging/gameplay_candidates.geojson]
  gameplayStaging --> beautify[11 beautify_gameplay]
  beautify --> beautified[staging/gameplay_beautified.geojson]
  beautified --> gameplayHuman[Human review -> GAMEPLAY_APPROVED]
  gameplayHuman --> publishGameplay[13 publish_gameplay]
  publishGameplay --> phone[Phone / seed]
```

Principles this rests on:

- **Build time only.** The running application never contacts Overture,
  Geofabrik or Overpass. A human runs this pipeline and commits the result.
- **Overture primary, Geofabrik fallback**, as decided in `03`.
- **GIS produces polygons, not language models.** A boundary has to correspond
  to something real; an invented one is unfalsifiable. Stage 11 may *criticize*
  design and suggest restricted merge ops; GIS still executes geometry.
- **Two layers.** Stages 01–09 publish **parcels** (reality). Stages 10–13
  abstract them into **gameplay** territories without inventing geometry.
- **Humans publish.** Automation prepares candidates; a person decides —
  separately for parcels (`APPROVED`) and gameplay (`GAMEPLAY_APPROVED`).
- **Exhaustive tiling.** Every point in the AOI belongs to exactly one
  territory. Gaps and overlaps are both gameplay bugs.
- **Metres, never degrees.** All measurement happens in UTM 43N or on the
  ellipsoid. A threshold compared against a degree-based area is meaningless.

---

## Stage contracts

Full detail lives in each stage's module docstring under
`tools/pipeline/stages/`. This table is the index.

| Stage | Requires | Produces | Must be true of the result |
| --- | --- | --- | --- |
| 01 `download_data` | region config | `raw/download_manifest.json` + extracts | Sources pinned; checksums recorded; unchanged files not re-downloaded |
| 02 `extract_features` | raw manifest | `intermediate/02_separators.geojson` | Only classes from `highway_classes.yaml`; exclusion beats inclusion; clipped past the bbox edge |
| 03 `extract_landmarks` | raw manifest | `intermediate/03_landmarks.geojson` | Every named eligible park/lake/stadium/campus is atomic; only ≥50-acre landmarks are protected; multi-part places dissolved into one |
| 04 `build_boundary_graph` | separators | `intermediate/04_boundary_graph.geojson` | Fully noded, snapped within `snap_m`, in the working CRS, dangles dropped |
| 05 `polygonize_and_carve` | graph + landmarks | `intermediate/05_faces.geojson` | Exhaustive cover, no overlaps; carve every atomic landmark and reinsert it whole |
| 06 `normalize_sizes` | faces | `intermediate/06_normalized.geojson` | Scraps merged along longest shared border; protected majors untouched; total area preserved |
| 07 `assign_names` | normalized | `intermediate/07_named.geojson` | Names from source data only; stable `territory_id`; fallbacks carry `needs_review` |
| 08 `validate` | named | `staging/candidates.geojson` + `validation_report.json` | Fails closed on any topology defect; report written either way |
| 09 `publish` | candidates + report, gated on `APPROVED` | `published/territories.geojson` + `publish_manifest.json` | Exact copy of parcel candidates; immutable reality layer |
| 10 `cluster_gameplay` | published parcels + separators | `staging/gameplay_candidates.geojson` + cluster/validation reports | Barrier-aware merges only; protected frozen; no invented geometry |
| 11 `beautify_gameplay` | gameplay candidates + separators | metrics, suggestions, apply report, `staging/gameplay_beautified.geojson` | Critic suggests restricted ops; GIS auto-applies ≥ confidence; no freeform vertices |
| 12 `gameplay_review` | beautified + apply report, gated on `GAMEPLAY_APPROVED` | `staging/gameplay_review.json` | Human sign-off for the playable layer |
| 13 `publish_gameplay` | beautified + review | `published/gameplay_territories.geojson` + manifest | Exact copy; phone / `seed_territories.py` source |

### Sizing

Ordinary gameplay territories must be at least **250 acres**
(`1,011,714.1056 m²`), target **300 acres** (`1,214,056.92672 m²`), and must
not exceed **500 acres** (`2,023,428.2112 m²`). The 50-acre floor
(`standalone_min_area_m2`) marks source-protected **legendary** landmarks only.
There is no territory-count target. An ordinary Stage 09 parcel already over
500 acres is an upstream separator defect and Stage 10 fails closed instead of
inventing a boundary.

Stage 06 never absorbs atomic landmarks as anonymous scraps. Stage 10
**absorbs** every non-protected atomic landmark whole into the best surrounding
ordinary fabric (preferring undersized neighbours). There is no expansion into a
prize / special class. Ordinary fabric then agglomerates toward the 250–300 acre
band. Undersized scraps, road strips, and near-enclave islands are force-absorbed
into neighbours so every ordinary border touches another territory. Every merge
respects hard barriers when possible and the 500-acre ceiling.

Stage 11 prioritises below-floor and strip merges, then parcel transfers. No
freeform vertex edits.

Landmarks use two gameplay classes:

- **legendary** (`protected`) — source-standalone ≥50 acres; never annexes;
  byte-stable perimeter; exempt from the 10-corner budget
- **ordinary** — fabric plus absorbed sub-50-acre atomics; ≥250 acres;
  ≤10 exterior corners; ≤500-acre hard max

Stage 11 finishes with a mosaic-safe corner budget: delete near-collinear shared
vertices (with 2-owner area conservation), merge leftovers that remain over
budget, and batch free-arc peels that must restore gap/overlap or are rejected.
Vertices that lie on a **legendary** perimeter are exempt from the count (and
never edited). Hitting ≤10 on every ordinary ring without opening the mosaic is
not always possible yet — leftovers soft-flag for review rather than hard-fail
publish (temporary).

### Naming priority

1. Place or neighbourhood name from Overture divisions or OSM `place=*`
2. Park, lake or landmark name for protected features
3. Street-pair fallback: *"Between 30th Main and Kanakapura Road"*
4. Unnamed, plus `needs_review`

Anything reaching step 3 or 4 is flagged. A street-pair name is a readable
placeholder, not a real name, and `validation.allow_unnamed_publish` is false so
an unnamed territory cannot reach players.

### Identity and versioning

A **parcel** territory's id is `uuid5(namespace, "city/area/slug")` and depends
on nothing else — not geometry, not version, not display name.

A **gameplay** territory's id is `uuid5(namespace, "city/area/gameplay/{slug}")`
except protected landmarks, which keep their parcel `territory_id` so Lalbagh
(and peers) stay continuous across layers. Merged fabric carries
`member_territory_ids` (sorted parcel ids) for audit and future ownership
migration.

Geometry hashes exist to *detect* a change, which is what bumps the `version`
column. Identity is permanent; the version moves. The reasoning is spelled out
in `tools/pipeline/lib/determinism.py`.

---

## Review checklist

Stage 08 writes `staging/candidates.geojson` and stops. Before creating the
`APPROVED` file, open the candidates in QGIS or geojson.io against satellite
imagery and check:

- [ ] Lalbagh is one territory, not several, and its boundary follows the wall
- [ ] Every lake in the AOI is whole
- [ ] No border runs down a footpath, a park path, or a quiet residential lane
      a person would happily run along
- [ ] Named territories carry names a local would use
- [ ] Every `needs_review` entry has been looked at individually
- [ ] Nothing is a shape you would have to explain to a player
- [ ] `validation_report.json` shows coverage at or above the configured ratio,
      with zero gaps and zero overlaps

Before `GAMEPLAY_APPROVED`, also verify:

- [ ] No ordinary territory is below 250 acres or above 500 acres; 250–300 acre
      territories should read as coherent neighbourhoods
- [ ] No ordinary territory has more than 10 exterior corners
- [ ] Legendary territories (Lalbagh-class) keep their exact source perimeter
- [ ] No ordinary territory is a long strip (aspect > 3:1) without a recorded
      merge/transfer attempt in the beautify apply report
- [ ] No ordinary territory sits inside another (near-enclave / island); borders
      form a touching mosaic. `ordinary_enclave` is soft-reported temporarily —
      gap/overlap/coverage stay hard.
- [ ] Ordinary exterior-corner budget (≤10) is best-effort / soft-review until
      mosaic-safe peels can hard-fail closed without opening gaps
- [ ] Sub-50-acre named landmarks are absorbed whole into one surrounding
      ordinary fabric territory (no special / expanded prize class)
- [ ] Every ≥50-acre protected landmark keeps its exact source perimeter and id
- [ ] `gameplay_cluster_report.json` absorptions and
      `gameplay_validation_report.json` hard checks match the map

Then, and only then:

```bash
touch data/pipeline/bengaluru/jayanagar_lalbagh/staging/APPROVED
uv run python run_pipeline.py --region bengaluru_jayanagar_lalbagh --from-stage 9
```

`APPROVED` is a file rather than a `--yes` flag on purpose. A flag becomes the
default; a file that has to be created by hand does not.

Everything before stage 09 is reversible by re-running a stage. Publishing is
not: once players run in these territories, ownership history attaches to them.

---

## Phase B implements the algorithm bodies

The pipeline ships as a complete skeleton: real configs, real orchestrator, real
determinism and CRS helpers, real contract enforcement, and nine stage stubs
that write placeholder artifacts so the chain runs end to end.

An implementer replaces the body of one `run()` at a time. They do not change
`NUMBER`, `NAME`, `REQUIRES` or `PRODUCES`, the orchestrator, the config keys,
or anything under `backend/` or `src/`. The contract tests in
`tools/pipeline/tests/` fail loudly if they do.

`tools/pipeline/README.md` has the operational detail.

---

## Acceptance

Milestone 2 is done when:

- [ ] The AOI is fully partitioned, with no gaps and no overlaps
- [ ] Landmarks are intact and fabric is normalised under the soft rules
- [ ] Ids, versions and names are stable across re-runs
- [ ] A second run over the same source extracts produces an identical hash
- [ ] The published set serves through the existing API with no mobile change
- [ ] No H3, no AI, no ownership or influence changes
