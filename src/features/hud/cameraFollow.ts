import type { RunFix } from './telemetry';

/** Last-known GPS is often older than ten seconds. That is still the right
 *  neighbourhood to open on; Jayanagar is not. After the first snap, live
 *  follow goes back to rejecting stale samples so a dead GPS cannot drag. */
export const LIVE_FIX_MAX_AGE_MS = 10_000;
/** Animate only for small corrections. Opening from the bundled centre to the
 *  player would otherwise fly the camera across a continent. */
export const SNAP_IF_FARTHER_M = 80;

export function fixTimestampMs(ts: number): number {
  // Unix seconds are ~1e9; JS ms are ~1e12. Native Android has used both.
  return ts > 0 && ts < 1e11 ? ts * 1000 : ts;
}

export function metresApart(a: [number, number], b: [number, number]): number {
  const lat = ((a[1] + b[1]) / 2) * Math.PI / 180;
  const dx = (b[0] - a[0]) * Math.cos(lat);
  return Math.hypot(dx, b[1] - a[1]) * 111_320;
}

export function shouldFollowFix(now: number, fix: RunFix, hasSnapped: boolean, holdUntil: number): boolean {
  if (now < holdUntil) return false;
  if (!hasSnapped) return true;
  return now - fixTimestampMs(fix.ts) <= LIVE_FIX_MAX_AGE_MS;
}

export function followDurationMs(hasSnapped: boolean, far: boolean, reducedMotion: boolean, economy: boolean): number {
  if (!hasSnapped || far || reducedMotion) return 0;
  return economy ? 500 : 850;
}
