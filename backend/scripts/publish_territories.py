"""Safely apply a reviewed gameplay territory publish to PostGIS.

This is an operator control, not a development seed shortcut. It accepts only a
Stage 13 gameplay publish pair, produces a dry-run plan by default, and refuses
to remove territories or change their stable identity. An apply requires a
reason and an exact published-hash confirmation and records both a JSON audit
artifact and an ``audit_events`` row.

Examples:
    uv run python scripts/publish_territories.py
    uv run python scripts/publish_territories.py --apply \
      --actor operator@example.com --reason "Reviewed release R42" \
      --confirm-publish <published_hash>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import MultiPolygon, mapping, shape
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import SessionLocal  # noqa: E402
from app.models import AuditEvent, Territory  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TERRITORY_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class PublishControlError(ValueError):
    """The publish does not meet the operator safety contract."""


@dataclass(frozen=True)
class PublishedTerritory:
    id: uuid.UUID
    slug: str
    name: str
    kind: str
    geometry: dict[str, Any]
    geometry_hash: str


@dataclass(frozen=True)
class ReviewedPublish:
    city: str
    area: str
    published_hash: str
    manifest_path: Path
    geojson_path: Path
    territories: tuple[PublishedTerritory, ...]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _artifact_hash(collection: dict[str, Any]) -> str:
    """Match the pipeline hash, excluding only mutable provenance."""
    return _content_hash({key: value for key, value in collection.items() if key != "pipeline"})


def _normalized_multipolygon(geometry: dict[str, Any]) -> dict[str, Any]:
    """Normalize Polygon/MultiPolygon serialization for semantic geometry comparison."""
    parsed = shape(geometry)
    if parsed.geom_type == "Polygon":
        parsed = MultiPolygon([parsed])
    return mapping(parsed)


def _geometry_hash(geometry: dict[str, Any]) -> str:
    return _content_hash(_normalized_multipolygon(geometry))


def _expected_ids(city: str, area: str, slug: str) -> set[uuid.UUID]:
    """Gameplay merges have a gameplay ID; protected passthroughs keep parcel IDs."""
    return {
        uuid.uuid5(TERRITORY_NAMESPACE, f"{city}/{area}/gameplay/{slug}"),
        uuid.uuid5(TERRITORY_NAMESPACE, f"{city}/{area}/{slug}"),
    }


def load_reviewed_publish(geojson_path: Path, manifest_path: Path) -> ReviewedPublish:
    """Load and verify an immutable Stage 13 published pair."""
    if not geojson_path.is_file() or not manifest_path.is_file():
        raise PublishControlError("both published GeoJSON and manifest files are required")

    try:
        collection = json.loads(geojson_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PublishControlError(f"invalid JSON: {exc}") from exc

    if collection.get("type") != "FeatureCollection":
        raise PublishControlError("published GeoJSON must be a FeatureCollection")
    pipeline = collection.get("pipeline")
    if not isinstance(pipeline, dict) or pipeline.get("stage") != "publish_gameplay":
        raise PublishControlError("only a reviewed Stage 13 gameplay publish is accepted")
    if manifest.get("layer") != "gameplay" or manifest.get("validation_status") != "pass":
        raise PublishControlError("manifest must be a passing gameplay publish manifest")

    city, area = manifest.get("city"), manifest.get("area")
    if not isinstance(city, str) or not city or not isinstance(area, str) or not area:
        raise PublishControlError("manifest must declare a non-empty city and area")
    actual_hash = _artifact_hash(collection)
    if manifest.get("published_hash") != actual_hash:
        raise PublishControlError("manifest published_hash does not match the GeoJSON")

    features = collection.get("features")
    if not isinstance(features, list) or not features:
        raise PublishControlError("published GeoJSON must contain at least one territory")
    if manifest.get("territory_count") != len(features):
        raise PublishControlError("manifest territory_count does not match the GeoJSON")

    territories: list[PublishedTerritory] = []
    seen_ids: set[uuid.UUID] = set()
    seen_slugs: set[str] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise PublishControlError(f"feature[{index}] is not a GeoJSON Feature")
        props = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            raise PublishControlError(f"feature[{index}] needs properties and geometry")
        try:
            territory_id = uuid.UUID(str(props["territory_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise PublishControlError(f"feature[{index}] has an invalid territory_id") from exc
        slug, name, kind = props.get("slug"), props.get("name"), props.get("kind")
        if not all(isinstance(value, str) and value for value in (slug, name, kind)):
            raise PublishControlError(f"feature[{index}] needs non-empty slug, name, and kind")
        if not SLUG_RE.fullmatch(slug):
            raise PublishControlError(f"feature[{index}] has an unstable slug {slug!r}")
        if territory_id not in _expected_ids(city, area, slug):
            raise PublishControlError(
                f"feature[{index}] territory_id is not the stable ID for {city}/{area}/{slug}"
            )
        if territory_id in seen_ids or slug in seen_slugs:
            raise PublishControlError(f"feature[{index}] duplicates territory identity")
        try:
            parsed_geometry = shape(geometry)
        except Exception as exc:
            raise PublishControlError(f"feature[{index}] has invalid geometry") from exc
        if parsed_geometry.geom_type not in {"Polygon", "MultiPolygon"} or parsed_geometry.is_empty:
            raise PublishControlError(
                f"feature[{index}] must be a non-empty Polygon or MultiPolygon"
            )
        if not parsed_geometry.is_valid:
            raise PublishControlError(f"feature[{index}] has invalid polygon topology")
        # The database contract is MultiPolygon. Normalize only the in-memory
        # representation; the reviewed published artifact stays untouched.
        geometry = _normalized_multipolygon(geometry)

        seen_ids.add(territory_id)
        seen_slugs.add(slug)
        territories.append(
            PublishedTerritory(
                id=territory_id,
                slug=slug,
                name=name,
                kind=kind,
                geometry=geometry,
                geometry_hash=_geometry_hash(geometry),
            )
        )

    return ReviewedPublish(
        city=city,
        area=area,
        published_hash=actual_hash,
        manifest_path=manifest_path,
        geojson_path=geojson_path,
        territories=tuple(territories),
    )


def build_impact_summary(
    publish: ReviewedPublish, existing: Iterable[tuple[Territory, str | None]]
) -> dict[str, Any]:
    """Build a non-destructive plan and enforce stable ID/version transitions."""
    rows = list(existing)
    in_area = {
        row.id: (row, geometry_json)
        for row, geometry_json in rows
        if row.city == publish.city and row.area == publish.area
    }
    all_by_id = {row.id: row for row, _ in rows}
    by_slug_version = {(row.slug, row.version): row for row, _ in rows}
    incoming_ids = {territory.id for territory in publish.territories}
    removed = sorted(str(territory_id) for territory_id in set(in_area) - incoming_ids)
    if removed:
        raise PublishControlError(
            "refusing to remove existing territories; publish a successor set through a "
            f"retirement workflow first ({len(removed)} absent)"
        )

    additions = updates = unchanged = 0
    versions: dict[str, int] = {}
    for territory in publish.territories:
        current = all_by_id.get(territory.id)
        if current is None:
            additions += 1
            versions[str(territory.id)] = 1
        else:
            if (
                current.city != publish.city
                or current.area != publish.area
                or current.slug != territory.slug
            ):
                raise PublishControlError(
                    f"{territory.slug}: stable territory ID is already bound to "
                    f"{current.city}/{current.area}/{current.slug}"
                )
            if current.version < 1:
                raise PublishControlError(f"{territory.slug}: stored version must be positive")
            geometry_json = in_area[territory.id][1]
            current_hash = _geometry_hash(json.loads(geometry_json)) if geometry_json else None
            if current_hash == territory.geometry_hash:
                unchanged += 1
                versions[str(territory.id)] = current.version
            else:
                updates += 1
                versions[str(territory.id)] = current.version + 1
        conflicting = by_slug_version.get((territory.slug, versions[str(territory.id)]))
        if conflicting is not None and conflicting.id != territory.id:
            raise PublishControlError(
                f"{territory.slug}: version {versions[str(territory.id)]} is already "
                "bound to a different territory ID"
            )

    return {
        "city": publish.city,
        "area": publish.area,
        "published_hash": publish.published_hash,
        "territory_count": len(publish.territories),
        "additions": additions,
        "geometry_updates": updates,
        "unchanged": unchanged,
        "retirements": 0,
        "versions": versions,
    }


def _write_audit_artifact(audit_dir: Path, payload: dict[str, Any]) -> Path:
    audit_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = audit_dir / f"territory-publish-{stamp}-{payload['mode']}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _to_wkt(geometry: dict[str, Any]) -> str:
    """Minimal GeoJSON MultiPolygon to WKT; avoids an extra database conversion."""
    polygons = []
    for polygon in geometry["coordinates"]:
        rings = [
            "(" + ", ".join(f"{lon} {lat}" for lon, lat, *_ in ring) + ")"
            for ring in polygon
        ]
        polygons.append("(" + ", ".join(rings) + ")")
    return "MULTIPOLYGON(" + ", ".join(polygons) + ")"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--geojson",
        type=Path,
        default=ROOT
        / "data/pipeline/bengaluru/jayanagar_lalbagh/published/gameplay_territories.geojson",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT
        / "data/pipeline/bengaluru/jayanagar_lalbagh/published/gameplay_publish_manifest.json",
    )
    parser.add_argument(
        "--audit-dir", type=Path, default=ROOT / "data/operator-audit/territory-publishes"
    )
    parser.add_argument(
        "--apply", action="store_true", help="apply the reviewed publish after planning"
    )
    parser.add_argument("--actor", help="operator reference recorded in the audit event")
    parser.add_argument("--reason", help="change reason recorded in the audit event")
    parser.add_argument(
        "--confirm-publish", help="must equal the manifest published_hash when applying"
    )
    args = parser.parse_args(argv)

    try:
        publish = load_reviewed_publish(args.geojson, args.manifest)
        with SessionLocal() as session:
            rows = session.execute(select(Territory, Territory.geom.ST_AsGeoJSON())).all()
            summary = build_impact_summary(publish, rows)

            mode = "apply" if args.apply else "dry-run"
            audit = {"at": datetime.now(UTC).isoformat(), "mode": mode, "summary": summary}
            if not args.apply:
                audit_path = _write_audit_artifact(args.audit_dir, audit)
                print(
                    json.dumps(
                        {**summary, "audit_artifact": str(audit_path)},
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
            if not args.actor or not args.reason:
                raise PublishControlError("--apply requires --actor and --reason")
            if args.confirm_publish != publish.published_hash:
                raise PublishControlError(
                    "--confirm-publish must exactly match manifest published_hash"
                )

            existing = {row.id: row for row, _ in rows}
            for territory in publish.territories:
                row = existing.get(territory.id)
                version = summary["versions"][str(territory.id)]
                geom = f"SRID=4326;{_to_wkt(territory.geometry)}"
                if row is None:
                    session.add(
                        Territory(
                            id=territory.id,
                            version=version,
                            slug=territory.slug,
                            name=territory.name,
                            city=publish.city,
                            area=publish.area,
                            kind=territory.kind,
                            geom=geom,
                        )
                    )
                elif version != row.version:
                    row.version = version
                    row.name = territory.name
                    row.kind = territory.kind
                    row.geom = geom
                else:
                    row.name, row.kind = territory.name, territory.kind
            session.add(
                AuditEvent(
                    actor_kind="operator",
                    actor_ref=args.actor,
                    action="territory.publish",
                    target_type="territory_dataset",
                    target_ref=f"{publish.city}/{publish.area}",
                    after_state=summary,
                    reason=args.reason,
                    details={
                        "manifest": str(publish.manifest_path),
                        "geojson": str(publish.geojson_path),
                    },
                )
            )
            session.commit()
            audit_path = _write_audit_artifact(args.audit_dir, audit)
            print(
                json.dumps(
                    {**summary, "audit_artifact": str(audit_path)}, indent=2, sort_keys=True
                )
            )
            return 0
    except PublishControlError as exc:
        print(f"Publish refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
