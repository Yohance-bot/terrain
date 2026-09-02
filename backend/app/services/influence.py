"""Pure, deterministic Phase 1 influence calculations.

These functions intentionally contain no database access.  The ingestion worker
supplies server-derived distance and moving time, loads a versioned tuning
snapshot, and persists the resulting grant.  Keeping the maths here makes
reprocessing and tests independent of transport and storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Literal

ActivityKind = Literal["walk", "run"]


@dataclass(frozen=True)
class InfluenceTuning:
    """Versioned knobs, with the documented starting assumptions."""

    distance_weight: float = 1.0
    moving_time_weight: float = 0.01
    walking_weight: float = 0.7
    running_weight: float = 1.0
    gamma: float = 1.0
    running_pace_ceiling_s_per_km: float = 600.0
    abandonment_floor: float = 1.0


def classify_activity(
    distance_m: float, moving_time_s: float, tuning: InfluenceTuning
) -> ActivityKind:
    """Classify pace without awarding an extra reward for speed.

    A run is classified from a plausible moving pace only.  Invalid/zero time
    falls back to walking, which prevents malformed samples from gaining an
    accidental running multiplier.
    """

    if distance_m <= 0 or moving_time_s <= 0:
        return "walk"
    pace_s_per_km = moving_time_s * 1000 / distance_m
    return "run" if pace_s_per_km <= tuning.running_pace_ceiling_s_per_km else "walk"


def effort_for_segment(
    *,
    distance_m: float,
    moving_time_s: float,
    activity: ActivityKind,
    tuning: InfluenceTuning,
) -> float:
    """Convert a server-matched segment into movement effort."""

    if distance_m < 0 or moving_time_s < 0:
        raise ValueError("distance and moving time must be non-negative")
    activity_weight = tuning.running_weight if activity == "run" else tuning.walking_weight
    return activity_weight * (
        tuning.distance_weight * distance_m + tuning.moving_time_weight * moving_time_s
    )


def influence_for_effort(
    *, effort: float, current_share: float, tuning: InfluenceTuning
) -> float:
    """Apply diminishing returns while preserving some reward for every effort."""

    if effort < 0:
        raise ValueError("effort must be non-negative")
    bounded_share = min(max(current_share, 0.0), 1.0)
    return effort * (1.0 - bounded_share) ** tuning.gamma


def decay_active_influence(
    *, active_influence: float, elapsed_days: float, half_life_days: float
) -> float:
    """Exponentially decay an active value without a rolling-window cliff."""

    if active_influence < 0:
        raise ValueError("active influence must be non-negative")
    if elapsed_days < 0:
        raise ValueError("elapsed days must be non-negative")
    if half_life_days <= 0:
        raise ValueError("half-life must be positive")
    return active_influence * exp(-0.6931471805599453 * elapsed_days / half_life_days)


def active_share(*, contributor_active: float, total_active: float) -> float:
    if contributor_active <= 0 or total_active <= 0:
        return 0.0
    return contributor_active / total_active


def territory_is_abandoned(*, total_active: float, tuning: InfluenceTuning) -> bool:
    """Only total inactivity releases a territory; a close contest never does."""

    return total_active < tuning.abandonment_floor
