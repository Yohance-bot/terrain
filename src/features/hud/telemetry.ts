export type TimedDistance = { ts: number; distanceM: number };
export type RunFix = { coordinate: [number, number]; ts: number; speedMps: number; bearing: number | null; accuracyM: number | null; segment: number };

/** A trailing window, not whole-run average. Missing/stale GPS never implies motion. */
export function rollingPace(points: TimedDistance[], now: number, unitMetres = 1000): number | null {
  const end = points.at(-1);
  if (!end || now - end.ts > 10_000 || end.ts - now > 5_000) return null;
  const start = points.find(p => p.ts >= end.ts - 20_000);
  if (!start || end.ts - start.ts < 5_000) return null;
  const distance = end.distanceM - start.distanceM;
  const seconds = (end.ts - start.ts) / 1000;
  if (distance < 3 || distance / seconds < 0.5) return null;
  return seconds * unitMetres / distance;
}

export function formatPace(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—';
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`;
}

export function bearingBetween(a: [number, number], b: [number, number]): number {
  const radians = Math.PI / 180;
  const dLon = (b[0] - a[0]) * radians;
  const latA = a[1] * radians;
  const latB = b[1] * radians;
  return (Math.atan2(Math.sin(dLon) * Math.cos(latB), Math.cos(latA) * Math.sin(latB) - Math.sin(latA) * Math.cos(latB) * Math.cos(dLon)) / radians + 360) % 360;
}

export function smoothBearing(previous: number, next: number, weight = 0.22): number {
  return previous + ((next - previous + 540) % 360 - 180) * weight;
}
