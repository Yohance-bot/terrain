import type { GeoCoord } from '@/lib/gpsClean';
export const RUN_TRAIL_COLOR = '#11D9F1';
const interpolate = (a: GeoCoord, b: GeoCoord, t: number): GeoCoord => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
const metres = (a: GeoCoord, b: GeoCoord) => Math.hypot((a[0] - b[0]) * Math.cos((a[1] + b[1]) * Math.PI / 360), a[1] - b[1]) * 111320;
/** Rounded quadratic corners without spline overshoot. Each curve stays inside
 * its corner triangle, with a metre-bounded cut; endpoints and GPS gaps survive.
 * This is the final rendering step, never input to metrics or street matching.
 */
export function smoothTrail(data: GeoJSON.FeatureCollection<GeoJSON.LineString>, radiusM = 8, budget = 4608): GeoJSON.FeatureCollection<GeoJSON.LineString> {
  const inputCount = data.features.reduce((n, f) => n + f.geometry.coordinates.length, 0);
  let extras = Math.max(0, budget - inputCount);
  return { ...data, features: data.features.map(feature => {
    const input = feature.geometry.coordinates as GeoCoord[];
    if (input.length < 3 || extras < 2) return feature;
    const output: GeoCoord[] = [input[0]!];
    for (let i = 1; i < input.length - 1; i++) {
      const previous = input[i - 1]!, point = input[i]!, next = input[i + 1]!;
      const incoming = metres(previous, point), outgoing = metres(point, next);
      const ax = point[0] - previous[0], ay = point[1] - previous[1], bx = next[0] - point[0], by = next[1] - point[1];
      const cosine = (ax * bx + ay * by) / (Math.hypot(ax, ay) * Math.hypot(bx, by) || 1);
      if (extras < 2 || incoming < 0.3 || outgoing < 0.3 || cosine > 0.998 || cosine < -0.92) { output.push(point); continue; }
      const cut = Math.min(Math.max(0, radiusM), incoming * 0.35, outgoing * 0.35);
      const entry = interpolate(point, previous, cut / incoming), exit = interpolate(point, next, cut / outgoing);
      const steps = Math.min(6, Math.max(2, Math.floor(extras / Math.max(1, input.length - i))));
      output.push(entry);
      for (let step = 1; step <= steps; step++) {
        const t = step / steps;
        output.push(interpolate(interpolate(entry, point, t), interpolate(point, exit, t), t));
      }
      extras -= steps;
    }
    output.push(input.at(-1)!);
    return { ...feature, geometry: { ...feature.geometry, coordinates: output } };
  }) };
}
