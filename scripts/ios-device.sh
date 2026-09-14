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
find_device() {
  for _ in 1 2 3; do
    DEVICE=$(xcrun devicectl list devices 2>/dev/null \
      | awk 'NR>2 && $0 ~ /available/ {print $3; exit}' || true)
    [ -n "$DEVICE" ] && return
    sleep 2
  done
}
[ -z "$DEVICE" ] && find_device

echo "→ Building Release"
# Built for a generic iOS destination rather than this device's id. Targeting the
# id makes xcodebuild mount the developer disk image first, which fails whenever
# the phone is locked or its tunnel has dropped — and none of that is needed to
# compile. Only the install and launch below actually require the device.
xcodebuild -workspace "$ROOT/ios/run.xcworkspace" -scheme run \
  -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath "$ROOT/ios/build/device-release" \
  -allowProvisioningUpdates build

APP="$ROOT/ios/build/device-release/Build/Products/Release-iphoneos/run.app"
test -f "$APP/main.jsbundle" || {
  echo "No embedded bundle — the app would need a Metro server." >&2
  exit 1
}

# The phone is only needed from here on, so a locked or unplugged phone costs
# the install rather than the whole build.
[ -z "$DEVICE" ] && find_device
if [ -z "$DEVICE" ]; then
  echo
  echo "Built, but no paired iPhone is reachable, so nothing was installed."
  echo "Connect it, unlock it, trust this Mac, then re-run: npm run ios:device"
  echo "The build is cached, so that second run only installs."
  exit 1
fi

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
