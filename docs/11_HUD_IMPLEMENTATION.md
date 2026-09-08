# TerraRun HUD implementation — 2026-09-08

Current road styling, rooftops, cyan curves and trail options are documented in
[Map world and trails](12_MAP_WORLD_AND_TRAILS.md). The notes below describe the
initial HUD implementation; the new map-world notes supersede its visual details.

See [the pre-implementation audit](10_HUD_AUDIT.md) for conflicts, baseline evidence
and remaining backend issues. Features were implemented in the requested order;
GPS/lifecycle foundations were repaired before adding the rendering layers.

Fog of war was removed at the user’s request. The full map is visible; exploration
tracking, persistence writes, mask rendering and exploration settings were removed.
Previously stored exploration metadata is unused. The audit records the original scope.

## Implemented behavior

| Feature | Behavior and integration |
| --- | --- |
| Telemetry | Safe-area top pill: rolling 20-second pace, elapsed time and distance. Isolated one-second clock, km/mi preferences, stale GPS pace shown as a dash. |
| Checkpoints | One cue per kilometre/mile crossed, light haptic and native pulse. `useCheckpoints(active, waypoints)` accepts named radius-based waypoints; no waypoint service exists yet. Missed background splits are consumed without a replay backlog. |
| Claim burst | Immediate loop closure gets a gold flood, sparks and pull-back labelled **pending validation**. A separate **Territory claimed** event requires an applied server result and owned segments; finishes wait for that celebration before navigating. Queued submissions can celebrate when confirmed on the active map. Per-run local receipt suppresses repeat claims. |
| Trail | Connected blue-to-mint gradient, restrained halo and crisp core. Each GPS section is simplified independently; signal gaps are never connected. Raw SQLite samples remain intact. |
| Contested borders | Exact shared edges between your and another owner's polygons pulse amber. Explicit line geometry can be supplied through `TerritoryMap.contestedBorders`. Ownership currently refreshes by existing API snapshots, not a multiplayer stream. Simulation uses a labelled mock adjacent border. |
| Lighting | Native paint transitions over the existing MapLibre style, local day/twilight/night plus weather tint. Open-Meteo receives coordinates rounded to 0.01 degrees, no account identity. Settings can disable weather. Cached sunrise/sunset drive daylight when available; offline fallback uses device-local 05:30/18:30 with twilight blending. |
| Camera | One camera writer follows accepted fixes with smoothed bearing/pitch/zoom. Stationary heading is held. Pan releases follow; recenter uses the actual fix. Claims temporarily pull back; gestures cancel restoration. Economy/reduced-motion use north-up, zero pitch. |

The checkout contains a circle player marker, no 3D robot renderer or model asset.
The accepted `RunFix` is the integration point for a restored avatar.

## Runtime boundaries and budgets

`useRecorder` owns durable GPS acquisition and accepted timestamped fixes.
`useVisualRun` publishes route/camera snapshots at 1 Hz, or 0.5 Hz in economy.
`TelemetryPill` subscribes to scalar metrics independently of the map. Transient
checkpoint/closure/claim events live in `useRunCues`; preferences have a separate lifetime. One cold-process recovery replaces destructive recovery
on every map remount. Cold restart recovers an interrupted run, not live resumption.

| Work | Full effects | Economy / lifecycle limits |
| --- | --- | --- |
| Map renderer | 30 FPS during a run | Native frame cap; actual FPS needs profiling |
| Route geometry | At most 1,536 vertices | 768 vertices; no glow/core extra passes |
| Glow | Blur 4, visible from zoom 14 | Removed in economy; core from zoom 15 |
| Contested border | 1.2-second native paint transitions, zoom 13+ | Static in economy/reduced motion; paused offscreen/background |
| Event effects | Native-driver opacity/transforms, 12 sparks per claim | No permanent particle emitter; no sparks in economy; reduced motion removes expanding rings/sparks |
| Lighting | Minute palette updates, 5-second paint transitions | No full style reload; no transition in reduced motion |
| Weather | At most every 15 minutes, 6-second request timeout, 90-minute expiry | No requests during simulation/offscreen/background; time-only fallback |
| GPS | Expo High accuracy, 1-second requested interval, 1 m distance interval | Background may batch at 5 seconds; OS determines actual delivery cadence |

Paint ordering is explicit, using five transparent anchors in the bundled style:
base territories → contested border → trail → event cues → player. Stable
anchors preserve gameplay effect order during asynchronous native source insertion.
Base roads and labels remain fully visible beneath the gameplay effects.
The validator checks anchor presence and order. Keep these anchors when retuning
or replacing the base style.

## Validation and limitations

- TypeScript, Expo lint, style validator, timestamp regression and production-module
  HUD tests pass. The HUD suite executes actual TypeScript modules with mocked
  native/persistence boundaries; it covers pace, splits/waypoints, claim authority,
  shared edges, lighting, bearing, geometry budgets and recorder
  recovery, chronology, traffic-light pauses, signal gaps and stop queue draining.
- Desktop synthetic 90-minute/5,400-point route: approximately 10 ms trail build,
  4 ms total exploration ingestion and 0.2 ms mask generation (47 rectangles).
  These are CPU smoke measurements on this Mac, not device frame or battery data.
- iPhone 17 iOS simulator review used an existing compatible native Debug binary
  and the updated JavaScript in an isolated temporary preview. A localhost fixture
  served mock account/map data and rejected submissions; no test runs were sent to
  the real backend. Telemetry, exploration, trail, shared-border layering, camera
  follow and HUD spacing were inspected. Temporary preview-only event controls also
  verified the checkpoint banner/pulse and the distinct gold claim flood, ring,
  sparks and pull-back. Those controls were removed after review; these were
  synthetic presentation tests, not server-confirmed captures. Simulator haptics
  are not physical evidence.
- A fresh native iOS build was attempted but failed during MapLibre extraction
  because disk space was exhausted. No new native dependency was added. Android
  and a fresh native Release build remain unverified.
- Physical iPhone NOVA was offline. The 45-minute energy, thermal, GPS accuracy and
  real-motion camera audit remains pending; follow the protocol in the audit.
  This implementation must not be called battery-calibrated or device-tuned yet.
- Multi-loop/self-intersecting claim semantics, production simulation/anti-cheat,
  backend/client matching differences and raw trace retention remain follow-ups
  listed in the audit. Authoritative ownership still occurs after run submission.

Optional development diagnostics: set `EXPO_PUBLIC_HUD_DIAGNOSTICS=true` and restart
Metro. Ten-second logs contain rendered callback counts, maximum JS timer drift,
accepted/rejected fixes and route size, without coordinates. Frame callbacks add
overhead and are absent in production. Use Instruments/Android system profiling
for native frame times and energy; JS drift is not an FPS measurement.
