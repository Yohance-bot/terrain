"""Golden tests for the generated territory set. Skipped until Phase B.

These are written now, before any GIS code, so that the target is fixed in
advance. Each skip message states the assertion the stage must satisfy; the
body is the test to unskip once the fixture in `fixtures/synthetic_aoi/` and
the corresponding stage body exist.

Do not weaken an assertion here to make a stage pass. Every one of them
corresponds to a rule in `03_MAP_AND_TERRITORY_PIPELINE` that gameplay depends
on, and a topology defect in the map surfaces later as a runner whose distance
silently counted twice or not at all.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="Phase B: needs real stage implementations and the synthetic AOI fixture"
)


def test_coverage_is_exhaustive():
    """Stage 05: the faces cover the AOI with no gaps.

    Summed face area equals AOI area to within validation.max_gap_m2. A gap is
    ground a runner can cross that affects nothing, which reads to a player as
    the game being broken.
    """
    raise NotImplementedError


def test_faces_do_not_overlap():
    """Stage 05: pairwise intersection area is zero within validation.max_overlap_m2.

    An overlap means one runner's distance counts toward two territories.
    """
    raise NotImplementedError


def test_landmarks_survive_polygonization_whole():
    """Stage 05: a protected landmark appears as exactly one output face.

    Its area matches the input landmark, and no separator cuts through it. This
    is the assertion that keeps Lalbagh one place instead of four polygons.
    """
    raise NotImplementedError


def test_scraps_merge_into_their_longest_shared_border():
    """Stage 06: a face below scrap_m2 is absorbed by the right neighbour.

    Longest shared border, not nearest centroid -- it produces the merge a
    person would have made.
    """
    raise NotImplementedError


def test_normalisation_preserves_total_area():
    """Stage 06: merging moves borders, it never creates or destroys area.

    Union of the output equals union of the input exactly.
    """
    raise NotImplementedError


def test_landmarks_are_never_merged_or_split_by_size_rules():
    """Stage 06: a protected face is byte-identical before and after normalisation.

    Lalbagh is far above fabric_soft_max_m2 and must be left alone regardless.
    """
    raise NotImplementedError


def test_naming_follows_the_documented_priority():
    """Stage 07: place name, then landmark name, then street pair, then unnamed.

    Anything reaching the last two steps carries needs_review.
    """
    raise NotImplementedError


def test_slugs_are_unique_within_a_region():
    """Stage 07: collisions are disambiguated deterministically.

    Two runs must assign the same suffix to the same polygon.
    """
    raise NotImplementedError


def test_validation_fails_closed_on_a_topology_defect():
    """Stage 08: an injected overlap produces a report and no candidates file.

    A reviewer who sees a candidates file assumes it passed.
    See tests/test_stage08_validate.py for the implemented coverage.
    """
    raise NotImplementedError


def test_publish_is_blocked_without_approval_even_when_validation_passed():
    """Stage 09: the human gate is a requirement, not an override."""
    raise NotImplementedError


def test_rerunning_the_pipeline_reproduces_identical_output():
    """The whole-pipeline guarantee: same inputs, same bytes.

    Run 01-08 twice against the fixture and compare the content hash of
    candidates.geojson, ignoring provenance members.
    """
    raise NotImplementedError


def test_republishing_unchanged_geometry_does_not_bump_versions():
    """Stage 09: identity is permanent and versions move only on real change."""
    raise NotImplementedError
