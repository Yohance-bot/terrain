"""Stage 01 -- fetch and checksum the source extracts.

CONTRACT
========

Requires: nothing on disk. The region config is the input.
Produces: `raw/download_manifest.json`, plus the extract files beside it.

What this stage does
--------------------
Downloads the pinned Overture theme parquet for the AOI bbox, and the Geofabrik
OSM extract that covers Karnataka, into the region's `raw/` directory. Writes a
`.sha256` next to each file and records everything in the manifest.

Invariants Phase B must hold
----------------------------
- Call `ctx.region.require_pinned_sources()` first. An unpinned Overture release
  makes the run's output depend on the day it happened, which breaks the one
  guarantee the whole milestone rests on.
- Skip a download whose existing file already matches its recorded checksum,
  unless `ctx.force`. These extracts are hundreds of megabytes; re-running
  stage 03 should not mean re-downloading Karnataka.
- Verify after downloading, not before. A truncated file that is never checked
  produces a plausible-looking territory set built from half a city.
- Record the resolved Overture release string in the manifest even though it
  also lives in config. The manifest is the audit record; it has to stand alone.
- Nothing is filtered here. Selection is stage 02's job, and keeping the raw
  extracts untouched is what allows the filter rules to be changed and re-run
  without another download.

Non-goals
---------
No parsing, no clipping, no reprojection, no tag filtering.

Notes for the author
--------------------
Overture is the primary source per `03_MAP_AND_TERRITORY_PIPELINE`; Geofabrik is
the fallback for anything Overture covers poorly in Bengaluru. Download both --
which one wins per feature class is decided in stages 02 and 03, and having only
one on disk turns that into a download instead of a re-run.

The runtime application never talks to any of these services. This is
build-time infrastructure, executed by a human.
"""

from __future__ import annotations

from lib import artifacts
from lib import download as download_lib
from lib.contracts import PipelineContext, StageResult, StageStatus
from lib.io import write_json

NUMBER = 1
NAME = "download_data"

REQUIRES: tuple = ()
PRODUCES = (artifacts.RAW_MANIFEST,)


def run(ctx: PipelineContext) -> StageResult:
    ctx.ensure_dirs()
    # Refuse to proceed on a floating release. Determinism dies the day the
    # "latest" Overture file silently changes under us.
    ctx.region.require_pinned_sources()
    release = ctx.region.overture.release
    assert release is not None  # narrowed by require_pinned_sources

    west, south, east, north = ctx.region.bbox.as_xy_bounds()
    bbox_wsen = (west, south, east, north)

    files = []
    written = []

    for theme, feature_type in download_lib.types_for_themes(ctx.region.overture.themes):
        dest = ctx.raw_dir / f"overture_{theme}_{feature_type}.geoparquet"
        # Call through the module so tests can monkeypatch lib.download without
        # caring how the stage bound the name at import time.
        record = download_lib.download_overture_type(
            feature_type=feature_type,
            release=release,
            bbox_wsen=bbox_wsen,
            dest=dest,
            force=ctx.force,
        )
        files.append(_manifest_entry(record))
        written.append(record.path)

    geofabrik_url = ctx.region.geofabrik.extract_url
    geofabrik_name = geofabrik_url.rstrip("/").split("/")[-1]
    geofabrik_dest = ctx.raw_dir / geofabrik_name
    geofabrik = download_lib.download_http_file(
        key="geofabrik_extract",
        source="geofabrik",
        url=geofabrik_url,
        dest=geofabrik_dest,
        force=ctx.force,
    )
    files.append(_manifest_entry(geofabrik))
    written.append(geofabrik.path)

    # Sort so two runs with the same downloads produce byte-identical manifests.
    files = sorted(files, key=lambda entry: entry["key"])

    manifest = {
        "stage": NAME,
        "status": "ok",
        "city": ctx.region.city,
        "area": ctx.region.area,
        "bbox": {
            "south": ctx.region.bbox.south,
            "west": ctx.region.bbox.west,
            "north": ctx.region.bbox.north,
            "east": ctx.region.bbox.east,
        },
        "crs_work": ctx.region.crs_work,
        "crs_store": ctx.region.crs_store,
        "overture_release": release,
        "files": files,
    }
    manifest_path = write_json(artifacts.RAW_MANIFEST.path(ctx), manifest)
    written.append(manifest_path)

    skipped = sum(1 for entry in files if entry["skipped"])
    fetched = len(files) - skipped
    message = (
        f"overture release {release}; bbox WSES={bbox_wsen}; "
        f"{fetched} downloaded, {skipped} reused from checksum"
    )
    return StageResult(stage=NAME, status=StageStatus.OK, written=written, message=message)


def _manifest_entry(record) -> dict:
    entry = {
        "key": record.key,
        "source": record.source,
        "url": record.url,
        "filename": record.filename,
        "sha256": record.sha256,
        "bytes": record.bytes,
        "skipped": record.skipped,
    }
    if record.release is not None:
        entry["release"] = record.release
    if record.theme is not None:
        entry["theme"] = record.theme
    if record.feature_type is not None:
        entry["feature_type"] = record.feature_type
    return entry
