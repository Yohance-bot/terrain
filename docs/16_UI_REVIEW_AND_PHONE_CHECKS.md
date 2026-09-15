# TerraRun UI completion and app review — September 14, 2026

## This update

Continues the committed athlete/UI redesign (profile, training log, activity detail,
friends, duels, shoes, goals, settings, authentication and run preparation).

- Replaces Barlow with bundled Manrope regular/medium/semibold/bold. Uses warm cream
  surfaces, dark readable labels, and honey-to-yellow SVG icon gradients. The cyan
  GPS/street trail and territory ownership colours retain their meaning.
- Joins Start to the map's bottom dock. A tap starts a real run; developer accounts
  keep the long-press shortcut to virtual-run options. Map overlays clear the dock.
- Replaces the full-width attribution banner with compact OpenStreetMap credit and
  a one-tap panel linking OpenStreetMap, OpenFreeMap and Open-Meteo.
- Gives the main tabs short native transitions. Returning to Map uses the reversed
  pop animation so the map enters from the right. Reduce Motion disables these.
- Fixes avatar heading: the model's +Z front is rotated into travel direction,
  relative to map bearing, retaining the last reliable heading when stationary.
- Publishes avatar eye/target/up/heading as one shared snapshot. Removes repeated
  asynchronous camera reads and rejects a read if a newer gesture arrived. A GPS
  fix updates the avatar using the most recent camera, even without a camera event.
- Adds a local Expo/ActivityKit module and WidgetKit extension for active runs.
  Compact/minimal/expanded Dynamic Island and Lock Screen presentations are included.
  Elapsed time ticks through SwiftUI; distance and rolling pace update from the
  existing recorder, at most every five seconds. No additional GPS subscription,
  server push infrastructure, or map coordinates are sent to the widget.
- Handles Finish, stale GPS, interrupted-run recovery, miles/kilometres and virtual
  run labelling. Native activity calls are serialized and optional: their failure
  cannot prevent sample persistence or run completion.

The native folders are generated and git-ignored. The committed config plugin and
local module reproduce the extension with `npx expo prebuild --platform ios`, followed
by `pod install` in `ios`. Do not copy only JavaScript to an old native build.

## Verification and limits

The signed Release app was installed successfully on NOVA. It was left for the
user to launch and test manually. The embedded bundle is newer than all app source,
and code-signature verification passed for the app and its embedded extension.

- TypeScript and Expo lint pass.
- Avatar projection/heading, HUD/recorder, route timestamps, route smoothing,
  street matching, building geometry, ground borders, social/ghost playback,
  formatting and MapLibre style validation pass.
- Live Activity tests cover delayed start followed by Finish, update throttling,
  unit conversion, unsupported platforms and native failure recovery. The recorder
  integration test checks the final activity receives the drained GPS distance.
- All 152 backend tests pass against a dedicated local PostGIS database.
- Admin production build passes; lint reports four existing warnings in Test Lab
  React effects/ref usage. Its main JavaScript bundle is about 2.06 MB minified
  (546 KB gzip); it should be split before wider use.
- Read-only live checks: Render health returns 200 and OpenAPI lists seven athlete
  routes. This verifies deployment presence, not every authenticated production flow.
- Widget Swift type-check and the signed iPhone Release build pass. The app embeds
  its JavaScript and the signed TerraRunActivity extension.
- Simulator testing was stopped at the user's request. Visual appearance, navigation
  feel, Dynamic Island lifecycle and outdoor GPS/battery behaviour require phone testing.

## Honest assessment

Scores are engineering/product judgments of the current alpha, not user-research
results or a claim that the app is ready for a public release.

| Category | Score / 10 | Assessment |
| --- | --- | --- |
| Product and gameplay | 8 | Running, exploration, territory capture, ghosts and duels form a coherent core. Retention and balance still need real runners. |
| Visual design | 7, provisional | Shared typography, icons, cards and clearer hierarchy improve consistency. The crowded map, procedural architecture and effects need phone review. |
| Usability | 6.5, provisional | Recovery/error states, meaningful run history and shared controls help. Permissions, onboarding, long labels and mid-run interactions need end-to-end manual checks. |
| Code and maintainability | 6.5 | Useful separation of recorder, presentation, server authority and reusable UI. Large screen/service files and overlapping local/network state make continued changes expensive. |
| Core data and reliability | 7.5 | Durable raw samples, queued submission, idempotency, server validation and a passing backend suite are strong foundations. Field GPS loss/recovery remains unproven by desktop tests. |
| Admin and operations | 6.5 | Broad controls, simulation, account tools and operational endpoints exist. Large bundle, lint warnings and limited automated browser coverage reduce confidence. |
| Security and privacy | 6, limited review | Server sessions, password hashing and scoped friend/account reads exist. Native auth tokens currently live in SQLite rather than platform secure storage; broader security review and abuse testing are still needed. |
| Performance and battery | Unrated | No honest number without an outdoor 45–60 minute run. Geometry benchmarks are not FPS or battery measurements. |
| Release readiness | 5.5 | Cloud endpoints and a standalone build path exist. No repository CI was found; Android and store distribution are not validated here. Personal-team iOS provisioning still needs periodic renewal. |

**Overall: approximately 6.5/10 as an alpha.** The core is substantial. The largest
remaining gain is reliable, tested behaviour on a real run, followed by simplifying
the implementation and reducing map/UI clutter—not increasing the feature count.

The avatar still uses a separate Filament view with no shared depth buffer with
MapLibre. These fixes address heading and stale camera updates; they do not make
buildings correctly occlude the character or prove zero latency during every gesture.

## Phone checklist

1. Open the Release app with Metro stopped. Check Sign-in, Friends, Profile and
   Settings for the new font and yellow icons. Change system text size and check
   labels and buttons remain usable.
2. From Friends and Profile, tap Map. It should enter from the left without
   accumulating extra tabs. Repeat quickly and with Reduce Motion enabled.
3. Confirm Start is attached to the bottom dock, credits do not cover the street,
   and tapping credits opens all provider links. Tap Start for a real run; on a
   developer account, long-press it for virtual-run options.
4. Pan, rotate, pinch and recenter the map while stationary, then while walking or
   using the joystick. The avatar should remain on its marker and face travel
   direction. Test a turn through north and a U-turn. Record any remaining drift.
5. Start a run, go to the Home Screen and long-press Dynamic Island. Check compact
   distance, expanded distance/pace/timer and the Lock Screen view. Tap it to return.
   If absent, check iOS allows Live Activities for this app. Supported iPhones show
   Dynamic Island; other supported iOS devices show the Lock Screen presentation.
6. With background location permitted, walk with the screen locked. Elapsed time
   should tick and distance should update with GPS. No fresh fix for 25 seconds
   changes the Lock Screen status to waiting for GPS and hides stale pace.
7. Finish the run. Dynamic Island should close; the finished summary may remain on
   the Lock Screen for up to a minute. Verify a second run does not retain old metrics.
8. Check miles and kilometres, virtual-run labelling, offline submission/reconnect,
   and reopening after an interrupted run. Force-quit cannot keep recording; on next
   launch interrupted-run recovery clears any remaining activity.
9. Run 45–60 minutes outdoors. Note starting/ending battery %, device temperature,
   GPS gaps and visible frame drops, comparing full effects with battery saver.
