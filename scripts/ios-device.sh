#!/usr/bin/env bash
# Build, install and launch the Release app on a physical iPhone.
#
# `expo run:ios` cannot find devices on Xcode 26+: its devicectl JSON parsing
# fails ("Unexpected devicectl JSON version output"), so its device list comes
# back empty and no identifier matches. devicectl itself is fine — only Expo's
# reading of it is broken — so this drives xcodebuild and devicectl directly.
#
# Release embeds the JS bundle, so no Metro server is needed on the phone.
set -euo pipefail

DEVICE="${1:-}"
BUNDLE_ID="com.runprototype.app"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# devicectl exits non-zero transiently while a tunnel to the phone is active,
# which `set -o pipefail` would turn into "no device". Retry, and never let the
# detection itself abort the script.
if [ -z "$DEVICE" ]; then
  for _ in 1 2 3; do
    DEVICE=$(xcrun devicectl list devices 2>/dev/null \
      | awk 'NR>2 && $0 ~ /available/ {print $3; exit}' || true)
    [ -n "$DEVICE" ] && break
    sleep 2
  done
fi
if [ -z "$DEVICE" ]; then
  echo "No paired iPhone found. Connect it, unlock it, and trust this Mac." >&2
  exit 1
fi

echo "→ Building Release for $DEVICE"
xcodebuild -workspace "$ROOT/ios/run.xcworkspace" -scheme run \
  -configuration Release -destination "id=$DEVICE" \
  -derivedDataPath "$ROOT/ios/build/device-release" \
  -allowProvisioningUpdates build

APP="$ROOT/ios/build/device-release/Build/Products/Release-iphoneos/run.app"
test -f "$APP/main.jsbundle" || {
  echo "No embedded bundle — the app would need a Metro server." >&2
  exit 1
}

echo "→ Installing"
xcrun devicectl device install app --device "$DEVICE" "$APP"

echo "→ Launching"
# A first install on a new certificate needs the profile trusted on the phone:
# Settings → General → VPN & Device Management → trust the developer.
xcrun devicectl device process launch --device "$DEVICE" "$BUNDLE_ID" || {
  echo
  echo "Launch refused. If this is a new certificate, trust it on the phone:"
  echo "Settings → General → VPN & Device Management → Developer App → Trust"
  exit 1
}
