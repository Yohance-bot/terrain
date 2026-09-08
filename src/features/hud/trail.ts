import type { GeoCoord } from '@/lib/gpsClean';
import { rdpSimplify } from '@/lib/gpsClean';

export const TRAIL_POINT_BUDGET = 1536;
/** Display-only LOD, preserving section breaks and endpoints. Raw fixes stay in SQLite. */
export function buildTrail(path: GeoCoord[], starts: number[], economy = false): GeoJSON.FeatureCollection<GeoJSON.LineString> {
  const budget = economy ? 768 : TRAIL_POINT_BUDGET;
  const boundaries = [0, ...starts.filter(i => i > 0 && i < path.length), path.length];
  let parts: GeoCoord[][] = [];
  for (let part = 1; part < boundaries.length; part++) {
    let current: GeoCoord[] = [];
    for (const p of path.slice(boundaries[part - 1], boundaries[part])) {
      if (!Number.isFinite(p[0]) || !Number.isFinite(p[1]) || Math.abs(p[0]) > 180 || Math.abs(p[1]) > 85) { if (current.length > 1) parts.push(current); current = []; continue; }
      // Never draw a world-spanning line across the antimeridian.
      if (current.length && Math.abs(p[0] - current.at(-1)![0]) > 180) { if (current.length > 1) parts.push(current); current = []; }
      current.push(p);
    }
    if (current.length > 1) parts.push(current);
  }
  // Section explosion is also bounded. Old geometry is display history only.
  parts = parts.slice(-Math.floor(budget / 4));
  let tolerance = economy ? 5 : 2;
  const original = parts;
  for (let pass = 0; pass < 12; pass++) {
    parts = original.map(part => rdpSimplify(part.map(([lon, lat]) => ({ lon, lat })), tolerance).map(p => [p.lon, p.lat]));
    if (parts.reduce((n, p) => n + p.length, 0) <= budget) break;
    tolerance *= 2;
  }
  // A pathological zigzag must still have a hard native-source budget.
  let remaining = budget;
  const features: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  for (let i = parts.length - 1; i >= 0 && remaining >= 2; i--) {
    const part = parts[i]!;
    const take = Math.min(part.length, remaining);
    const coordinates = part.length <= take ? part : Array.from({ length: take }, (_, n) => part[Math.round(n * (part.length - 1) / (take - 1))]!);
    features.unshift({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates } });
    remaining -= coordinates.length;
  }
  return { type: 'FeatureCollection', features };
}
