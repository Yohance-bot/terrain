#!/usr/bin/env bash
# Run the app in the iOS Simulator, where it can be screenshotted.
#
# A physical device can be built to and read from, but not looked at: there is
# no screenshot path for one here. Several rendering bugs in the map avatar were
# invisible until the app ran somewhere a picture could be taken of it.
#
# Screenshot with:
#   xcrun simctl io booted screenshot out.png
set -euo pipefail

DEVICE_NAME="${1:-iPhone 17}"
BUNDLE_ID="com.runprototype.app"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

UDID=$(xcrun simctl list devices available \
  | awk -v want="$DEVICE_NAME (" 'index($0, want) { match($0, /\(([0-9A-F-]{36})\)/, m); print m[1]; exit }' 2>/dev/null || true)
if [ -z "${UDID:-}" ]; then
  UDID=$(xcrun simctl list devices available | grep -F "$DEVICE_NAME (" | head -1 \
    | sed -E 's/.*\(([0-9A-F-]{36})\).*/\1/')
fi
[ -n "$UDID" ] || { echo "No simulator named '$DEVICE_NAME'." >&2; exit 1; }

echo "→ Booting $DEVICE_NAME"
xcrun simctl boot "$UDID" 2>/dev/null || true
open -a Simulator
until xcrun simctl list devices booted | grep -q "$UDID"; do sleep 2; done

echo "→ Building (Debug, for the simulator)"
xcodebuild -workspace "$ROOT/ios/run.xcworkspace" -scheme run \
  -configuration Debug -destination "id=$UDID" \
  -derivedDataPath "$ROOT/ios/build/sim" -allowProvisioningUpdates build

APP="$ROOT/ios/build/sim/Build/Products/Debug-iphonesimulator/run.app"
xcrun simctl install "$UDID" "$APP"

# Somewhere in the play area, so the map has a position to centre on.
xcrun simctl location "$UDID" set 12.925,77.5838

cat <<'NOTE'

→ Installed. A Debug build loads JS from Metro, so start it separately:
      npx expo start --dev-client

  Two things the simulator cannot do for you:
    - `simctl privacy grant location` does not suppress the location prompt;
      it still has to be tapped once per install.
    - Signing in needs a session. The app reads it from the `meta` table of
      Documents/SQLite/run-prototype.db inside the app container, as the keys
      `auth.token` and `auth.device`.
NOTE
