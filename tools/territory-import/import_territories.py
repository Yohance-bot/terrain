#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.32", "shapely>=2.0", "osm2geojson>=0.2.5"]
# ///
"""One-off territory extraction for Milestone 1. Run by a human, never by the app.

This is NOT the generation pipeline from `03_MAP_AND_TERRITORY_PIPELINE`. That is
whole-city infrastructure and is deliberately not built yet. This script pulls a
handful of hand-picked boundaries once, so they can be committed as static files
and spot-checked before use.

`03` prohibits depending on the public Overpass API for production traffic. This
is a development-time extraction run by hand, which that prohibition does not
cover -- the application itself never makes a network call to Overpass.

Usage:
    ./import_territories.py            # extract and write GeoJSON
    ./import_territories.py --check    # report what exists without writing

Afterwards, open every file in geojson.io or QGIS and compare against satellite
imagery. Anything wrong gets deleted or hand-corrected. That manual check is the
point of the milestone doing this by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import osm2geojson
import requests
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

# Tried in order. The main instance is frequently rate-limited or overloaded and
# returns 504; the mirrors usually answer. Overpass also rejects requests with a
# default library user agent, hence USER_AGENT below.
OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
USER_AGENT = "run-prototype-territory-import/0.1 (one-off milestone 1 extraction)"

# Fixed namespace so territory ids are stable across re-runs. `03` requires
# territory identity to be immutable; deriving it from the slug guarantees that
# re-extracting a boundary does not mint a new territory.
NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

ROOT = Path(__file__).resolve().parents[2]
PICKS = Path(__file__).parent / "picks.json"


def build_query(bbox: list[float], selectors: list[str]) -> str:
    """Bounding box rather than an administrative area lookup.

    Resolving `area["name"="Bengaluru"]` forces Overpass to load the whole city
    boundary before it can filter, which routinely times out on the public
    instances. A bbox around the test area returns in seconds and is strictly
    better here, since every pick is inside Jayanagar by definition.
    """
    box = ",".join(str(v) for v in bbox)
    body = "\n  ".join(f"{selector}({box});" for selector in selectors)
    return f"""
[out:json][timeout:90];
(
  {body}
);
out geom;
""".strip()


def fetch(query: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(2):
        for url in OVERPASS_MIRRORS:
            try:
                response = requests.post(
                    url,
                    data={"data": query},
                    timeout=180,
                    headers={"User-Agent": USER_AGENT},
                )
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001 -- try the next mirror
                last_error = exc
                time.sleep(2 + 3 * attempt)
    raise RuntimeError(f"all Overpass mirrors failed: {last_error}")


def to_multipolygon(overpass_json: dict):
    """Collapse whatever Overpass returned into a single MultiPolygon.

    osm2geojson handles the fiddly part -- assembling OSM relations with inner and
    outer ways into valid polygons. Anything that is not an area (a stray node or
    open way) is discarded.
    """
    collection = osm2geojson.json2geojson(overpass_json)
    polygons = []
    for feature in collection.get("features", []):
        geometry = feature.get("geometry")
        if not geometry or geometry["type"] not in ("Polygon", "MultiPolygon"):
            continue
        candidate = shape(geometry)
        if candidate.is_valid and not candidate.is_empty:
            polygons.append(candidate)

    if not polygons:
        return None

    merged = unary_union(polygons)
    if merged.geom_type == "Polygon":
        from shapely.geometry import MultiPolygon

        merged = MultiPolygon([merged])
    return merged


def write_manifest(out_dir: Path, city: str, area: str, version: int) -> int:
    """Rebuild the manifest from the GeoJSON actually on disk.

    Derived rather than accumulated in memory, so a partial extraction still
    produces a manifest that matches reality and a re-run picks up where it left
    off. Existing 'verified' flags are preserved -- a human set those.
    """
    manifest_path = out_dir / "manifest.json"
    previous = {}
    if manifest_path.exists():
        for entry in json.loads(manifest_path.read_text()).get("territories", []):
            previous[entry["slug"]] = entry.get("verified", False)

    territories = []
    for path in sorted(out_dir.glob("*.geojson")):
        feature = json.loads(path.read_text())
        props = feature["properties"]
        geometry = shape(feature["geometry"])
        territories.append(
            {
                "id": props["territory_id"],
                "slug": props["slug"],
                "name": props["name"],
                "kind": props["kind"],
                "version": props["version"],
                "city": city,
                "area": area,
                "approx_km2": round(geometry.area * (111_320**2) / 1_000_000, 4),
                "verified": previous.get(props["slug"], False),
            }
        )

    manifest_path.write_text(
        json.dumps(
            {
                "city": city,
                "area": area,
                "version": version,
                "attribution": "© OpenStreetMap contributors",
                "license": "ODbL",
                "territories": territories,
            },
            indent=2,
        )
        + "\n"
    )
    return len(territories)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Report only; write nothing")
    parser.add_argument("--force", action="store_true", help="Re-fetch picks already on disk")
    parser.add_argument("--only", nargs="*", help="Fetch only these slugs")
    args = parser.parse_args()

    config = json.loads(PICKS.read_text())
    city, area, version = config["city"], config["area"], config["version"]
    out_dir = ROOT / "data" / "territories" / city / area / f"v{version}"

    if not args.check:
        out_dir.mkdir(parents=True, exist_ok=True)

    failures = []

    for pick in config["picks"]:
        slug = pick["slug"]
        if args.only and slug not in args.only:
            continue

        target = out_dir / f"{slug}.geojson"
        # Overpass is unreliable enough that a full run frequently fails partway.
        # Already-extracted picks are left alone so a re-run only retries the gaps.
        if target.exists() and not args.force:
            print(f"  {slug:<24}have it")
            continue

        print(f"  {slug:<24}", end="", flush=True)
        try:
            geometry = to_multipolygon(fetch(build_query(config["bbox"], pick["osm"])))
        except Exception as exc:  # noqa: BLE001 -- one-off tool, report and continue
            print(f"ERROR  {exc}")
            failures.append(slug)
            time.sleep(2)
            continue

        if geometry is None:
            print("NO GEOMETRY  (verify the name in OSM, or draw it by hand)")
            failures.append(slug)
            time.sleep(2)
            continue

        # Rough area in square metres, for sanity-checking against expectations.
        approx_km2 = geometry.area * (111_320**2) / 1_000_000
        print(f"ok   ~{approx_km2:.3f} km²")

        territory_id = str(uuid.uuid5(NAMESPACE, f"{city}/{area}/{slug}"))

        if not args.check:
            feature = {
                "type": "Feature",
                "id": territory_id,
                "properties": {
                    "territory_id": territory_id,
                    "slug": slug,
                    "name": pick["name"],
                    "kind": pick["kind"],
                    "version": version,
                },
                "geometry": mapping(geometry),
            }
            (out_dir / f"{slug}.geojson").write_text(json.dumps(feature))

        time.sleep(2)  # Overpass is a free shared service. Be polite.

    if not args.check:
        count = write_manifest(out_dir, city, area, version)
        print(f"\nManifest lists {count} territories in {out_dir.relative_to(ROOT)}")

    if failures:
        print(f"\nNeeds attention: {', '.join(failures)}")
    print("\nEvery boundary must be visually verified before seeding. Set")
    print("'verified': true in manifest.json once you have checked it.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
