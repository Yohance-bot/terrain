"""The real config files load, and encode the decisions already made."""

from __future__ import annotations

import pytest

from lib.config import BBox, ConfigError, available_regions, load_region


def test_region_is_discoverable():
    assert "bengaluru_jayanagar_lalbagh" in available_regions()


def test_region_loads_with_expected_identity(region):
    assert region.city == "bengaluru"
    # Deliberately not "jayanagar": Milestone 2 publishes alongside the
    # hand-made Milestone 1 data so that rolling back is a config change.
    assert region.area == "jayanagar_lalbagh"


def test_working_crs_is_projected_metres(region):
    # Every threshold in the pipeline is in metres. UTM 43N is the zone that
    # covers Bengaluru; anything else here silently rescales every measurement.
    assert region.crs_work == "EPSG:32643"
    assert region.crs_store == "EPSG:4326"


def test_bbox_covers_the_corridor(region):
    bbox = region.bbox
    # Lalbagh sits near 12.95N, 77.58E and must be inside the AOI -- it is the
    # landmark the milestone is judged on.
    assert bbox.south < 12.95 < bbox.north
    assert bbox.west < 77.58 < bbox.east


def test_bbox_rejects_inverted_input(tmp_path):
    with pytest.raises(ConfigError):
        BBox.from_list([12.9, 77.6, 12.8, 77.5], tmp_path / "fake.yaml")


def test_overture_release_is_pinned(region):
    # Stage 01 refuses floating sources. The pin lives in the region YAML so a
    # re-run tomorrow cannot silently change the map under our feet.
    assert region.overture.release == "2026-07-22.0"
    region.require_pinned_sources()


def test_geofabrik_extract_is_dated_not_latest(region):
    # *-latest moves every day. A dated extract keeps the pipeline reproducible.
    assert "latest" not in region.geofabrik.extract_url
    assert "southern-zone-260804.osm.pbf" in region.geofabrik.extract_url


def test_unpinned_release_fails_loudly(region):
    from dataclasses import replace

    from lib.config import OvertureSource

    unpinned = replace(
        region,
        overture=OvertureSource(release=None, themes=region.overture.themes),
    )
    with pytest.raises(ConfigError, match="not pinned"):
        unpinned.require_pinned_sources()


def test_thresholds_are_present_and_ordered(thresholds):
    assert thresholds.snap_m > 0
    assert thresholds.territory_min_area_m2 == 20000
    assert thresholds.territory_min_area_m2 == thresholds.fabric_soft_min_m2
    assert thresholds.scrap_m2 < thresholds.fabric_soft_min_m2
    assert thresholds.fabric_soft_min_m2 < thresholds.fabric_soft_max_m2
    assert thresholds.fabric_soft_max_m2 < thresholds.fabric_review_max_m2


def test_gameplay_thresholds_are_present_and_ordered(thresholds):
    gp = thresholds.gameplay
    assert (
        gp.soft_min_m2
        < gp.soft_max_m2
        <= gp.place_max_m2
        <= gp.review_max_m2
        <= gp.hard_max_m2
    )
    assert gp.soft_min_m2 / 4046.8564224 == pytest.approx(250)
    assert gp.soft_max_m2 / 4046.8564224 == pytest.approx(300)
    assert gp.hard_max_m2 / 4046.8564224 == pytest.approx(350)
    assert gp.min_shared_border_m > 0
    assert "motorway" in gp.barrier_highway_classes


def test_beautify_thresholds_are_present(thresholds):
    bt = thresholds.beautify
    assert bt.critic == "heuristic"
    assert 0.0 <= bt.auto_apply_min_confidence <= 1.0
    assert 0.0 < bt.min_compactness <= 1.0
    assert 0.0 < bt.peninsula_border_share <= 1.0
    assert bt.min_peninsula_shared_border_m >= 0
    assert bt.jagged_complexity >= 1.0
    assert bt.max_aspect_ratio == pytest.approx(3.0)
    assert bt.min_aspect_improvement >= 0
    assert bt.min_transfer_compactness_gain >= 0
    assert bt.max_suggestions > 0
    assert bt.max_exterior_corners == 10
    assert bt.corner_snap_m > 0


def test_gameplay_barrier_classes(thresholds):
    gp = thresholds.gameplay
    assert "trunk" not in gp.barrier_highway_classes
    assert "primary" not in gp.barrier_highway_classes
    assert "residential" not in gp.barrier_highway_classes
    assert "rail" in gp.barrier_railway_classes
    assert gp.barrier_area_groups == ()
    assert thresholds.atomic_min_area_m2 < thresholds.standalone_min_area_m2
    assert thresholds.standalone_min_area_m2 / 4046.8564224 == pytest.approx(60)


def test_validation_gates_are_strict(thresholds):
    validation = thresholds.validation
    assert validation.min_coverage_ratio > 0.99
    # An unnamed territory is unreviewable, so it cannot reach players.
    assert validation.allow_unnamed_publish is False


@pytest.mark.parametrize("excluded", ["footway", "cycleway", "path", "service", "pedestrian"])
def test_runnable_ways_are_never_borders(feature_classes, excluded):
    # A border along something people run on invites border-hugging, where a
    # runner farms two territories at once by running the line between them.
    assert feature_classes.is_excluded_highway(excluded)


@pytest.mark.parametrize("included", ["primary", "secondary", "tertiary", "residential"])
def test_road_classes_that_divide_neighbourhoods_are_borders(feature_classes, included):
    assert included in feature_classes.included("highway")


def test_include_and_exclude_do_not_overlap(feature_classes):
    # A class in both lists means the outcome depends on evaluation order,
    # which is exactly the kind of thing nobody notices until the map is wrong.
    overlap = set(feature_classes.included("highway")) & set(feature_classes.excluded("highway"))
    assert not overlap, f"highway classes are both included and excluded: {sorted(overlap)}"


def test_missing_region_fails_loudly():
    with pytest.raises(ConfigError, match="not found"):
        load_region("no_such_region")
