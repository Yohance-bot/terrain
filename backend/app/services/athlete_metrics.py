"""The numbers a runner reads after a run, derived from its own samples.

Pure functions over timestamped points: no database, no settings. That keeps
them testable on synthetic tracks and lets stored results be rebuilt whenever a
definition here changes, by bumping `METRICS_VERSION`.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from math import asin, cos, inf, radians, sin, sqrt

METRICS_VERSION = 1

# Standard best-effort distances in metres: 400 m, ½ mile, 1K, 1 mile, 2 mile,
# 5K, 10K, 15K, 10 mile, 20K, half marathon, 30K, marathon.
BEST_EFFORT_DISTANCES: tuple[int, ...] = (
    400,
    805,
    1000,
    1609,
    3219,
    5000,
    10000,
    15000,
    16093,
    20000,
    21097,
    30000,
    42195,
)

EARTH_RADIUS_M = 6_371_008.8

# Moving time is judged on net displacement over a short window, not on
# point-to-point path length. A phone standing still at a crossing wanders a
# metre or two every second; summed, that looks like a slow jog, but over ten
# seconds it goes nowhere. Walking pace (~1.3 m/s) still counts as moving.
MOVING_WINDOW_S = 10.0
STOPPED_SPEED_MPS = 1.0

# Altitude from a phone is noisy to a few metres. Smooth it, then only count a
# change once it has held past a threshold, or every wobble becomes "climbing".
ELEVATION_SMOOTHING_POINTS = 5
ELEVATION_THRESHOLD_M = 3.0

SPLIT_M = 1000.0
MIN_FINAL_SPLIT_M = 50.0
SERIES_POINTS = 120
PACE_WINDOW_M = 200.0

# Energy cost of running is close to 1 kcal per kg per km regardless of pace.
KCAL_PER_KG_KM = 1.036


@dataclass(frozen=True)
class TrackPoint:
    """One usable fix: seconds from the first fix, position, optional altitude."""

    t: float
    lat: float
    lon: float
    altitude_m: float | None = None


@dataclass(frozen=True)
class Split:
    index: int
    distance_m: float
    moving_s: float
    elevation_delta_m: float | None


@dataclass(frozen=True)
class RunMetricsResult:
    moving_s: int
    elevation_gain_m: float | None
    elevation_loss_m: float | None
    splits: list[Split]
    best_efforts: dict[int, float]
    pace_series: list[tuple[float, float]]
    elevation_series: list[tuple[float, float]]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def calories(distance_m: float, weight_kg: float | None) -> int | None:
    """An estimate only, and only when the athlete has told us their weight."""
    if weight_kg is None or distance_m <= 0:
        return None
    return round(weight_kg * (distance_m / 1000) * KCAL_PER_KG_KM)


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation over non-decreasing xs; the first crossing wins."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_left(xs, x)
    x0, x1 = xs[i - 1], xs[i]
    return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - x0) / (x1 - x0)


def _empty(elapsed_s: float | None) -> RunMetricsResult:
    return RunMetricsResult(
        moving_s=int(round(elapsed_s or 0)),
        elevation_gain_m=None,
        elevation_loss_m=None,
        splits=[],
        best_efforts={},
        pace_series=[],
        elevation_series=[],
    )


def _moving_time(points: list[TrackPoint], times: list[float]) -> list[float]:
    """Cumulative moving seconds at each point."""
    moving = [0.0]
    start = 0
    for i in range(1, len(points)):
        dt = times[i] - times[i - 1]
        while start < i - 1 and times[i] - times[start + 1] >= MOVING_WINDOW_S:
            start += 1
        span = times[i] - times[start]
        if dt <= 0 or span <= 0:
            moving.append(moving[-1])
            continue
        net = haversine_m(points[start].lat, points[start].lon, points[i].lat, points[i].lon)
        moving.append(moving[-1] + (dt if net / span >= STOPPED_SPEED_MPS else 0.0))
    return moving


def _elevation(points: list[TrackPoint]) -> list[float] | None:
    """Smoothed altitude per point, or None when too few fixes carried one."""
    raw = [p.altitude_m for p in points]
    known = sum(a is not None for a in raw)
    if known < 2 or known < len(raw) / 2:
        return None
    filled: list[float] = []
    last: float | None = next(a for a in raw if a is not None)
    for a in raw:
        last = a if a is not None else last
        filled.append(float(last))
    half = ELEVATION_SMOOTHING_POINTS // 2
    return [
        sum(filled[max(0, i - half) : i + half + 1]) / len(filled[max(0, i - half) : i + half + 1])
        for i in range(len(filled))
    ]


def compute_metrics(
    points: list[TrackPoint],
    *,
    distance_m: float | None = None,
    elapsed_s: float | None = None,
) -> RunMetricsResult:
    """Every derived number for one run.

    `distance_m` is the server's authoritative length; the cumulative distance
    here is scaled to it so splits and efforts agree with the headline figure.
    """
    if len(points) < 2:
        return _empty(elapsed_s)

    cum = [0.0]
    for a, b in zip(points, points[1:], strict=False):
        cum.append(cum[-1] + haversine_m(a.lat, a.lon, b.lat, b.lon))
    if distance_m and cum[-1] > 0:
        scale = distance_m / cum[-1]
        cum = [c * scale for c in cum]
    total = cum[-1]

    times: list[float] = []
    for p in points:
        times.append(max(p.t, times[-1]) if times else p.t)
    if times[-1] - times[0] <= 0:
        # No usable clock: the distance stands, but nothing time-based does.
        result = _empty(elapsed_s)
        return result

    moving = _moving_time(points, times)
    moving_s = moving[-1]
    if elapsed_s is not None:
        moving_s = min(moving_s, elapsed_s)

    smoothed = _elevation(points)
    gain = loss = None
    elevation_series: list[tuple[float, float]] = []
    if smoothed is not None:
        gain = loss = 0.0
        anchor = smoothed[0]
        for altitude in smoothed[1:]:
            change = altitude - anchor
            if change >= ELEVATION_THRESHOLD_M:
                gain += change
                anchor = altitude
            elif change <= -ELEVATION_THRESHOLD_M:
                loss -= change
                anchor = altitude
        gain, loss = round(gain, 1), round(loss, 1)

    def altitude_at(d: float) -> float | None:
        return _interp(cum, smoothed, d) if smoothed is not None else None

    splits: list[Split] = []
    index, previous_d, previous_moving = 1, 0.0, 0.0
    previous_alt = altitude_at(0.0)
    while index * SPLIT_M <= total + 1e-6:
        d = index * SPLIT_M
        at_moving = _interp(cum, moving, d)
        at_alt = altitude_at(d)
        splits.append(
            Split(
                index=index,
                distance_m=SPLIT_M,
                moving_s=round(at_moving - previous_moving, 1),
                elevation_delta_m=None if at_alt is None else round(at_alt - previous_alt, 1),
            )
        )
        index, previous_d, previous_moving, previous_alt = index + 1, d, at_moving, at_alt
    if total - previous_d >= MIN_FINAL_SPLIT_M:
        end_alt = altitude_at(total)
        splits.append(
            Split(
                index=index,
                distance_m=round(total - previous_d, 1),
                moving_s=round(moving[-1] - previous_moving, 1),
                elevation_delta_m=None if end_alt is None else round(end_alt - previous_alt, 1),
            )
        )

    best_efforts: dict[int, float] = {}
    for target_distance in BEST_EFFORT_DISTANCES:
        if target_distance > total + 1e-6:
            break
        best, j = inf, 0
        for i in range(len(cum)):
            target = cum[i] + target_distance
            if target > total + 1e-6:
                break
            while j < len(cum) and cum[j] < target - 1e-9:
                j += 1
            if j >= len(cum):
                break
            if j == 0 or cum[j] == cum[j - 1]:
                end_t = times[j]
            else:
                fraction = (target - cum[j - 1]) / (cum[j] - cum[j - 1])
                end_t = times[j - 1] + (times[j] - times[j - 1]) * fraction
            best = min(best, end_t - times[i])
        if 0 < best < inf:
            best_efforts[target_distance] = round(best, 1)

    pace_series: list[tuple[float, float]] = []
    if total >= PACE_WINDOW_M:
        half = PACE_WINDOW_M / 2
        for step in range(SERIES_POINTS + 1):
            x = total * step / SERIES_POINTS
            lo, hi = max(0.0, x - half), min(total, x + half)
            span = hi - lo
            moved = _interp(cum, moving, hi) - _interp(cum, moving, lo)
            if span < half or moved <= 0:
                continue
            pace_series.append((round(x, 1), round(moved / (span / 1000), 1)))
        if smoothed is not None:
            elevation_series = [
                (
                    round(total * s / SERIES_POINTS, 1),
                    round(_interp(cum, smoothed, total * s / SERIES_POINTS), 1),
                )
                for s in range(SERIES_POINTS + 1)
            ]

    return RunMetricsResult(
        moving_s=int(round(moving_s)),
        elevation_gain_m=gain,
        elevation_loss_m=loss,
        splits=splits,
        best_efforts=best_efforts,
        pace_series=pace_series,
        elevation_series=elevation_series,
    )
