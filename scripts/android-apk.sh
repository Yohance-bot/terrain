#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export TERRARUN_KEYSTORE="${TERRARUN_KEYSTORE:-$HOME/.config/terrarun/android-release.jks}"
export TERRARUN_STORE_PASSWORD="${TERRARUN_STORE_PASSWORD:-$(cat "$HOME/.config/terrarun/android-release.password")}"
export EXPO_PUBLIC_API_URL=https://run-backend-ngyo.onrender.com
export CI=1
export CMAKE_BUILD_PARALLEL_LEVEL=2
[[ -f "$TERRARUN_KEYSTORE" && -n "$TERRARUN_STORE_PASSWORD" ]] || { echo "Release signing key/password missing" >&2; exit 1; }
cd android
./gradlew assembleRelease -PreactNativeArchitectures=arm64-v8a,armeabi-v7a --max-workers=2 -Dorg.gradle.jvmargs='-Xmx3g -XX:MaxMetaspaceSize=768m' "$@"
