"""Stage 08 fail-closed validation."""

from __future__ import annotations

import pytest
from shapely.geometry import box, mapping

from lib import artifacts
from lib.contracts import StageStatus
from lib.crs import to_store, to_work
from lib.determinism import territory_id
from lib.io import artifact_hash_input, is_placeholder, read_json, write_geojson, write_json
from lib.registry import discover_stages
from lib.validate import (
    ValidationFailedError,
    _check_atomic_landmark_integrity,
    chain_fingerprint_path,
)


def _stage08():
    return next(s for s in discover_stages() if s.number == 8)


def _aoi_work(ctx):
    return to_work(box(*ctx.region.bbox.as_xy_bounds()), ctx.region.crs_work)


def _feature(geom_store, **props):
    return {
        "type": "Feature",
        "geometry": mapping(geom_store) if not isinstance(geom_store, dict) else geom_store,
        "properties": props,
    }


def _mint(ctx, slug: str) -> str:
    return str(territory_id(ctx.region.city, ctx.region.area, slug))


def test_atomic_landmark_must_have_one_whole_provenance_holder(ctx):
    crs = ctx.region.crs_work
    atomic_id = _mint(ctx, "jain-college")
    fabric_id = _mint(ctx, "jayanagar-fabric")
    atomic_work = box(500_000, 1_430_000, 500_100, 1_430_100)
    parcel = _feature(
        to_store(atomic_work, crs),
        territory_id=atomic_id,
        slug="jain-college",
        atomic=True,
        protected=False,
    )
    whole = _feature(
        to_store(box(499_900, 1_429_900, 500_200, 1_430_200), crs),
        territory_id="gameplay-1",
        member_territory_ids=[atomic_id, fabric_id],
        protected=False,
    )
    assert (
        _check_atomic_landmark_integrity(
            [parcel],
            [whole],
            crs,
            max_missing_m2=1.0,
            standalone_min_m2=ctx.thresholds.standalone_min_area_m2,
        )
        == []
    )

    standalone = _feature(
        to_store(atomic_work, crs),
        territory_id="gameplay-2",
        member_territory_ids=[atomic_id],
        protected=False,
    )
    failures = _check_atomic_landmark_integrity(
        [parcel],
        [standalone],
        crs,
        max_missing_m2=1.0,
        standalone_min_m2=ctx.thresholds.standalone_min_area_m2,
    )
    assert any(item["check"] == "atomic_absorption" for item in failures)

    split_a = _feature(
        to_store(box(500_000, 1_430_000, 500_050, 1_430_100), crs),
        territory_id="gameplay-3",
        member_territory_ids=[atomic_id, fabric_id],
        protected=False,
    )
    split_b = _feature(
        to_store(box(500_050, 1_430_000, 500_100, 1_430_100), crs),
        territory_id="gameplay-4",
        member_territory_ids=[atomic_id, "other"],
        protected=False,
    )
    failures = _check_atomic_landmark_integrity(
        [parcel],
        [split_a, split_b],
        crs,
        max_missing_m2=1.0,
        standalone_min_m2=ctx.thresholds.standalone_min_area_m2,
    )
    assert any(item["check"] == "atomic_integrity" for item in failures)

    # Absorbed atomic inside multi-member ordinary fabric is a success even when
    # the source parcel alone is under the 50-acre floor.
    absorbed = _feature(
        to_store(box(499_500, 1_429_500, 500_700, 1_430_700), crs),
        territory_id="gameplay-ordinary",
        member_territory_ids=[atomic_id, fabric_id],
        protected=False,
        landmark_dedicated=False,
        territory_class="ordinary",
    )
    assert (
        _check_atomic_landmark_integrity(
            [parcel],
            [absorbed],
            crs,
            max_missing_m2=1.0,
            standalone_min_m2=ctx.thresholds.standalone_min_area_m2,
        )
        == []
    )


def _write_landmarks(ctx, features: list[dict]) -> None:
    write_geojson(
        artifacts.LANDMARKS.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "extract_landmarks"},
    )


def _write_normalized(ctx, features: list[dict]) -> None:
    write_geojson(
        artifacts.NORMALIZED.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "normalize_sizes"},
    )


def _write_named(ctx, features: list[dict]) -> None:
    write_geojson(
        artifacts.NAMED.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "assign_names"},
    )


def _pass_partition(ctx):
    """One protected major + fabric filling the rest of the AOI (no overlap)."""
    crs = ctx.region.crs_work
    aoi = _aoi_work(ctx)
    minx, miny, maxx, maxy = aoi.bounds
    mid = (minx + maxx) / 2.0
    protected = box(minx, miny, mid, maxy)
    fabric = box(mid, miny, maxx, maxy)
    # Nudge shared edge so shapely overlap area is ~0 (touch only).
    fabric = box(mid, miny, maxx, maxy)

    slug = "test-park"
    tid = _mint(ctx, slug)
    tid_fab = _mint(ctx, "west-fabric")
    area_p = float(protected.area)
    area_f = float(fabric.area)

    landmark = _feature(
        to_store(protected, crs),
        protected=True,
        role="major",
        name="Test Park",
        slug=slug,
        kind="park",
        area_m2=area_p,
    )
    named = [
        _feature(
            to_store(protected, crs),
            territory_id=tid,
            face_id="face-00001",
            protected=True,
            role="major",
            name="Test Park",
            slug=slug,
            kind="park",
            name_source="landmark",
            needs_review=False,
            area_m2=area_p,
        ),
        _feature(
            to_store(fabric, crs),
            territory_id=tid_fab,
            face_id="face-00002",
            protected=False,
            name="West Fabric",
            slug="west-fabric",
            kind="block",
            name_source="place",
            needs_review=True,
            area_m2=area_f,
        ),
    ]
    normalized = [
        _feature(
            to_store(protected, crs),
            face_id="face-00001",
            protected=True,
            role="major",
            name="Test Park",
            slug=slug,
            kind="park",
            area_m2=area_p,
        ),
        _feature(
            to_store(fabric, crs),
            face_id="face-00002",
            protected=False,
            kind="fabric",
            area_m2=area_f,
            needs_review=True,
        ),
    ]
    return landmark, named, normalized


def test_valid_partition_passes_and_writes_candidates(ctx):
    landmark, named, normalized = _pass_partition(ctx)
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)

    result = _stage08().run(ctx)
    assert result.status is StageStatus.OK
    assert artifacts.CANDIDATES.path(ctx).exists()
    assert not is_placeholder(artifacts.CANDIDATES.path(ctx))
    report = read_json(artifacts.VALIDATION_REPORT.path(ctx))
    assert report["status"] == "pass"
    assert report["hard"]["passed"] is True
    assert report["soft"]["needs_review_count"] == 1
    assert chain_fingerprint_path(ctx).exists()


def test_overlap_fails_closed_no_candidates(ctx):
    landmark, named, normalized = _pass_partition(ctx)
    # Inflate first poly so it overlaps the second heavily.
    aoi = _aoi_work(ctx)
    minx, miny, maxx, maxy = aoi.bounds
    mid = (minx + maxx) / 2.0
    overlap_left = box(minx, miny, mid + (maxx - minx) * 0.2, maxy)
    named[0]["geometry"] = mapping(to_store(overlap_left, ctx.region.crs_work))
    named[0]["properties"]["area_m2"] = float(overlap_left.area)
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)

    with pytest.raises(ValidationFailedError, match="overlap"):
        _stage08().run(ctx)

    assert artifacts.VALIDATION_REPORT.path(ctx).exists()
    assert not artifacts.CANDIDATES.path(ctx).exists()
    report = read_json(artifacts.VALIDATION_REPORT.path(ctx))
    assert report["status"] == "fail"
    assert any(f["check"] == "overlap" for f in report["hard"]["failures"])


def test_gap_fails_closed_no_candidates(ctx):
    crs = ctx.region.crs_work
    aoi = _aoi_work(ctx)
    minx, miny, maxx, maxy = aoi.bounds
    tiny = box(minx, miny, minx + 10, miny + 10)
    slug = "tiny-block"
    named = [
        _feature(
            to_store(tiny, crs),
            territory_id=_mint(ctx, slug),
            protected=False,
            name="Tiny",
            slug=slug,
            kind="block",
            name_source="place",
            needs_review=False,
            area_m2=float(tiny.area),
        )
    ]
    _write_landmarks(ctx, [])
    _write_normalized(ctx, [])
    _write_named(ctx, named)

    with pytest.raises(ValidationFailedError):
        _stage08().run(ctx)

    assert not artifacts.CANDIDATES.path(ctx).exists()
    report = read_json(artifacts.VALIDATION_REPORT.path(ctx))
    checks = {f["check"] for f in report["hard"]["failures"]}
    assert "gap" in checks or "coverage" in checks


def test_duplicate_territory_id_fails(ctx):
    landmark, named, normalized = _pass_partition(ctx)
    named[1]["properties"]["territory_id"] = named[0]["properties"]["territory_id"]
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)

    with pytest.raises(ValidationFailedError, match="territory_id"):
        _stage08().run(ctx)
    assert not artifacts.CANDIDATES.path(ctx).exists()


def test_duplicate_slug_fails(ctx):
    landmark, named, normalized = _pass_partition(ctx)
    named[1]["properties"]["slug"] = named[0]["properties"]["slug"]
    named[1]["properties"]["territory_id"] = _mint(ctx, "other-id-slug")
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)

    with pytest.raises(ValidationFailedError, match="slug"):
        _stage08().run(ctx)


def test_missing_name_fails(ctx):
    landmark, named, normalized = _pass_partition(ctx)
    named[1]["properties"]["name"] = ""
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)

    with pytest.raises(ValidationFailedError, match="names"):
        _stage08().run(ctx)


def test_invalid_polygon_fails(ctx):
    landmark, named, normalized = _pass_partition(ctx)
    # Self-intersecting bowtie in storage CRS.
    named[1]["geometry"] = {
        "type": "Polygon",
        "coordinates": [
            [
                [77.57, 12.91],
                [77.58, 12.92],
                [77.58, 12.91],
                [77.57, 12.92],
                [77.57, 12.91],
            ]
        ],
    }
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)

    with pytest.raises(ValidationFailedError, match="valid_geometry"):
        _stage08().run(ctx)


def test_missing_protected_major_fails(ctx):
    landmark, named, normalized = _pass_partition(ctx)
    # Drop protected from named; keep landmark major.
    named = [f for f in named if not f["properties"].get("protected")]
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)

    with pytest.raises(ValidationFailedError, match="protected"):
        _stage08().run(ctx)


def test_fingerprint_written_with_named_hash(ctx):
    landmark, named, normalized = _pass_partition(ctx)
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)
    # Earlier chain artifacts optional; write named is enough for sha256.
    write_json(
        artifacts.RAW_MANIFEST.path(ctx),
        {"status": "ok", "overture_release": "test"},
    )

    _stage08().run(ctx)
    fp = read_json(chain_fingerprint_path(ctx))
    assert fp["pipeline_stages"] == "01-07"
    assert fp["artifacts"]["named"]["present"] is True
    assert fp["artifacts"]["named"]["sha256"]
    assert fp["artifacts"]["raw_manifest"]["sha256"]
    assert "created" not in fp


def test_needs_review_soft_does_not_block(ctx):
    landmark, named, normalized = _pass_partition(ctx)
    assert named[1]["properties"]["needs_review"] is True
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)

    result = _stage08().run(ctx)
    assert result.status is StageStatus.OK
    report = read_json(artifacts.VALIDATION_REPORT.path(ctx))
    assert report["soft"]["needs_review_count"] >= 1
    assert report["status"] == "pass"


def test_pass_runs_are_deterministic(ctx):
    landmark, named, normalized = _pass_partition(ctx)
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)

    _stage08().run(ctx)
    first = artifact_hash_input(read_json(artifacts.CANDIDATES.path(ctx)))

    artifacts.CANDIDATES.path(ctx).unlink()
    artifacts.VALIDATION_REPORT.path(ctx).unlink()
    chain_fingerprint_path(ctx).unlink()

    _stage08().run(ctx)
    second = artifact_hash_input(read_json(artifacts.CANDIDATES.path(ctx)))
    assert first == second
