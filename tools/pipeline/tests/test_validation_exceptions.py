"""Stage 08 known-exceptions mechanism.

Covers: exception list respected, excluded features absent from
candidates.geojson, hard pass achieved with exceptions, default (flag off)
behaviour unchanged, and coverage/gap logic around excluded parcels.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from shapely.geometry import box, mapping

from lib import artifacts
from lib.config import ConfigError, load_validation_exceptions
from lib.contracts import StageStatus
from lib.crs import to_store, to_work
from lib.determinism import territory_id
from lib.io import read_json, write_geojson
from lib.registry import discover_stages
from lib.validate import ValidationFailedError


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


def _write_landmarks(ctx, features):
    write_geojson(
        artifacts.LANDMARKS.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "extract_landmarks"},
    )


def _write_normalized(ctx, features):
    write_geojson(
        artifacts.NORMALIZED.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "normalize_sizes"},
    )


def _write_named(ctx, features):
    write_geojson(
        artifacts.NAMED.path(ctx), features, pipeline={"status": "ok", "stage": "assign_names"}
    )


def _partition_with_unnamed_slice(ctx):
    """Protected major + two fabric slices; the second slice has no name.

    Together the three pieces exactly tile the AOI with no gap/overlap, so
    the only hard failure is the missing name on the third slice -- letting
    tests isolate the exception mechanism from every other check.
    """
    crs = ctx.region.crs_work
    aoi = _aoi_work(ctx)
    minx, miny, maxx, maxy = aoi.bounds
    third = (maxx - minx) / 3.0

    protected = box(minx, miny, minx + third, maxy)
    fabric_named = box(minx + third, miny, minx + 2 * third, maxy)
    fabric_unnamed = box(minx + 2 * third, miny, maxx, maxy)

    slug_p = "test-park"
    slug_named = "east-fabric"
    slug_unnamed = "unnamed-slice"
    tid_p, tid_named, tid_unnamed = (
        _mint(ctx, slug_p),
        _mint(ctx, slug_named),
        _mint(ctx, slug_unnamed),
    )

    landmark = _feature(
        to_store(protected, crs),
        protected=True,
        role="major",
        name="Test Park",
        slug=slug_p,
        kind="park",
        area_m2=float(protected.area),
    )
    named = [
        _feature(
            to_store(protected, crs),
            territory_id=tid_p,
            face_id="face-00001",
            protected=True,
            role="major",
            name="Test Park",
            slug=slug_p,
            kind="park",
            name_source="landmark",
            needs_review=False,
            area_m2=float(protected.area),
        ),
        _feature(
            to_store(fabric_named, crs),
            territory_id=tid_named,
            face_id="face-00002",
            protected=False,
            name="East Fabric",
            slug=slug_named,
            kind="block",
            name_source="place",
            needs_review=False,
            area_m2=float(fabric_named.area),
        ),
        _feature(
            to_store(fabric_unnamed, crs),
            territory_id=tid_unnamed,
            face_id="face-00003",
            protected=False,
            name=None,
            slug=slug_unnamed,
            kind="block",
            name_source="unnamed",
            needs_review=True,
            area_m2=float(fabric_unnamed.area),
        ),
    ]
    normalized = [
        _feature(
            to_store(protected, crs),
            face_id="face-00001",
            protected=True,
            role="major",
            name="Test Park",
            slug=slug_p,
            kind="park",
            area_m2=float(protected.area),
        ),
        _feature(
            to_store(fabric_named, crs),
            face_id="face-00002",
            protected=False,
            kind="fabric",
            area_m2=float(fabric_named.area),
        ),
        _feature(
            to_store(fabric_unnamed, crs),
            face_id="face-00003",
            protected=False,
            kind="fabric",
            area_m2=float(fabric_unnamed.area),
        ),
    ]
    return landmark, named, normalized, slug_unnamed


def _stub_exceptions(monkeypatch, slugs_and_reasons: dict[str, str]) -> None:
    """Stand in for `lib.config.load_validation_exceptions`.

    Config loading (region YAML, thresholds, and this exceptions file) always
    reads from the real `tools/pipeline/config/` tree, never from a test's
    `tmp_path` repo root -- that is true of every other config fixture in this
    suite too (see `conftest.py`). Stubbing the loader lets these tests drive
    the mechanism without writing into the real config directory.
    """

    def _fake(_region_name, config_root=None):
        return dict(slugs_and_reasons)

    monkeypatch.setattr("lib.validate.load_validation_exceptions", _fake)


# --- lib.config.load_validation_exceptions ----------------------------------


def test_load_validation_exceptions_reads_file(tmp_path):
    regions = tmp_path / "regions"
    regions.mkdir(parents=True)
    (regions / "myregion.exceptions.json").write_text(
        '{"exceptions": [{"slug": "a", "reason": "bad edge"}, '
        '{"slug": "b", "reason": "sliver"}]}',
        encoding="utf-8",
    )
    result = load_validation_exceptions("myregion", config_root=tmp_path)
    assert result == {"a": "bad edge", "b": "sliver"}


def test_load_validation_exceptions_reads_slug_and_territory_id(tmp_path):
    regions = tmp_path / "regions"
    regions.mkdir(parents=True)
    (regions / "myregion.exceptions.json").write_text(
        '{"exceptions": [{"slug": "asc-war-memorial", "territory_id": "abc-123", "reason": "MVP exception"}]}',
        encoding="utf-8",
    )
    result = load_validation_exceptions("myregion", config_root=tmp_path)
    assert result["asc-war-memorial"] == "MVP exception"
    assert result["abc-123"] == "MVP exception"


def test_load_validation_exceptions_missing_file_raises(tmp_path):
    (tmp_path / "regions").mkdir(parents=True)
    with pytest.raises(ConfigError, match="no exceptions file"):
        load_validation_exceptions("no_such_region", config_root=tmp_path)


def test_load_validation_exceptions_rejects_missing_reason(tmp_path):
    regions = tmp_path / "regions"
    regions.mkdir(parents=True)
    (regions / "myregion.exceptions.json").write_text(
        '{"exceptions": [{"slug": "a"}]}', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="reason"):
        load_validation_exceptions("myregion", config_root=tmp_path)


def test_load_validation_exceptions_rejects_duplicate_slug(tmp_path):
    regions = tmp_path / "regions"
    regions.mkdir(parents=True)
    (regions / "myregion.exceptions.json").write_text(
        '{"exceptions": [{"slug": "a", "reason": "x"}, {"slug": "a", "reason": "y"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_validation_exceptions("myregion", config_root=tmp_path)


def test_load_validation_exceptions_rejects_empty_list(tmp_path):
    regions = tmp_path / "regions"
    regions.mkdir(parents=True)
    (regions / "myregion.exceptions.json").write_text('{"exceptions": []}', encoding="utf-8")
    with pytest.raises(ConfigError, match="non-empty"):
        load_validation_exceptions("myregion", config_root=tmp_path)


# --- default (flag off) behaviour is unchanged -------------------------------


def test_flag_off_by_default(ctx):
    assert ctx.allow_validation_exceptions is False


def test_flag_off_missing_name_still_hard_fails(ctx):
    landmark, named, normalized, slug_unnamed = _partition_with_unnamed_slice(ctx)
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)
    # No exceptions file written, flag left off -- must behave exactly like
    # every region did before this mechanism existed.
    with pytest.raises(ValidationFailedError, match="names"):
        _stage08().run(ctx)
    assert not artifacts.CANDIDATES.path(ctx).exists()
    report = read_json(artifacts.VALIDATION_REPORT.path(ctx))
    assert report["status"] == "fail"
    assert "excluded_known_exceptions" not in report
    assert any(
        f["check"] == "names" and slug_unnamed in f["detail"] for f in report["hard"]["failures"]
    )


def test_flag_off_ignores_a_matching_exception_list(ctx, monkeypatch):
    """An exceptions list that *would* cover this slug must not matter unless
    the flag is actually on."""
    landmark, named, normalized, slug_unnamed = _partition_with_unnamed_slice(ctx)
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)
    _stub_exceptions(monkeypatch, {slug_unnamed: "some reason"})

    with pytest.raises(ValidationFailedError, match="names"):
        _stage08().run(ctx)
    assert not artifacts.CANDIDATES.path(ctx).exists()


# --- flag on: exception respected, excluded from candidates, hard pass ------


def test_known_exception_excluded_and_hard_pass(ctx, monkeypatch):
    landmark, named, normalized, slug_unnamed = _partition_with_unnamed_slice(ctx)
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)
    _stub_exceptions(monkeypatch, {slug_unnamed: "bbox-edge naming gap, accepted for MVP review"})
    ctx = replace(ctx, allow_validation_exceptions=True)

    result = _stage08().run(ctx)
    assert result.status is StageStatus.OK

    candidates = read_json(artifacts.CANDIDATES.path(ctx))
    candidate_slugs = {f["properties"]["slug"] for f in candidates["features"]}
    assert slug_unnamed not in candidate_slugs
    assert len(candidates["features"]) == 2

    report = read_json(artifacts.VALIDATION_REPORT.path(ctx))
    assert report["status"] == "pass"
    assert report["hard"]["passed"] is True
    assert not any(f["check"] == "names" for f in report["hard"]["failures"])

    excluded = report["excluded_known_exceptions"]
    assert excluded["count"] == 1
    assert excluded["features"][0]["slug"] == slug_unnamed
    assert excluded["features"][0]["reason"] == (
        "bbox-edge naming gap, accepted for MVP review"
    )
    assert excluded["unused_exceptions"] == []


def test_unused_exception_is_reported(ctx, monkeypatch):
    """A slug in the exceptions file that never shows up as a failure this run
    is not silently dropped -- it is surfaced so a stale list gets noticed."""
    landmark, named, normalized, slug_unnamed = _partition_with_unnamed_slice(ctx)
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)
    _stub_exceptions(monkeypatch, {slug_unnamed: "known gap", "never-seen-slug": "stale entry"})
    ctx = replace(ctx, allow_validation_exceptions=True)

    _stage08().run(ctx)
    report = read_json(artifacts.VALIDATION_REPORT.path(ctx))
    assert report["excluded_known_exceptions"]["unused_exceptions"] == ["never-seen-slug"]


def test_exception_does_not_apply_if_feature_actually_has_a_name(ctx, monkeypatch):
    """The exception list only ever excludes a genuine 'missing name' failure.

    If the slug in the exceptions list is later fixed upstream and now has a
    real name, it must not be excluded -- exclusion is not a blanket "always
    drop this slug" switch.
    """
    landmark, named, normalized, slug_unnamed = _partition_with_unnamed_slice(ctx)
    for feature in named:
        if feature["properties"]["slug"] == slug_unnamed:
            feature["properties"]["name"] = "Now Has A Real Name"
            feature["properties"]["name_source"] = "place"
            feature["properties"]["needs_review"] = False
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)
    _stub_exceptions(monkeypatch, {slug_unnamed: "should not be needed anymore"})
    ctx = replace(ctx, allow_validation_exceptions=True)

    result = _stage08().run(ctx)
    assert result.status is StageStatus.OK
    candidates = read_json(artifacts.CANDIDATES.path(ctx))
    candidate_slugs = {f["properties"]["slug"] for f in candidates["features"]}
    assert slug_unnamed in candidate_slugs
    report = read_json(artifacts.VALIDATION_REPORT.path(ctx))
    assert report["excluded_known_exceptions"]["count"] == 0
    assert report["excluded_known_exceptions"]["unused_exceptions"] == [slug_unnamed]


def test_known_exception_matches_renamed_hard_max_source_slug():
    from lib.validate import _matches_known_exception

    props = {
        "slug": "agaram-2",
        "hard_max_exception_source_slug": "agaram-72",
        "territory_id": "renamed-terr-id",
        "member_territory_ids": ["legacy-id"],
    }
    known = {"agaram-72": "mvp reviewed hard max", "legacy-id": "legacy member id"}

    assert _matches_known_exception(props, known) is True
    assert _matches_known_exception({"slug": "new-slug", "territory_id": "legacy-id"}, known) is True


# --- coverage / gap semantics around excluded parcels ------------------------


def test_excluded_parcel_is_an_intentional_hole_not_a_gap_failure(ctx, monkeypatch):
    """Removing the unnamed slice's area from the mosaic must not trip the
    gap/coverage hard checks -- the AOI used for that math shrinks by exactly
    the excluded footprint."""
    landmark, named, normalized, slug_unnamed = _partition_with_unnamed_slice(ctx)
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)
    _stub_exceptions(monkeypatch, {slug_unnamed: "bbox-edge naming gap"})
    ctx = replace(ctx, allow_validation_exceptions=True)

    result = _stage08().run(ctx)
    assert result.status is StageStatus.OK
    report = read_json(artifacts.VALIDATION_REPORT.path(ctx))
    assert not any(f["check"] in ("gap", "coverage") for f in report["hard"]["failures"])
    # Coverage ratio is computed against the shrunken (effective) AOI, so the
    # two remaining pieces cover ~100% of what is left, not ~66%.
    assert report["metrics"]["coverage_ratio"] == pytest.approx(1.0, abs=1e-6)
    assert report["metrics"]["gap_m2"] == pytest.approx(0.0, abs=1.0)


def test_exceptions_never_asked_for_when_flag_off(ctx, monkeypatch):
    """Loading the exceptions file must not even be attempted when disabled."""
    from lib import validate as validate_lib

    def _boom(*_args, **_kwargs):
        raise AssertionError("load_validation_exceptions must not be called when flag is off")

    monkeypatch.setattr(validate_lib, "load_validation_exceptions", _boom)

    landmark, named, normalized, _slug_unnamed = _partition_with_unnamed_slice(ctx)
    _write_landmarks(ctx, [landmark])
    _write_normalized(ctx, normalized)
    _write_named(ctx, named)

    with pytest.raises(ValidationFailedError):
        _stage08().run(ctx)
