import { smoothBearing, type RunFix } from './telemetry';
export type FollowPose = { bearing: number; zoom: number; pitch: number };
export function followPose(previous: FollowPose, fix: RunFix, calm: boolean): FollowPose {
  const speed = Math.max(0, Math.min(7, fix.speedMps));
  return {
    bearing: calm ? 0 : speed >= 1.5 && fix.bearing != null ? smoothBearing(previous.bearing, fix.bearing) : previous.bearing,
    pitch: calm ? 0 : previous.pitch + (Math.min(57, 51 + speed * 1.2) - previous.pitch) * 0.18,
    zoom: calm ? 17 : previous.zoom + ((17.7 - speed * 0.05) - previous.zoom) * 0.15,
  };
}
