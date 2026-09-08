# TerraRun HUD audit — 2026-09-07

Recorded before feature implementation. Scope: mobile routes, recorder, geometry,
SQLite, API/cache contracts, MapLibre style, backend services/routes/models and
migrations, admin frontend, pipeline/publishing boundaries, scripts and design
documents. Build-time GIS internals were inspected structurally and at their
mobile/publishing contracts; this is not an exhaustive GIS correctness or security
audit. Generated datasets were inspected as data, not edited. `addon.py` is an
existing untracked user file and is excluded from changes.

## Findings and implementation decisions

| Priority | Existing conflict / evidence | Impact and disposition |
| --- | --- | --- |
| High | `app/index.tsx` uses `useRecorder()` without selectors and owns a one-second elapsed timer. `gpsClean.ts:liveCleanPath` recreates every coordinate, even for rejected fixes. | Unrelated updates traverse a 769-line map component and replay full-route work. Isolate telemetry timer, stabilize rejected paths, memoize map and budget visual snapshots. |
| High | Expo uses BestForNavigation/zero distance interval while MapLibre UserLocation and tracking run independently. | Battery cost and two disagreeing positions. Use accepted recorder fixes for the live marker, exploration and camera; native location only while browsing. Keep durable GPS independent of visual LOD. |
| High | Cleaner rejects jumps over 80 m relative to its last accepted point forever; no time/gap model, finite-coordinate validation or chronological gate. | Reacquisition can freeze runner and fog, or invalid fixes poison native geometry. Track time, recover after gaps, break rendered segments and never award distance across gaps. |
| High | Map mount calls `recoverInterruptedRuns`, which changes all recording/submitting rows. Active metadata/task can outlive React. Start permission/DB errors occur outside catch; stop changes status before queued fixes update live state. | Remount/start/stop can diverge durable and displayed run state. Guard recovery per process and while live; stop obsolete task before cold recovery; drain accepted fixes on stop. Cold restart saves an interrupted run, not seamless run resumption. |
| High | `detectLoopCandidate` scans the full path; loop dedupe key includes changing area. `justCapturedTerritoryIds` is passed only by the summary, not the live map; `onStop` navigates immediately. | Repeated closure events and invisible claim celebration. Use one closure cue per run and a separate confirmed event keyed by server run ID; display confirmed burst before summary navigation. |
| High | Backend only accepts finished-run submissions; it derives influence/loop ownership from raw GPS. Client uses a tighter 25 m gate + EMA, server 50 m. | Instant **authoritative** live claims do not exist. Immediate effect must say “Loop closed · pending validation”; “Territory claimed” requires applied server response. Do not change competitive rules in a rendering overhaul. |
| Medium | Existing glow is 18–35 px with blur 14; traversal creates separate two-point segments and grid dedupe can erase short segments. | Overdraw and misleading trail. Replace with connected, gap-aware gradient paths, bounded geometry and zoom/economy LOD. No continuous JS particle emitter. |
| Medium | Base style has 114 layers; runtime fills anchor before the first road while borders are appended above labels. Source visibility is set after loading map, and comments warn of native style-swap crashes. | Theme changes must not repeatedly replace the style JSON. Install stable theme-aware layers once, animate paint transitions; define fog/effect/player ordering. |
| Medium | Territory palette rebuild is pairwise adjacency; two identical 5.2 MB bundled datasets exist. Offline fallback is selected independently in screen/map. | Keep static topology memoized, derive shared borders once, use the same runtime dataset. No pipeline republish or dataset migration for HUD work. |
| Medium | “Recenter on your location” actually centers Jayanagar; no gesture ownership for camera. | One camera controller, follow opt-out on pan, actual fix recenter, shortest-angle bearing smoothing and low-speed heading lock. |
| Medium | Fog, weather, split event state, waypoint source and contested feed do not exist. | Add local exploration with versioned persistence; current-run simulation must not persist exploration. Mock contested borders only behind developer/simulation gating, explicitly labelled. Weather uses a coarse current fix and cache with time-only fallback. |
| Medium | Ownership refresh is only launch/manual/submission; queue timer is not foreground-gated. | Do not label snapshots as live multiplayer. Gate nonessential timers by app foreground and screen focus. Future push feed can supply explicit contested line geometry. |
| Medium | Unit/notification preferences exist but live stats ignore them. Pace is whole-run average and can format `5:60`. Bottom overlays obscure attribution/recenter. | Rolling timestamp-based pace, stale fix indication, unit-aware splits; keep attribution above bottom controls. |
| Medium | Design docs and recorder comments forbid territory feedback mid-run. READMEs/API description claim distance-only ownership/no accounts despite influence and account code. | This user brief supersedes old live-feedback restriction. Backend semantics stay authoritative; document updated HUD contract. |
| Medium | No robot/model asset or renderer exists in this checkout; only circle marker layers. | Preserve marker slot and use accepted recorder coordinates. A missing 3D robot cannot be preserved or profiled from this repository. |
| Follow-up | Local simulation emits non-mock fixes and defaults to tracked submissions; local identity APIs are explicitly POC-gated. | Simulation is not evidence for production anti-cheat or competitive validity. Do not enable developer backend switches publicly. |
| Follow-up | Backend loop SQL constructs a polygon without explicit validity repair; starts/ends must close at run origin; multiple loops are not represented. | Client previews may differ from rejection/server matching, especially self-crossings. Keep previews provisional; multi-loop game rules need a separate backend change. |
| Follow-up | Admin map uses `@ts-nocheck`, independent Carto style and 10-second ownership polling. Existing JS regression scripts reimplement logic rather than import it. | Admin is not a mobile styling dependency. Add tests that execute actual HUD modules; passing copied tests alone is not sufficient evidence. |
| Follow-up | Privacy retention exists server-side but READMEs say never prune; mobile SQLite has no trace retention policy. | Exploration is new location history: scope per identity, store coarse cells locally, provide erase control and avoid sending it to server. |

Pipeline stages 01–13 are build-time operations, not run-loop dependencies. Their
approval gates, identity rules, CRS transformations and published geometry remain
unchanged. Backend influence/review/progression and admin pages do not need new
animation state. No new Supabase dependency is introduced (this repo uses FastAPI
and PostGIS directly).

## Baseline evidence

- `npm run typecheck`: passed.
- `npm run lint`: no errors; existing missing `onStart` dependency warning.
- `npm run map-style:validate`: passed, 114 layers / 50 styled road layers.
- `npm run test:run-samples`: passed (copied-function test, limited confidence).
- `xcrun xctrace list devices`: physical iPhone NOVA offline. No physical-device
  FPS, energy, thermal or 45-minute battery measurements can be claimed.

Read before implementation: [Expo 54 reference](https://docs.expo.dev/versions/v54.0.0/),
[Location](https://docs.expo.dev/versions/v54.0.0/sdk/location/),
[Haptics](https://docs.expo.dev/versions/v54.0.0/sdk/haptics/).
MapLibre APIs are checked against installed 11.3.6 source/types.

## Rendering budget and device acceptance

Cheap: one-second metric text, event-only native-driver scale/opacity pulses,
one crisp route line, static theme paint. Moderate: two restrained glow passes,
coarse exploration mask updates, low-rate contested paint transitions. Expensive:
full-style reloads, per-frame GeoJSON/JS particles, large blur/fill overdraw,
continuous heading sensors, high-pitch camera plus 3D buildings and uncapped GPS.

Target: 30 map FPS during runs, 1 Hz route/fog/camera snapshots (0.5 Hz economy),
bounded route geometry, no animation timers offscreen/background, weather at most
every 15 minutes, time palette at minute cadence, event particles only. Retain
raw GPS fidelity separately. Prefer High accuracy for fitness; validate the change
against recorded reference traces before treating distance as calibrated.

Physical test, Release build: same 45-minute route and screen brightness for
baseline/economy/full HUD, stable battery start range, no charging. Record battery
start/end, thermal warnings, Energy Log/Android power traces, native frame times,
JS stalls, route point/drop counts, GPS interruption and permission mode. Include
10 minutes screen locked, urban canyon reacquisition, stationary minutes, fast
turns, kilometre split, closure, background/foreground, pan/recenter and offline
submission. Compare median/p95 frame time, >50 ms stalls and % battery/hour.
Targets are hypotheses until measured: sustained map >=28 FPS at a 30 FPS cap,
no repeated >100 ms JS stalls, no cue backlog on resume, no invented gap distance,
no fog reveal across rejected jumps and no continuing camera motion after pan.

If expensive: economy mode first; reduce halo, pitch and source cadence before
changing acquisition fidelity. Never interpret JS timer drift as native FPS.
