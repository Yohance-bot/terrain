"""Stage 07 naming priority and identity rules."""

from __future__ import annotations

from shapely.geometry import LineString, box, mapping

from lib import artifacts
from lib.contracts import StageStatus
from lib.crs import to_store
from lib.determinism import territory_id
from lib.io import artifact_hash_input, is_placeholder, read_json, write_geojson
from lib.naming import _NamedPlace, _NamedRoad
from lib.registry import discover_stages


def _stage07():
    return next(s for s in discover_stages() if s.number == 7)


def _write_normalized(ctx, features: list[dict]) -> None:
    write_geojson(
        artifacts.NORMALIZED.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "normalize_sizes", "feature_count": len(features)},
    )


def _centre_work(ctx):
    from shapely.geometry import box as shapely_box

    from lib.crs import to_work

    aoi = to_work(shapely_box(*ctx.region.bbox.as_xy_bounds()), ctx.region.crs_work)
    minx, miny, maxx, maxy = aoi.bounds
    return (minx + maxx) / 2.0, (miny + maxy) / 2.0


def test_protected_landmark_keeps_name_and_stable_id(ctx, monkeypatch):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    park = box(cx, cy, cx + 500, cy + 500)
    features = [
        {
            "type": "Feature",
            "geometry": mapping(to_store(park, crs)),
            "properties": {
                "face_id": "face-00001",
                "protected": True,
                "role": "major",
                "name": "Lalbagh Botanical Garden",
                "slug": "lalbagh-botanical-garden",
                "kind": "park",
                "area_m2": float(park.area),
            },
        }
    ]
    _write_normalized(ctx, features)
    monkeypatch.setattr("lib.naming.load_places", lambda _ctx: [])
    monkeypatch.setattr("lib.naming.load_named_roads", lambda _ctx: [])

    result = _stage07().run(ctx)
    assert result.status is StageStatus.OK
    data = read_json(artifacts.NAMED.path(ctx))
    assert not is_placeholder(artifacts.NAMED.path(ctx))
    assert len(data["features"]) == 1
    props = data["features"][0]["properties"]
    assert props["name"] == "Lalbagh Botanical Garden"
    assert props["slug"] == "lalbagh-botanical-garden"
    assert props["kind"] == "park"
    assert props["name_source"] == "landmark"
    assert props["territory_id"] == str(
        territory_id(ctx.region.city, ctx.region.area, "lalbagh-botanical-garden")
    )


def test_fabric_inside_place_gets_place_name(ctx, monkeypatch):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    face = box(cx, cy, cx + 100, cy + 100)
    place_geom = box(cx - 50, cy - 50, cx + 200, cy + 200)
    _write_normalized(
        ctx,
        [
            {
                "type": "Feature",
                "geometry": mapping(to_store(face, crs)),
                "properties": {
                    "face_id": "face-00001",
                    "protected": False,
                    "kind": "fabric",
                    "area_m2": float(face.area),
                },
            }
        ],
    )
    monkeypatch.setattr(
        "lib.naming.load_places",
        lambda _ctx: [
            _NamedPlace(
                name="Jayanagar 4th Block",
                slug="jayanagar-4th-block",
                geom=place_geom,
                area_m2=float(place_geom.area),
            )
        ],
    )
    monkeypatch.setattr("lib.naming.load_named_roads", lambda _ctx: [])

    _stage07().run(ctx)
    props = read_json(artifacts.NAMED.path(ctx))["features"][0]["properties"]
    assert props["name"] == "Jayanagar 4th Block"
    assert props["kind"] == "block"
    assert props["name_source"] == "place"
    assert props.get("needs_review") is not True


def test_street_pair_fallback(ctx, monkeypatch):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    face = box(cx, cy, cx + 100, cy + 100)
    _write_normalized(
        ctx,
        [
            {
                "type": "Feature",
                "geometry": mapping(to_store(face, crs)),
                "properties": {
                    "face_id": "face-00001",
                    "protected": False,
                    "kind": "fabric",
                    "area_m2": float(face.area),
                },
            }
        ],
    )
    monkeypatch.setattr("lib.naming.load_places", lambda _ctx: [])
    monkeypatch.setattr(
        "lib.naming.load_named_roads",
        lambda _ctx: [
            _NamedRoad(name="30th Main", geom=LineString([(cx, cy), (cx + 100, cy)])),
            _NamedRoad(
                name="Kanakapura Road",
                geom=LineString([(cx, cy), (cx, cy + 100)]),
            ),
        ],
    )

    _stage07().run(ctx)
    props = read_json(artifacts.NAMED.path(ctx))["features"][0]["properties"]
    assert props["name"] == "Between 30th Main and Kanakapura Road"
    assert props["needs_review"] is True
    assert props["name_source"] == "street_pair"
    assert props["kind"] == "block"


def test_unnamed_when_no_place_or_roads(ctx, monkeypatch):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    face = box(cx, cy, cx + 80, cy + 80)
    _write_normalized(
        ctx,
        [
            {
                "type": "Feature",
                "geometry": mapping(to_store(face, crs)),
                "properties": {
                    "face_id": "face-00001",
                    "protected": False,
                    "kind": "fabric",
                    "area_m2": float(face.area),
                },
            }
        ],
    )
    monkeypatch.setattr("lib.naming.load_places", lambda _ctx: [])
    monkeypatch.setattr("lib.naming.load_named_roads", lambda _ctx: [])

    _stage07().run(ctx)
    props = read_json(artifacts.NAMED.path(ctx))["features"][0]["properties"]
    assert "name" not in props or props.get("name") is None
    assert props["needs_review"] is True
    assert props["name_source"] == "unnamed"
    assert props["slug"].startswith("unnamed-")


def test_slug_collision_disambiguated_deterministically(ctx, monkeypatch):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    place = box(cx - 10, cy - 10, cx + 300, cy + 300)
    faces = [
        box(cx, cy, cx + 50, cy + 50),
        box(cx + 60, cy + 60, cx + 110, cy + 110),
    ]
    _write_normalized(
        ctx,
        [
            {
                "type": "Feature",
                "geometry": mapping(to_store(g, crs)),
                "properties": {
                    "face_id": f"face-{i:05d}",
                    "protected": False,
                    "kind": "fabric",
                    "area_m2": float(g.area),
                },
            }
            for i, g in enumerate(faces, start=1)
        ],
    )
    monkeypatch.setattr(
        "lib.naming.load_places",
        lambda _ctx: [
            _NamedPlace(
                name="Same Place",
                slug="same-place",
                geom=place,
                area_m2=float(place.area),
            )
        ],
    )
    monkeypatch.setattr("lib.naming.load_named_roads", lambda _ctx: [])

    _stage07().run(ctx)
    first = read_json(artifacts.NAMED.path(ctx))
    slugs = sorted(f["properties"]["slug"] for f in first["features"])
    assert slugs == ["same-place", "same-place-2"]
    ids = {f["properties"]["territory_id"] for f in first["features"]}
    assert len(ids) == 2

    _stage07().run(ctx)
    second = artifact_hash_input(read_json(artifacts.NAMED.path(ctx)))
    assert artifact_hash_input(first) == second
