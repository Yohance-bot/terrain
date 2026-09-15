import uuid
from types import SimpleNamespace

from fastapi import Response

from app.api.v1.territories import (
    etag_matches,
    list_territories,
    territory_dataset_version,
    territory_state,
)


def territory(territory_id: str, version: int) -> SimpleNamespace:
    return SimpleNamespace(id=territory_id, version=version)


def test_dataset_version_is_stable_for_the_same_published_set():
    original = [
        territory("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", 1),
        territory("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", 3),
    ]
    reordered = list(reversed(original))

    version = territory_dataset_version(original, city="bengaluru", area="jayanagar")
    assert version == territory_dataset_version(reordered, city="bengaluru", area="jayanagar")


def test_dataset_version_changes_when_the_published_set_changes():
    original = [territory("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", 1)]
    republished = [territory("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", 2)]

    assert territory_dataset_version(
        original, city="bengaluru", area="jayanagar"
    ) != territory_dataset_version(republished, city="bengaluru", area="jayanagar")


def test_etag_matching_handles_quoted_and_multiple_tags():
    version = "published-version"

    assert etag_matches(f'"other", "{version}"', version)
    assert etag_matches("*", version)
    assert not etag_matches('"other"', version)


def test_static_dataset_exposes_its_sync_version_and_etag():
    row = (
        SimpleNamespace(
            id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            version=1,
            slug="test-park",
            name="Test Park",
            kind="park",
        ),
        '{"type":"MultiPolygon","coordinates":[]}',
    )
    session = SimpleNamespace(execute=lambda _statement: SimpleNamespace(all=lambda: [row]))
    response = Response()

    body = list_territories(
        response=response,
        city="testland",
        area="testville",
        if_none_match=None,
        session=session,
    )

    version = response.headers["x-territory-dataset-version"]
    assert len(version) == 64
    assert response.headers["etag"] == f'"{version}"'
    assert body.dataset_version == int(version[:8], 16)


def test_live_ownership_identifies_the_shape_dataset_it_applies_to():
    territory_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    row = (
        SimpleNamespace(
            id=territory_id,
            version=1,
            slug="test-park",
            name="Test Park",
            kind="park",
        ),
        None,
        42.5,
        None,
        None,
    )
    session = SimpleNamespace(execute=lambda _statement: SimpleNamespace(all=lambda: [row]))
    response = Response()

    states = territory_state(
        response=response, city="testland", area="testville", session=session
    )

    assert states[0].territory_id == territory_id
    assert response.headers["x-territory-dataset-version"] == territory_dataset_version(
        [row[0]], city="testland", area="testville"
    )
