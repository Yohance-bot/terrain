# TerraRun Android preview — 15 September 2026

This is a tester build, not a field-validated public release. No emulator/simulator was used. Physical-device visual, GPS and battery testing belongs to the tester checklist below.

## Included

- Manrope typography, yellow gradient icons/initials, attached Start dock and less bottom whitespace. Tab transitions follow Map → Friends → Profile order; returning to Map reveals it from the left.
- Sun/moon map-layer button follows the map's actual lighting state. The old environment footer is removed. Compact, tappable provider attribution remains.
- Current territory owners have native 3D flagpoles and collision-managed name labels. Labels come from account display names, with anonymous Runner IDs only for legacy unlinked devices. Fixed territories and captured loop areas both expose interior label points from PostGIS.
- One Filament scene shares the bundled runner GLB between the player, active ghost and nearby friends whose locations the server has authorized. Eight instances maximum; active ghost gets priority, then nearest friends within 1.5 km of the player. Friends expire after 90 seconds without an update. Distant/economy-mode runners use labelled markers; available ghost starts remain waypoint markers until raced. No extra GPS watch is added for these visuals.
- Ghost heading comes from its recorded path. Each model receives an absolute transform instead of accumulating transforms on rerenders. Ground rings and names distinguish friend/ghost runners.
- Outside-territory loop capture was already implemented server-side. The response and summary now explicitly confirm the new area, even with zero named territory segments. The regression test proves capture and idempotent resubmission.
- Android shoe menus use scrollable sheets; native Android alerts support at most three buttons.
- Android launcher name is TerraRun. Backup of private app storage is disabled and unused storage/overlay permissions are blocked. Runtime location permission is still requested normally.

## Loop rules

A valid tracked run must cover at least 350 metres, finish within 45 metres of its start, and enclose at least 1,200 square metres. The server validates the run before applying a claim. Runs under review do not get confirmed-claim feedback. These rules do not require the loop to intersect predefined territories. This does not add continuous mid-run sub-loop capture: confirmation follows submission of the completed run.

## Rebuild

Java 21, Android SDK 36/build-tools 36, NDKs requested by the native dependencies, and CMake are needed on the build machine. None are needed by testers.

1. `npm ci`
2. `npx expo prebuild --platform android --no-install`
3. Configure `ANDROID_HOME` and the generated `android/local.properties` if needed.
4. `scripts/android-apk.sh`

The release key lives outside this repository at `~/.config/terrarun/android-release.jks`; its password is in the adjacent private `.password` file. Back up these private files securely: future APK updates must use the same key. They are not embedded in the app or committed. The script also accepts `TERRARUN_KEYSTORE` and `TERRARUN_STORE_PASSWORD` for another build host. Increment `expo.android.versionCode` before a new tester release.

The APK embeds JavaScript, fonts, map style and runner model, and explicitly uses `https://run-backend-ngyo.onrender.com`. It does not need Metro, a USB connection or the developer's laptop. API actions and fresh map tiles need internet. A Render free-tier cold start can still delay the first login; authentication already allows 90 seconds.

## Verification and remaining limits

- 154 backend tests pass against the isolated local PostGIS database `terrarun_ui_audit_20260914`, including outside-territory capture and map leader metadata. Production data was not used for tests.
- TypeScript, ESLint and HUD/recorder, avatar math/population, ghost playback, Live Activity, format, road border, GPS timestamp and map-style suites pass.
- No new database migration is required. The updated backend must be deployed for leader names and outside-loop confirmation metadata; older clients remain compatible.
- Filament overlays MapLibre without a shared depth buffer. Buildings cannot correctly hide these avatars. This is a renderer limitation, not something desktop tests can validate away.
- Friend positions are polled, not streamed. The app must have a valid local map position to place its shared avatar scene. Full-effects frame rate, heat and battery life remain unmeasured on Android.
- iOS Dynamic Island is implemented separately; Android uses the location foreground service. APK installation does not update the iPhone app.
- Existing gaps from the broader review remain: native auth credentials are stored in local SQLite rather than secure storage, admin bundle splitting/React warnings, and no automated physical-device end-to-end coverage.

## Manual tester checklist

1. Install the APK, allow installation from the sharing app if Android asks, and open it with the developer laptop disconnected. Sign up/sign in; also test Google returning to `run://auth/callback`.
2. Check Map/Friends/Profile transitions both ways, large text, bottom gesture/three-button navigation, yellow initials and sun/moon layer control.
3. Grant precise foreground and background location. Start a run, lock the screen, then check distance and the ongoing Android service indicator. Denying background access should explain that TerraRun must stay open.
4. Walk a qualifying loop outside any named territory; finish and submit. Check the new area on the map and the claimed-area summary. Repeat submission/offline reconnect should not duplicate it.
5. Use two friends: enable sharing, see the friend's runner/name, move/turn, stop sharing and confirm disappearance after the next successful refresh. Disconnect data and confirm stale locations expire.
6. Race a saved ghost: it should use the same runner model, face its route and switch to idle when finished. Pan/rotate/recenter; compare against the ground ring.
7. Check leader names against territory details after ownership changes. Zoom out to check labels and territory readability.
8. Add at least four pairs of shoes and select/manage every pair. Test empty, loading, offline and retry states.
9. Complete a 45–60 minute outdoor run. Record battery change, heat, location gaps and frame drops with full effects and battery saver. Force-quitting stops recording; reopening should recover the interrupted run honestly.
