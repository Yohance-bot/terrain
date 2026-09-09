import type { ExpressionSpecification } from '@maplibre/maplibre-gl-style-spec';

import { territoryColorAt, mixTerritoryColor } from './territoryAppearance';

type Point = [number, number];
export const BUILDING_HEIGHT: ExpressionSpecification = ['min', 32, ['max', 5, ['*', 0.7, ['to-number', ['coalesce', ['get', 'render_height'], ['get', 'height'], 12]]]]];
export function buildingHeight(properties: GeoJSON.GeoJsonProperties): number {
  const raw = Number(properties?.render_height ?? properties?.height ?? 12);
  return Math.min(32, Math.max(5, (Number.isFinite(raw) ? raw : 12) * 0.7));
}
const finite = (p: GeoJSON.Position) => p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]) && Math.abs(p[0]!) <= 180 && Math.abs(p[1]!) <= 85;
export function geometryKey(feature: GeoJSON.Feature): string {
  return JSON.stringify(feature.geometry);
}
function hash(text: string) { let value = 2166136261; for (let i = 0; i < text.length; i++) value = Math.imul(value ^ text.charCodeAt(i), 16777619); return value >>> 0; }
function convex(ring: Point[]) {
  let sign = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!, b = ring[(i + 1) % ring.length]!, c = ring[(i + 2) % ring.length]!;
    const cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
    if (Math.abs(cross) < 1e-16) continue;
    if (sign && sign !== Math.sign(cross)) return false;
    sign = Math.sign(cross);
  }
  return sign !== 0;
}
function inside(point: Point, ring: Point[]) {
  let value = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i]!, b = ring[j]!;
    if ((a[1] > point[1]) !== (b[1] > point[1]) && point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) value = !value;
  }
  return value;
}
function roofPlan(rings: Point[][]): { ring: Point[]; center: Point } | null {
  const outer = rings[0]!;
  const mean: Point = [outer.reduce((n, p) => n + p[0], 0) / outer.length, outer.reduce((n, p) => n + p[1], 0) / outer.length];
  if (rings.length === 1 && outer.length <= 32 && convex(outer)) return { ring: outer, center: mean };
  // An inscribed octagon adds a pavilion to L-shaped wings and courtyard
  // buildings without covering a hole or crossing the footprint boundary.
  const minX = Math.min(...outer.map(p => p[0])), maxX = Math.max(...outer.map(p => p[0]));
  const minY = Math.min(...outer.map(p => p[1])), maxY = Math.max(...outer.map(p => p[1]));
  const xScale = Math.cos(mean[1] * Math.PI / 180);
  const choices: Point[] = [mean];
  for (let x = 1; x < 10; x++) for (let y = 1; y < 10; y++) choices.push([minX + (maxX - minX) * x / 10, minY + (maxY - minY) * y / 10]);
  // These candidates also find narrow rotated wings missed by the regular grid.
  for (let i = 0; i < outer.length; i++) {
    const a = outer[i]!, b = outer[(i + 1) % outer.length]!, c = outer[(i + 2) % outer.length]!;
    choices.push([(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3]);
  }
  let best: Point | null = null, clearance = 0;
  for (const point of choices) {
    if (!inside(point, outer) || rings.slice(1).some(hole => inside(point, hole))) continue;
    let nearest = Infinity;
    for (const ring of rings) for (let i = 0; i < ring.length; i++) {
      const a = ring[i]!, b = ring[(i + 1) % ring.length]!;
      const dx = (b[0] - a[0]) * xScale, dy = b[1] - a[1];
      const px = (point[0] - a[0]) * xScale, py = point[1] - a[1];
      const t = Math.max(0, Math.min(1, (px * dx + py * dy) / (dx * dx + dy * dy || 1)));
      nearest = Math.min(nearest, Math.hypot(px - dx * t, py - dy * t));
    }
    if (nearest > clearance) { clearance = nearest; best = point; }
  }
  if (!best || clearance * 111320 < 0.35) return null;
  const center = best, radius = Math.min(clearance * 0.85, 18 / 111320);
  return { center, ring: Array.from({ length: 8 }, (_, i) => [center[0] + Math.cos(i * Math.PI / 4) * radius / xScale, center[1] + Math.sin(i * Math.PI / 4) * radius]) };
}
const roofPlans = new Map<string, ReturnType<typeof roofPlan>>();

/** Every suitable loaded footprint inside the viewport gets a rooftop feature.
 * Nearby roofs have richer architecture; distant/economy roofs keep a simpler
 * pavilion instead of losing coverage. All footprints in territory areas are
 * included, regardless of ownership. Nothing is persisted or sent to a server.
 */
export function buildRoofDetails(features: GeoJSON.Feature[], center: Point, economy = false, bounds?: [number, number, number, number], territories: GeoJSON.Feature[] = []): GeoJSON.FeatureCollection<GeoJSON.Polygon> {
  const colorAt = territoryColorAt(territories);
  const seen = new Set<string>();
  const candidates: { ring: Point[]; center: Point; key: string; height: number; area: number }[] = [];
  for (const feature of features) {
    const polygons = feature.geometry.type === 'Polygon' ? [feature.geometry.coordinates] : feature.geometry.type === 'MultiPolygon' ? feature.geometry.coordinates : [];
    for (const coordinates of polygons) {
      const outer = coordinates[0];
      if (!outer || outer.length < 4 || !coordinates.every(ring => ring.length >= 4 && ring.every(finite))) continue;
      const minX = Math.min(...outer.map(p => p[0]!)), maxX = Math.max(...outer.map(p => p[0]!));
      const minY = Math.min(...outer.map(p => p[1]!)), maxY = Math.max(...outer.map(p => p[1]!));
      // A small geographic guard band prevents roof pop-in at the screen edge.
      if (bounds && (maxX < bounds[0] - 0.0008 || minX > bounds[2] + 0.0008 || maxY < bounds[1] - 0.0008 || minY > bounds[3] + 0.0008)) continue;
      const key = JSON.stringify(coordinates); if (seen.has(key)) continue; seen.add(key);
      const rings = coordinates.map(ring => ring.slice(0, -1) as Point[]);
      let plan = roofPlans.get(key);
      if (plan === undefined) {
        plan = roofPlan(rings); roofPlans.set(key, plan);
        if (roofPlans.size > 6000) roofPlans.delete(roofPlans.keys().next().value!);
      }
      if (!plan) continue;
      const c = plan.center, ring = plan.ring;
      const area = Math.abs(ring.reduce((sum, p, i) => { const next = ring[(i + 1) % ring.length]!; return sum + (p[0] - c[0]) * (next[1] - c[1]) - (next[0] - c[0]) * (p[1] - c[1]); }, 0)) * 0.5 * 111320 ** 2 * Math.cos(c[1] * Math.PI / 180);
      if (area < 1) continue;
      candidates.push({ ring, center: c, key, height: buildingHeight(feature.properties), area });
    }
  }
  const distance = (p: Point) => Math.hypot((p[0] - center[0]) * Math.cos(center[1] * Math.PI / 180), p[1] - center[1]) * 111320;
  candidates.sort((a, b) => distance(a.center) - distance(b.center));
  const result: GeoJSON.Feature<GeoJSON.Polygon>[] = [];
  for (const { ring, center: c, key, height, area } of candidates) {
    const seed = hash(key), variant = seed % 12;
    const territoryColor = colorAt(c);
    const add = (sx: number, sy: number, base: number, top: number, tone: string, offset = 0, corner = 0) => {
      // Uniform scaling + translation toward a vertex is a convex combination:
      // scale + offset <= 1 keeps every component inside the safe roof plan.
      const anchor = ring[(corner + (seed >>> 8)) % ring.length]!;
      const points: Point[] = ring.map(p => [c[0] + (p[0] - c[0]) * sx + (anchor[0] - c[0]) * offset, c[1] + (p[1] - c[1]) * sy + (anchor[1] - c[1]) * offset]);
      points.push(points[0]!);
      // Every roof tier uses uniform scaling inside its convex footprint.
      result.push({ type: 'Feature', properties: { base, height: top, tone, variant, ...(territoryColor ? { territoryColor, color: mixTerritoryColor(territoryColor, tone === 'slate' ? '#183A43' : '#F3F7ED', tone === 'cream' ? 0.65 : tone === 'slate' ? 0.42 : tone === 'garden' ? 0.2 : 0.12) } : {}), buildingKey: seed.toString(36) }, geometry: { type: 'Polygon', coordinates: [points] } });
    };
    const tone = ['aqua', 'clay', 'slate', 'cream'][seed % 4]!;
    if (territoryColor) add(0.98, 0.98, height + 0.61, height + 0.85, 'aqua');
    if (economy || distance(c) > 480 || area < 25) {
      // Coverage stays complete at low LOD. A raised, tinted roof pavilion is
      // cheaper than dropping whole buildings from the decoration pass.
      const scale = [0.76, 0.48, 0.88, 0.6, 0.38, 0.7][variant % 6]!;
      add(scale, scale, height + 0.85, height + (area < 25 ? 1.8 : 2 + variant % 4), tone, variant % 2 ? 0.16 : 0);
      continue;
    }
    if (variant === 0) {
      // Three setback storeys and a small rooftop pavilion.
      add(0.83, 0.83, height + 0.6, height + 2.8, 'cream');
      add(0.65, 0.65, height + 2.8, height + 4, tone);
      add(0.32, 0.32, height + 4, height + 5.5, 'slate');
    } else if (variant === 1) {
      // Low pyramidal roof: six inexpensive stepped volumes.
      for (let i = 0; i < 6; i++) add(0.92 - i * 0.135, 0.92 - i * 0.135, height + 0.6 + i * 0.55, height + 1.15 + i * 0.55, tone);
    } else if (variant === 2) {
      // Raised garden terrace, parapet rim and recessed roof deck.
      add(0.90, 0.90, height + 0.6, height + 1.3, 'cream');
      add(0.78, 0.78, height + 1.3, height + 1.5, 'garden');
      add(0.34, 0.34, height + 1.5, height + (area > 250 ? 5 : 3), 'aqua');
      add(0.40, 0.40, height + (area > 250 ? 5 : 3), height + (area > 250 ? 5.6 : 3.6), 'cream');
    } else if (variant === 3) {
      // Floating canopy over a narrow rooftop core.
      add(0.34, 0.34, height + 0.6, height + 3.6, 'slate');
      add(0.75, 0.75, height + 3.6, height + 4.2, 'aqua');
      add(0.60, 0.60, height + 4.2, height + 4.6, 'cream');
    } else if (variant === 4) {
      // Twin pavilions, with a shared landscaped podium.
      add(.88, .88, height + .85, height + 1.4, 'garden');
      add(.24, .24, height + 1.4, height + 4.8, tone, .46, 0);
      add(.24, .24, height + 1.4, height + 3.6, 'aqua', .46, Math.floor(ring.length / 2));
    } else if (variant === 5) {
      // Asymmetric terraced penthouse.
      add(.86, .86, height + .85, height + 1.3, 'cream');
      add(.48, .48, height + 1.3, height + 3.6, tone, .26);
      add(.31, .31, height + 3.6, height + 4.1, 'slate', .26);
      add(.18, .18, height + 1.3, height + 1.9, 'garden', .55, Math.floor(ring.length / 2));
    } else if (variant === 6) {
      // Lantern tower with a broad cap.
      add(.66, .66, height + .85, height + 1.4, 'cream');
      add(.26, .26, height + 1.4, height + 5.6, 'aqua');
      add(.44, .44, height + 5.6, height + 6.1, tone);
      add(.18, .18, height + 6.1, height + 6.8, 'cream');
    } else if (variant === 7) {
      // Two low solar/glass wings.
      add(.9, .9, height + .85, height + 1.2, 'cream');
      add(.29, .29, height + 1.2, height + 1.9, 'slate', .4);
      add(.29, .29, height + 1.2, height + 2.4, 'aqua', .4, Math.floor(ring.length / 2));
    } else if (variant === 8) {
      // Ring of corner turrets.
      add(.85, .85, height + .85, height + 1.4, 'garden');
      for (let i = 0; i < 4; i++) add(.18, .18, height + 1.4, height + 3.2 + (i % 2), tone, .62, Math.floor(i * ring.length / 4));
    } else if (variant === 9) {
      // Art-deco crown: alternating setbacks and pale cornices.
      for (let i = 0; i < 5; i++) add(.84 - i * .13, .84 - i * .13, height + .85 + i * .85, height + 1.7 + i * .85, i % 2 ? 'cream' : tone);
    } else if (variant === 10) {
      // Garden deck with an offset observation pavilion.
      add(.92, .92, height + .85, height + 1.2, 'cream');
      add(.8, .8, height + 1.2, height + 1.5, 'garden');
      add(.22, .22, height + 1.5, height + 4.1, 'aqua', .52);
      add(.32, .32, height + 4.1, height + 4.6, tone, .52);
    } else {
      // Stacked floating terraces.
      add(.28, .28, height + .85, height + 5.2, 'slate');
      add(.86, .86, height + 2, height + 2.5, tone);
      add(.64, .64, height + 3.5, height + 4, 'garden');
      add(.46, .46, height + 5.2, height + 5.7, 'cream');
    }
  }
  return { type: 'FeatureCollection', features: result };
}
