"""Run metrics on synthetic tracks, where the right answer is known exactly."""

from math import sin

import pytest

from app.services.athlete_metrics import (
    BEST_EFFORT_DISTANCES,
    TrackPoint,
    calories,
    compute_metrics,
    haversine_m,
)

LAT0, LON0 = 12.93, 77.58
DEG_PER_M = 1 / haversine_m(0, 0, 1, 0)  # metres per degree of latitude, inverted


def track(legs, *, altitude=None, sample_every_s=1.0):
    """Due north through `legs` of (seconds, metres/second) at 1 Hz."""
    points, t, north = [], 0.0, 0.0

    def point():
        alt = altitude(north) if altitude else None
        return TrackPoint(t=t, lat=LAT0 + north * DEG_PER_M, lon=LON0, altitude_m=alt)

    points.append(point())
    for seconds, speed in legs:
        for _ in range(int(seconds / sample_every_s)):
            t += sample_every_s
            north += speed * sample_every_s
            points.append(point())
    return points


def test_steady_run_splits_and_best_efforts():
    # 5.2 km at exactly 5:00 /km.
    points = track([(1560, 1000 / 300)])
    metrics = compute_metrics(points, elapsed_s=1560)

    assert metrics.moving_s == pytest.approx(1560, abs=2)
    assert [s.distance_m for s in metrics.splits] == [1000.0] * 5 + [pytest.approx(200, abs=1)]
    for split in metrics.splits[:5]:
        assert split.moving_s == pytest.approx(300, abs=1)
    assert metrics.best_efforts[400] == pytest.approx(120, abs=1)
    assert metrics.best_efforts[1000] == pytest.approx(300, abs=1)
    assert metrics.best_efforts[1609] == pytest.approx(482.7, abs=1)
    assert metrics.best_efforts[5000] == pytest.approx(1500, abs=1)
    assert 10000 not in metrics.best_efforts
    assert metrics.elevation_gain_m is None
    assert len(metrics.pace_series) > 100
    assert all(p == pytest.approx(300, abs=2) for _, p in metrics.pace_series)


def test_standing_still_is_not_moving_time():
    # 2 km, a two minute stop at a crossing, then 1 km more.
    points = track([(600, 1000 / 300), (120, 0.0), (300, 1000 / 300)])
    metrics = compute_metrics(points, elapsed_s=1020)

    assert metrics.moving_s == pytest.approx(900, abs=12)
    # The stop falls between splits and must not slow the third kilometre.
    assert metrics.splits[2].moving_s == pytest.approx(300, abs=12)


def test_a_single_long_gap_at_a_standstill_is_not_moving():
    # Ingest collapses duplicate fixes, so a stop can arrive as one 2 minute gap.
    before = track([(600, 1000 / 300)])
    last = before[-1]
    resumed = [
        TrackPoint(t=p.t + 720, lat=p.lat - LAT0 + last.lat, lon=p.lon)
        for p in track([(300, 1000 / 300)])[1:]
    ]
    gap = TrackPoint(t=last.t + 120, lat=last.lat, lon=last.lon)
    metrics = compute_metrics(before + [gap] + resumed, elapsed_s=1020)
    assert metrics.moving_s == pytest.approx(900, abs=12)


def test_gps_wander_while_stopped_is_not_counted():
    points = track([(300, 1000 / 300)])
    last = points[-1]
    for i in range(1, 121):
        wobble = 0.8 * sin(i * 1.7) * DEG_PER_M
        points.append(TrackPoint(t=last.t + i, lat=last.lat + wobble, lon=last.lon + wobble))
    metrics = compute_metrics(points, elapsed_s=420)
    assert metrics.moving_s <= 300 + 15


def test_elevation_counts_the_climb_not_the_noise():
    def altitude(north):
        noise = 1.2 * sin(north / 7)
        climb = min(max(north - 2000, 0), 500) / 500 * 20
        return 900 + climb + noise

    points = track([(900, 1000 / 300)], altitude=altitude)
    metrics = compute_metrics(points, elapsed_s=900)

    assert metrics.elevation_gain_m == pytest.approx(20, abs=3)
    assert metrics.elevation_loss_m <= 3
    assert metrics.splits[2].elevation_delta_m == pytest.approx(20, abs=3)
    assert len(metrics.elevation_series) == 121


def test_distance_follows_the_servers_measurement():
    points = track([(300, 1000 / 300)])  # 1 km by haversine
    metrics = compute_metrics(points, distance_m=1100, elapsed_s=300)
    assert [s.distance_m for s in metrics.splits] == [1000.0, pytest.approx(100, abs=1)]
    assert 1000 in metrics.best_efforts


def test_no_clock_means_no_time_based_numbers():
    points = [TrackPoint(t=0, lat=LAT0 + i * 10 * DEG_PER_M, lon=LON0) for i in range(200)]
    metrics = compute_metrics(points, elapsed_s=640)
    assert metrics.moving_s == 640
    assert metrics.splits == [] and metrics.best_efforts == {}


def test_efforts_only_up_to_the_run_length():
    points = track([(3000, 1000 / 300)])  # 10 km
    metrics = compute_metrics(points, elapsed_s=3000)
    assert set(metrics.best_efforts) == {d for d in BEST_EFFORT_DISTANCES if d <= 10000}


def test_calories_need_a_weight():
    assert calories(10000, 70) == 725
    assert calories(10000, None) is None
