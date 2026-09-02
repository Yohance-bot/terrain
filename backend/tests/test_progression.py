import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models import DeviceProfile, Territory
from app.schemas import HomeSelectionMetadata
from app.services.progression import ProgressionTotals, _experience, _prestige, set_home


def test_experience_uses_a_transparent_fixed_xp_curve() -> None:
    summary = _experience(
        ProgressionTotals(
            applied_tracked_runs=3,
            applied_tracked_distance_m=10_250,
            territories_contributed=2,
            lifetime_influence=800,
            active_influence=120,
        )
    )

    assert summary.total_xp == 1_025
    assert summary.level == 2
    assert summary.xp_into_level == 25
    assert summary.xp_to_next_level == 975


def test_prestige_exposes_each_derived_component() -> None:
    summary = _prestige(
        ProgressionTotals(
            applied_tracked_runs=2,
            applied_tracked_distance_m=0,
            territories_contributed=1,
            lifetime_influence=40,
            active_influence=5,
        )
    )

    assert summary.legacy_component == 40
    assert summary.active_component == 5
    assert summary.consistency_component == 20
    assert summary.score == 65


def test_home_metadata_rejects_unbounded_notes() -> None:
    with pytest.raises(ValidationError):
        HomeSelectionMetadata(note="x" * 65)


class FakeSession:
    def __init__(self, profile: DeviceProfile | None, territory_id: uuid.UUID) -> None:
        self.profile = profile
        self.territory_id = territory_id
        self.added: list[object] = []
        self.flush_count = 0

    def get(self, model: type[object], key: object) -> object | None:
        if model is Territory:
            return object() if key == self.territory_id else None
        if model is DeviceProfile:
            return self.profile
        raise AssertionError(f"unexpected model access: {model}")

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, DeviceProfile):
            self.profile = value

    def flush(self) -> None:
        self.flush_count += 1


def test_home_change_enforces_cooldown_without_touching_territory_state() -> None:
    device_id, first_home, second_home = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime(2026, 8, 12, tzinfo=UTC)
    profile = DeviceProfile(
        device_id=device_id,
        home_territory_id=first_home,
        home_selected_at=now - timedelta(days=1),
        home_change_available_at=now + timedelta(days=29),
        home_selection_source="onboarding",
    )
    session = FakeSession(profile, second_home)

    with pytest.raises(HTTPException) as exc_info:
        set_home(
            session,
            device_id=device_id,
            territory_id=second_home,
            metadata=HomeSelectionMetadata(source="settings"),
            now=now,
        )

    assert exc_info.value.status_code == 409
    assert profile.home_territory_id == first_home
    assert session.added == []
    assert session.flush_count == 0
