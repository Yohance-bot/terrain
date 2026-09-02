"""Load territories into PostGIS for the mobile API.

Two sources (pick via env / auto-detect):

1. Milestone 1 hand set:
   `data/territories/{city}/{area}/v1/manifest.json` + per-slug GeoJSON

2. Milestone 2 pipeline publish (prefer gameplay layer):
   `data/pipeline/{city}/{area}/published/gameplay_territories.geojson`
   falls back to `published/territories.geojson` (Stage 09 parcels) if
   Stage 13 has not been published yet.

    uv run python scripts/seed_territories.py
    uv run python scripts/seed_territories.py --source pipeline

Idempotent on territory id. Historic territories referenced by recorded runs
are never deleted: a conflicting legacy slug is retained at revision 0 while
the newly published territory takes the current revision.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.models import Territory  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("auto", "hand", "pipeline"),
        default="auto",
        help="hand = M1 GeoJSON set; pipeline = Stage 13 gameplay (or Stage 09 parcels)",
    )
    args = parser.parse_args(argv)

    source = args.source
    if source == "auto":
        if _pipeline_path().exists():
            source = "pipeline"
        elif _hand_manifest_path().exists():
            source = "hand"
        else:
            print(
                f"No territory data for {settings.territory_city}/{settings.territory_area}.\n"
                f"  looked for {_pipeline_gameplay_path()}\n"
                f"  looked for {_pipeline_parcels_path()}\n"
                f"  looked for {_hand_manifest_path()}"
            )
            return 1

    if source == "pipeline":
        return _seed_pipeline()
    return _seed_hand()


def _pipeline_gameplay_path() -> Path:
    return (
        ROOT
        / "data"
        / "pipeline"
        / settings.territory_city
        / settings.territory_area
        / "published"
        / "gameplay_territories.geojson"
    )


def _pipeline_parcels_path() -> Path:
    return (
        ROOT
        / "data"
        / "pipeline"
        / settings.territory_city
        / settings.territory_area
        / "published"
        / "territories.geojson"
    )


def _pipeline_path() -> Path:
    """Prefer Stage 12 gameplay; fall back to Stage 09 parcels."""
    gameplay = _pipeline_gameplay_path()
    if gameplay.exists():
        return gameplay
    return _pipeline_parcels_path()


def _hand_manifest_path() -> Path:
    return (
        ROOT
        / "data"
        / "territories"
        / settings.territory_city
        / settings.territory_area
        / "v1"
        / "manifest.json"
    )


def _seed_pipeline() -> int:
    path = _pipeline_path()
    if not path.exists():
        print(
            f"No pipeline publish at {_pipeline_gameplay_path()} "
            f"or {_pipeline_parcels_path()}. Run Stage 12 (or Stage 09) first."
        )
        return 1

    layer = "gameplay" if path.name == "gameplay_territories.geojson" else "parcels"
    print(f"Seeding from {path} ({layer})")

    collection = json.loads(path.read_text(encoding="utf-8"))
    features = list(collection.get("features") or [])
    if not features:
        print(f"{path} has no features.")
        return 1

    city = settings.territory_city
    area = settings.territory_area
    version = 1

    rows: list[dict] = []
    for feature in features:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry")
        if not geometry:
            continue
        if geometry["type"] == "Polygon":
            geometry = {"type": "MultiPolygon", "coordinates": [geometry["coordinates"]]}
        if geometry["type"] != "MultiPolygon":
            print(f"  skip {props.get('slug')!r}: unsupported type {geometry['type']}")
            continue

        tid = props.get("territory_id")
        slug = props.get("slug")
        name = props.get("name")
        kind = props.get("kind") or "block"
        if not tid or not slug or not name:
            print(f"  skip incomplete feature slug={slug!r}")
            continue

        rows.append(
            {
                "id": uuid.UUID(str(tid)),
                "version": version,
                "slug": str(slug),
                "name": str(name),
                "city": city,
                "area": area,
                "kind": str(kind),
                "geom": f"SRID=4326;{_to_wkt(geometry)}",
            }
        )

    print(
        f"Seeding pipeline publish: {len(rows)} territories "
        f"({city}/{area}) from {path.relative_to(ROOT)}"
    )

    session = SessionLocal()
    added = updated = 0
    try:
        # (slug, version) is globally unique. A prior smaller map can share a
        # slug with this larger publish while being referenced by historical
        # run segments. Do not delete that evidence; archive its revision so
        # the published territory can use the current (1) revision.
        slugs = {r["slug"] for r in rows}
        published_ids = {row["id"] for row in rows}
        legacy_conflicts = session.execute(
            select(Territory).where(
                Territory.slug.in_(slugs),
                Territory.version == version,
                Territory.id.not_in(published_ids),
            )
        ).scalars().all()
        for territory in legacy_conflicts:
            territory.version = 0
        if legacy_conflicts:
            print(f"  retained {len(legacy_conflicts)} historic slug conflict(s) at revision 0")

        for row in rows:
            existing = session.get(Territory, row["id"])
            if existing is None:
                session.add(Territory(**row))
                added += 1
            else:
                existing.version = row["version"]
                existing.slug = row["slug"]
                existing.name = row["name"]
                existing.city = row["city"]
                existing.area = row["area"]
                existing.kind = row["kind"]
                existing.geom = row["geom"]
                updated += 1

        session.commit()
    finally:
        session.close()

    with SessionLocal() as check:
        total = len(
            check.execute(
                select(Territory.id).where(Territory.city == city, Territory.area == area)
            ).all()
        )
    print(f"\n{added} added, {updated} updated. {total} territories for {city}/{area}.")
    return 0


def _seed_hand() -> int:
    data_dir = (
        ROOT / "data" / "territories" / settings.territory_city / settings.territory_area / "v1"
    )
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}. Run tools/territory-import first.")
        return 1

    manifest = json.loads(manifest_path.read_text())
    entries = manifest["territories"]

    unverified = [t["slug"] for t in entries if not t.get("verified")]
    if unverified:
        print("WARNING: these boundaries are not marked verified in manifest.json:")
        for slug in unverified:
            print(f"  - {slug}")
        print("Check each one against satellite imagery before trusting any result.\n")

    session = SessionLocal()
    added = updated = 0
    try:
        for entry in entries:
            path = data_dir / f"{entry['slug']}.geojson"
            if not path.exists():
                print(f"  skip {entry['slug']:<24} (no geojson file)")
                continue

            feature = json.loads(path.read_text())
            geometry = feature["geometry"]
            if geometry["type"] == "Polygon":
                geometry = {"type": "MultiPolygon", "coordinates": [geometry["coordinates"]]}

            territory_id = uuid.UUID(entry["id"])
            existing = session.get(Territory, territory_id)
            geom_value = f"SRID=4326;{_to_wkt(geometry)}"

            if existing is None:
                session.add(
                    Territory(
                        id=territory_id,
                        version=entry["version"],
                        slug=entry["slug"],
                        name=entry["name"],
                        city=entry["city"],
                        area=entry["area"],
                        kind=entry["kind"],
                        geom=geom_value,
                    )
                )
                added += 1
                print(f"  add  {entry['slug']:<24} {entry['name']}")
            else:
                existing.name = entry["name"]
                existing.kind = entry["kind"]
                existing.version = entry["version"]
                existing.geom = geom_value
                updated += 1
                print(f"  upd  {entry['slug']:<24} {entry['name']}")

        session.commit()
    finally:
        session.close()

    with SessionLocal() as check:
        total = len(check.execute(select(Territory.id)).all())
    print(f"\n{added} added, {updated} updated. {total} territories in the database.")
    return 0


def _to_wkt(geometry: dict) -> str:
    """Minimal GeoJSON MultiPolygon to WKT. Avoids pulling shapely into the API."""
    polygons = []
    for polygon in geometry["coordinates"]:
        rings = [
            "(" + ", ".join(f"{lon} {lat}" for lon, lat, *_ in ring) + ")" for ring in polygon
        ]
        polygons.append("(" + ", ".join(rings) + ")")
    return "MULTIPOLYGON(" + ", ".join(polygons) + ")"


if __name__ == "__main__":
    raise SystemExit(main())
