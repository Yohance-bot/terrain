"""Read-only, device-scoped progression derived from applied tracked activity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import floor

from fastapi import HTTPException
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DeviceProfile, InfluenceGrant, Run, Territory
from app.schemas import (
    ExperienceSummary,
    HomeSelectionMetadata,
    HomeTerritorySummary,
    LegacySummary,
    PrestigeSummary,
    ProfileSummary,
)


@dataclass(frozen=True)
class ProgressionTotals:
    applied_tracked_runs: int
    applied_tracked_distance_m: float
    territories_contributed: int
    lifetime_influence: float
    active_influence: float


def _applied_tracked_run_filter(device_id: object) -> tuple[object, ...]:
    return (
        Run.device_id == device_id,
        Run.source == "tracked",
        Run.status == "applied",
    )


def progression_totals(session: Session, device_id: object) -> ProgressionTotals:
    """Aggregate only runs that still qualify as applied, tracked activity."""

    run_count, distance_m = session.execute(
        select(
            func.count(Run.id),
            func.coalesce(func.sum(Run.distance_m), 0),
        ).where(*_applied_tracked_run_filter(device_id))
    ).one()
    territory_count, lifetime, active = session.execute(
        select(
            func.count(distinct(InfluenceGrant.territory_id)),
            func.coalesce(func.sum(InfluenceGrant.legacy_influence), 0),
            func.coalesce(func.sum(InfluenceGrant.active_influence), 0),
        )
        .join(Run, Run.id == InfluenceGrant.run_id)
        .where(
            InfluenceGrant.device_id == device_id,
            *_applied_tracked_run_filter(device_id),
        )
    ).one()
    return ProgressionTotals(
        applied_tracked_runs=int(run_count or 0),
        applied_tracked_distance_m=float(distance_m or 0),
        territories_contributed=int(territory_count or 0),
        lifetime_influence=float(lifetime or 0),
        active_influence=float(active or 0),
    )


def _experience(totals: ProgressionTotals) -> ExperienceSummary:
    total_xp = floor(totals.applied_tracked_distance_m / settings.xp_meters_per_point)
    level_offset, xp_into_level = divmod(total_xp, settings.xp_per_level)
    return ExperienceSummary(
        applied_tracked_runs=totals.applied_tracked_runs,
        applied_tracked_distance_m=round(totals.applied_tracked_distance_m, 2),
        total_xp=total_xp,
        level=level_offset + 1,
        xp_into_level=xp_into_level,
        xp_to_next_level=settings.xp_per_level - xp_into_level,
        meters_per_xp=settings.xp_meters_per_point,
        xp_per_level=settings.xp_per_level,
    )


def _legacy(totals: ProgressionTotals) -> LegacySummary:
    return LegacySummary(
        applied_tracked_runs=totals.applied_tracked_runs,
        territories_contributed=totals.territories_contributed,
        contributed_distance_m=round(totals.applied_tracked_distance_m, 2),
        lifetime_influence=round(totals.lifetime_influence, 4),
        active_influence=round(totals.active_influence, 4),
    )


def _prestige(totals: ProgressionTotals) -> PrestigeSummary:
    legacy_component = totals.lifetime_influence * settings.prestige_legacy_weight
    active_component = totals.active_influence * settings.prestige_active_weight
    consistency_component = totals.applied_tracked_runs * settings.prestige_run_weight
    return PrestigeSummary(
        score=round(legacy_component + active_component + consistency_component, 4),
        legacy_component=round(legacy_component, 4),
        active_component=round(active_component, 4),
        consistency_component=round(consistency_component, 4),
        legacy_weight=settings.prestige_legacy_weight,
        active_weight=settings.prestige_active_weight,
        run_weight=settings.prestige_run_weight,
    )


def profile_summary(session: Session, device_id: object) -> ProfileSummary:
    profile = session.get(DeviceProfile, device_id)
    home = None
    if profile is not None and profile.home_territory_id is not None:
        territory = session.get(Territory, profile.home_territory_id)
        if territory is not None:
            home = HomeTerritorySummary(
                territory_id=territory.id,
                slug=territory.slug,
                name=territory.name,
                selected_at=profile.home_selected_at,
                change_available_at=profile.home_change_available_at,
                metadata=HomeSelectionMetadata(
                    source=profile.home_selection_source or "onboarding",
                    note=profile.home_selection_note,
                ),
            )
    totals = progression_totals(session, device_id)
    return ProfileSummary(
        device_id=device_id,
        home=home,
        experience=_experience(totals),
        legacy=_legacy(totals),
        prestige=_prestige(totals),
    )


def set_home(
    session: Session,
    *,
    device_id: object,
    territory_id: object,
    metadata: HomeSelectionMetadata,
    now: datetime | None = None,
) -> None:
    """Set a personal Home without writing territory or influence state."""

    if session.get(Territory, territory_id) is None:
        raise HTTPException(status_code=404, detail="Territory not found")
    now = now or datetime.now(UTC)
    profile = session.get(DeviceProfile, device_id)
    if profile is None:
        profile = DeviceProfile(device_id=device_id)
        session.add(profile)
    if (
        profile.home_territory_id is not None
        and profile.home_territory_id != territory_id
        and profile.home_change_available_at is not None
        and now < profile.home_change_available_at
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Home can change after {profile.home_change_available_at.isoformat()}",
        )

    profile.home_territory_id = territory_id
    profile.home_selected_at = now
    profile.home_change_available_at = now + timedelta(days=settings.home_change_cooldown_days)
    profile.home_selection_source = metadata.source
    profile.home_selection_note = metadata.note
    session.flush()
