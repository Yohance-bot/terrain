# Athlete profile

The profile, training log and run details show everything a running app
typically shows that TerraRun's own data can support. This records what that is,
where each number comes from, and what is deliberately absent.

## Where the numbers come from

Every run already arrives with timestamped GPS samples. From those, once per run:

| Number | How |
|---|---|
| Distance | Server-measured route length (PostGIS), as before |
| Elapsed time | `ended_at − started_at` |
| Moving time | Time spent covering at least 1 m/s of net ground over a 10 s window — standing at a crossing doesn't count, walking does |
| Pace | Moving time ÷ distance |
| Splits | Moving time per kilometre, interpolated between fixes |
| Best efforts | Fastest elapsed stretch of the run at 400 m, ½ mi, 1K, 1 mi, 2 mi, 5K, 10K, 15K, 10 mi, 20K, half, 30K, marathon |
| Elevation gain / loss | Smoothed phone altitude, counting a change only once it holds past 3 m |
| Pace and elevation charts | 120 points along the run, pace over a 200 m window |

These are computed at ingest (`services/athlete_metrics.py`, pure and tested on
synthetic tracks) and cached in `run_metrics` / `run_best_efforts`. Runs
recorded before this existed get them on first read. Changing a definition
means bumping `METRICS_VERSION`; cached rows rebuild themselves.

Aggregates are computed at read time, in the timezone the phone sends, so a run
at 01:00 on Monday counts in the week the runner lived it:

- This week, this month, year to date, all time: runs, distance, moving time, climb
- Weekly (12) and monthly (12) distance
- Last 4 weeks, per week
- Weekly streak — current, best, since when (a week in progress hasn't been missed yet)
- Personal records per distance, longest run, biggest climb
- Weekly goal progress (distance, time, or runs)
- Territories held and captured

## What the athlete adds

- **Title and notes** per run (`run_annotations`)
- **Shoes** with mileage; new runs wear the default pair (`shoes`)
- **Weekly goal** (`weekly_goals`)
- **Weight**, only to estimate calories (`athlete_settings`)
- **Weather** at the start of each run, as the phone already read it for map lighting

## What friends see

`/social/accounts/{id}/profile`, accepted friends only: totals, weekly chart,
streak, records, recent runs with titles. Never routes, notes or shoes.

## Not shown, and why

| Common in running apps | Why not here |
|---|---|
| Heart rate, zones, relative effort | Needs a heart-rate sensor |
| Cadence, power | Needs a foot pod or watch |
| Elevation on older runs | Altitude wasn't recorded before this change |
| Splits per mile | Splits are per kilometre; per-mile would need recomputing from samples |
| Kudos, comments, photos, clubs | Social features the app doesn't have |
