/**
 * Whether the 3D character may be rendered at all.
 *
 * This exists because the avatar was, twice over, able to kill the app on launch
 * — the map mounts it on the opening screen, so "the renderer crashed" and "the
 * app won't open" were the same sentence. Both faults are fixed (see
 * `docs/18_AVATAR_CRASH.md`), so it is on.
 *
 * The switch is kept because the preference alone is not a safe place to put
 * this. It is stored, and Settings — where it could be changed — is behind the
 * crash, so a phone that has chosen the character cannot be talked out of it
 * from inside the app. If the renderer starts taking the app down again, flip
 * this to `false` and the map falls back to the marker it already draws.
 */
export const AVATAR_3D_SUPPORTED = true;
