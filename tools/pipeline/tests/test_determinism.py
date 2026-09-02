"""Identity and reproducibility guarantees.

The pipeline promises that identical inputs give identical output, and that a
territory keeps its identifier when its shape is redrawn. Both promises live
entirely in `lib/determinism.py`, so they are tested directly.
"""

from __future__ import annotations

import uuid

import pytest

from lib.determinism import (
    TERRITORY_NAMESPACE,
    canonical_json,
    content_hash,
    slugify,
    stable_sort,
    territory_id,
)


def test_territory_id_is_stable_across_calls():
    first = territory_id("bengaluru", "jayanagar_lalbagh", "lalbagh")
    second = territory_id("bengaluru", "jayanagar_lalbagh", "lalbagh")
    assert first == second


def test_territory_id_survives_a_geometry_change():
    """The point of the whole identity scheme.

    Redrawing a boundary must not mint a new territory -- every ownership row,
    standing and run segment already points at the existing id.
    """
    before = territory_id("bengaluru", "jayanagar_lalbagh", "lalbagh")
    # Same place, new shape. Identity is derived from city/area/slug only, so
    # the geometry is not even an input here, which is the guarantee.
    after = territory_id("bengaluru", "jayanagar_lalbagh", "lalbagh")
    assert before == after


def test_territory_id_matches_the_milestone_1_scheme():
    # tools/territory-import mints ids the same way. If these ever diverge, the
    # same real place would exist twice in the database under two ids.
    expected = uuid.uuid5(TERRITORY_NAMESPACE, "bengaluru/jayanagar/lalbagh")
    assert territory_id("bengaluru", "jayanagar", "lalbagh") == expected


def test_different_places_get_different_ids():
    assert territory_id("bengaluru", "jayanagar_lalbagh", "lalbagh") != territory_id(
        "bengaluru", "jayanagar_lalbagh", "sarakki-lake"
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Lalbagh Botanical Garden", "lalbagh-botanical-garden"),
        ("Jayanagar 4th Block", "jayanagar-4th-block"),
        ("  Sarakki Lake  ", "sarakki-lake"),
        ("Krishna Rao Park (South)", "krishna-rao-park-south"),
    ],
)
def test_slugify(name, expected):
    assert slugify(name) == expected


def test_slugify_rejects_a_name_with_no_usable_characters():
    with pytest.raises(ValueError):
        slugify("---")


def test_canonical_json_ignores_key_insertion_order():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_content_hash_detects_a_geometry_change():
    """This is the signal that bumps a territory's version.

    Identity stays; the version moves. Two halves of the same rule.
    """
    original = [[77.58, 12.95], [77.59, 12.95], [77.59, 12.96]]
    nudged = [[77.58, 12.95], [77.59, 12.95], [77.59, 12.9601]]
    assert content_hash(original) == content_hash(list(original))
    assert content_hash(original) != content_hash(nudged)


def test_content_hash_accepts_str_and_bytes():
    assert content_hash("lalbagh") == content_hash(b"lalbagh")


def test_stable_sort_is_reproducible():
    features = [{"slug": "sarakki-lake"}, {"slug": "lalbagh"}, {"slug": "ragigudda"}]
    ordered = stable_sort(features, key=lambda f: f["slug"])
    assert [f["slug"] for f in ordered] == ["lalbagh", "ragigudda", "sarakki-lake"]
    assert stable_sort(reversed(features), key=lambda f: f["slug"]) == ordered
