# Android performance pass

Scope: the Android UI/rendering path. GPS sampling, persisted routes, loop validation, accounts, network timeouts and server behavior are unchanged. iOS retains its existing rendering settings, geometry budgets and scene lifecycle.

## Confirmed avoidable work

- The runner callback wrote eight root transforms every display frame, including seven empty slots in the common solo case. Android now initializes those slots once and writes again only when visibility, position or heading changes. Animation still advances each frame; model roots and animated skeletons are separate.
- Leaving the map destroyed Filament's scene. Returning reloaded the asset/engine. Android now retains the scene, stops its scheduler while hidden, and resumes after a valid camera is placed. A render-thread guard also stops late surface callbacks, avoiding a background render loop after native surface recreation.
- Browsing could render MapLibre at 60 FPS alongside Filament, including behind another page. Android is capped at 30 FPS while visible and 1 FPS while hidden. iOS still uses its previous 60 FPS browsing/30 FPS recording settings. This is a cap, not a measured claim that every device achieves 30 FPS.
- Android's avatar overlay uses dynamic resolution (65–85% dimensions) and disables its shadow/refraction passes. The map, labels and interface remain full resolution. iOS receives none of these overrides.
- Rooftop generation analyzed every loaded building synchronously, up to 4,800 detail volumes. Android selects the nearest 360 footprints, caps generated detail at 1,400 polygons, and uses smaller distance bands for fine details. Base buildings, streets, roofs and territory geometry remain intact. Farther buildings have less generated decoration.
- Android geometry updates yield between batches of 24 buildings, run at six-second intervals, wait for the page transition initially, and cancel if a user gesture or screen change makes their result obsolete. No partial results are published. iOS keeps the original synchronous generation and cadence.

The Android Filament scheduler also had a callback-identity problem: removal used a new method-reference object rather than the posted callback. The Android-only patch keeps one callback per running epoch, removes that exact callback, and prevents stale in-flight frames from starting duplicate loops after resume. Its native callback runs outside the Java monitor to avoid lock inversion. The existing iOS native patch is unchanged.

## Verification

`npm run test:android-performance` executes the actual production renderer callback with a strict host-array stub that throws on out-of-range access. It verifies initialization, 60 unchanged frames, immediate heading updates, scheduler pause, and the unchanged iOS path. In the solo fixture, Android performs zero redundant root writes across those 60 frames (previously 480). It also checks geometry selection, the polygon cap and cancellation between batches.

`npm run test:android-scheduler` compiles the actual patched Java scheduler with Android/JNI boundaries stubbed. It checks 100 pause/resume cycles, exact callback removal, stale frames and pause/resume during a frame.

TypeScript, ESLint, HUD/recorder, avatar, social, Android accessibility roles, Live Activity and map style validation pass. The signed Android Release build succeeds; package/version, matching release certificate, bundled JavaScript, runner asset, fonts and cloud API URL were verified. These tests do not establish real-device FPS, memory use or battery consumption. No simulator was used.

## Manual comparison

The previous version-6 APK is retained in `artifacts/TerraRun-before-android-optimisation-v6.apk`. The optimized APK is `artifacts/TerraRun-android-optimised-v7.apk` (ARM64, matching the previous APK) and uses version code 7 and the same signing key, so it installs over the existing app without clearing account/run data.

On an affected Android phone, compare the same area and actions: launch; pan/rotate the map for 30 seconds; switch Map → Friends → Profile → Map ten times; start a run; lock/unlock; switch to classic marker and back; race a ghost; see a sharing friend. The runner should return after every transition, face travel direction, and disappear when sharing expires. Check that recording survives screen changes and the saved route still matches the walk.

If slowness remains, report the phone model, Android version, whether Battery Saver is on, and which action stalls. A physical-device trace is the next step; desktop geometry timings are not a substitute. Installing an older version code may require a downgrade workflow and can affect local data, so do not uninstall the new app merely to compare it with the backup.
