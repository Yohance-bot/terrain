#!/usr/bin/env bash
# Build a signed release APK, and install it if a phone is attached.
#
# Release embeds the JS bundle, so the APK runs without a Metro server and can
# be handed to a tester as a file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APK="$ROOT/android/app/build/outputs/apk/release/app-release.apk"

# Only arm64 by default. The generated gradle.properties asks for four ABIs,
# which quadruples the native build for three targets no current phone needs —
# armeabi-v7a is pre-2017 hardware and the x86 pair only exists for emulators.
# Widen it when a target needs it: ABIS=arm64-v8a,armeabi-v7a for an old phone.
ABIS="${ABIS:-arm64-v8a}"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
test -d "$ANDROID_HOME" || {
  echo "No Android SDK at $ANDROID_HOME. Install it, or set ANDROID_HOME." >&2
  exit 1
}

# The same lesson as the iOS build: this is an 8 GB machine, and Gradle plus a
# parallel CMake native build will happily ask for more than it has and spend
# the rest of the build swapping. Hold both down.
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
export CI=1

# app/build.gradle reads the keystore from the environment and, when it is
# absent, silently falls through to an *unsigned* release APK that no phone
# will install. Refuse early instead, with the reason.
#
# The key itself never enters the repository. Losing it means testers cannot
# install an update over what they already have, so it wants a backup.
KEYSTORE_DIR="$HOME/.config/terrarun"
export TERRARUN_KEYSTORE="${TERRARUN_KEYSTORE:-$KEYSTORE_DIR/android-release.jks}"
if [ -z "${TERRARUN_STORE_PASSWORD:-}" ]; then
  test -f "$KEYSTORE_DIR/android-release.password" || {
    echo "No signing password at $KEYSTORE_DIR/android-release.password," >&2
    echo "and TERRARUN_STORE_PASSWORD is not set." >&2
    exit 1
  }
  TERRARUN_STORE_PASSWORD="$(cat "$KEYSTORE_DIR/android-release.password")"
  export TERRARUN_STORE_PASSWORD
fi
test -f "$TERRARUN_KEYSTORE" || {
  echo "Keystore missing: $TERRARUN_KEYSTORE" >&2
  exit 1
}

echo "→ Building release APK for $ABIS"
rm -f "$APK"
(cd "$ROOT/android" && ./gradlew assembleRelease \
  -PreactNativeArchitectures="$ABIS" \
  --max-workers=2 \
  -Dorg.gradle.jvmargs='-Xmx3g -XX:MaxMetaspaceSize=768m' \
  --console=plain "$@")

test -f "$APK" || { echo "Gradle reported success but produced no APK." >&2; exit 1; }

# An APK that is unsigned, or still carrying the debug certificate, is worth
# catching here rather than on the phone. The fingerprint is printed so it can
# be compared against the key testers already trust.
echo "→ Verifying the signature"
APKSIGNER=$(find "$ANDROID_HOME/build-tools" -name apksigner -type f | sort -V | tail -1)
"$APKSIGNER" verify --print-certs "$APK" | rg -i "certificate SHA-256" || {
  echo "APK is not signed." >&2
  exit 1
}

echo
echo "APK: $APK"
du -h "$APK" | cut -f1

# Installing is optional: the APK is the deliverable, and a phone may not be here.
if command -v adb >/dev/null && [ -n "$(adb devices | awk 'NR>1 && $2=="device"')" ]; then
  echo "→ Installing on the attached device"
  adb install -r "$APK"
else
  echo "No Android device attached over adb — APK left for manual install."
fi
