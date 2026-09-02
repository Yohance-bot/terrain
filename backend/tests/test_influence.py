import pytest

from app.services.influence import (
    InfluenceTuning,
    active_share,
    classify_activity,
    decay_active_influence,
    effort_for_segment,
    influence_for_effort,
    territory_is_abandoned,
)


def test_pace_only_classifies_activity() -> None:
    tuning = InfluenceTuning()
    assert classify_activity(1_000, 300, tuning) == "run"
    assert classify_activity(1_000, 720, tuning) == "walk"
    assert classify_activity(1_000, 0, tuning) == "walk"


def test_walking_is_worth_less_but_never_worthless() -> None:
    tuning = InfluenceTuning()
    running = effort_for_segment(
        distance_m=1_000, moving_time_s=300, activity="run", tuning=tuning
    )
    walking = effort_for_segment(
        distance_m=1_000, moving_time_s=720, activity="walk", tuning=tuning
    )
    assert 0 < walking < running


def test_diminishing_returns_compresses_owned_territory_effort() -> None:
    tuning = InfluenceTuning(gamma=1)
    assert influence_for_effort(effort=100, current_share=0, tuning=tuning) == 100
    assert influence_for_effort(effort=100, current_share=0.5, tuning=tuning) == 50
    assert influence_for_effort(effort=100, current_share=0.9, tuning=tuning) == pytest.approx(10)


def test_exponential_decay_halves_at_half_life() -> None:
    assert decay_active_influence(
        active_influence=80, elapsed_days=14, half_life_days=14
    ) == pytest.approx(40)


def test_share_and_abandonment_depend_on_total_active_influence() -> None:
    tuning = InfluenceTuning(abandonment_floor=5)
    assert active_share(contributor_active=4, total_active=10) == 0.4
    assert not territory_is_abandoned(total_active=5, tuning=tuning)
    assert territory_is_abandoned(total_active=4.99, tuning=tuning)
