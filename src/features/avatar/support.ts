/**
 * Whether the 3D character may be rendered at all.
 *
 * Filament is killed on its first frame on iOS — see `docs/18_AVATAR_CRASH.md`.
 * The map mounts the avatar on the opening screen, so a stored `avatar`
 * preference makes the app impossible to open, and impossible to recover from
 * inside the app, since Settings sits behind the crash. That is why this is a
 * hard gate and not merely a default: the preference is still remembered and
 * still honoured the moment this flips, but it cannot take the app down.
 *
 * Android's surface lifecycle rules out the fault that was found and fixed on
 * iOS, but the first-frame kill has not been reproduced or ruled out on Android
 * hardware — there is no device or emulator image here to try it on. So it stays
 * off there too, rather than shipping a guess to testers.
 */
export const AVATAR_3D_SUPPORTED = false;
