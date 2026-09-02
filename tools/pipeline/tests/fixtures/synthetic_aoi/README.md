# Synthetic AOI fixture

Empty on purpose. Phase B adds the files described here.

The golden tests in `../../test_topology.py` need an input small enough to
reason about by hand. Running them against a real Bengaluru extract would be
slow, would change whenever OSM changes, and would make a failure impossible to
diagnose -- you would be debugging the algorithm and the data at once.

## What to build

A tiny fake district, hand-written, in `EPSG:4326`, somewhere inside the
Jayanagar–Lalbagh bbox so the working CRS is the real one.

### `separators.geojson`

A 4×4 grid of lines forming nine closed cells. Enough to exercise
polygonization without being tedious to check by eye.

Include, deliberately:

- One line ending just short of a junction, within `snap_m`. Stage 04 must snap
  it; if it does not, two cells merge and the test catches it.
- One dangling line that closes no face. Stage 04 must drop it.
- One `highway=footway` line crossing a cell. Stage 02 must exclude it, so it
  must never appear as a border.

### `landmarks.geojson`

One protected polygon that:

- Spans parts of **two** grid cells, so stage 05's carve is genuinely exercised
  rather than trivially satisfied by an already-aligned shape.
- Is larger than `fabric_soft_max_m2`, so stage 06 has an opportunity to split
  it and must not take it.

### `expected/`

Committed golden output for the stages that have deterministic results:
`05_faces.geojson`, `06_normalized.geojson`, `07_named.geojson`. Regenerate
these only when a rule intentionally changes, and say which rule in the commit
message.

## Rules

- Keep coordinates round and few. Someone will have to verify these numbers by
  hand at some point.
- No real OSM data. The moment this fixture depends on the outside world, the
  determinism test stops testing the pipeline.
- Sizes must straddle the thresholds in `config/thresholds.yaml`: at least one
  cell below `scrap_m2`, at least one inside the soft band, at least one above
  `fabric_review_max_m2`.
