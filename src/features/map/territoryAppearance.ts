import type { ExpressionSpecification } from '@maplibre/maplibre-gl-style-spec';
type Point = [number, number];
function inside(p: Point, ring: GeoJSON.Position[]) {
  let yes = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i]!, b = ring[j]!;
    if ((a[1]! > p[1]) !== (b[1]! > p[1]) && p[0] < (b[0]! - a[0]!) * (p[1] - a[1]!) / (b[1]! - a[1]!) + a[0]!) yes = !yes;
  }
  return yes;
}
/** Highest visual overlay first. Bounding boxes keep point-in-polygon work small. */
export function territoryColorAt(features: GeoJSON.Feature[]) {
  const zones = features.flatMap(f => {
    const color = f.properties?.capture_color ?? f.properties?.owner_color ?? f.properties?.terrain_color ?? f.properties?.color;
    if (typeof color !== 'string' || !/^#[0-9a-f]{6}$/i.test(color)) return [];
    const polygons = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.type === 'MultiPolygon' ? f.geometry.coordinates : [];
    return polygons.filter(p => p[0]?.length).map(rings => {
      const ring = rings[0]!;
      return { color, rings, box: [Math.min(...ring.map(p => p[0]!)), Math.min(...ring.map(p => p[1]!)), Math.max(...ring.map(p => p[0]!)), Math.max(...ring.map(p => p[1]!))] };
    });
  });
  return (p: Point): string | undefined => zones.find(z => p[0] >= z.box[0]! && p[1] >= z.box[1]! && p[0] <= z.box[2]! && p[1] <= z.box[3]! && inside(p, z.rings[0]!) && !z.rings.slice(1).some(r => inside(p, r)))?.color;
}
export function mixTerritoryColor(hex: string, target: string, amount: number) {
  return '#' + [1, 3, 5].map(i => Math.round(parseInt(hex.slice(i, i + 2), 16) * (1 - amount) + parseInt(target.slice(i, i + 2), 16) * amount).toString(16).padStart(2, '0')).join('');
}
/** Alpha lives in the colour, avoiding native fill-opacity mutation issues. */
export function territoryFill(prefix: string): ExpressionSpecification {
  return ['interpolate', ['linear'], ['zoom'], 12, ['to-color', ['get', `${prefix}_far`]], 16, ['to-color', ['get', `${prefix}_mid`]], 18, ['to-color', ['get', prefix]]];
}

/** Vector IDs let us tint facades without duplicating extrusions or z-fighting.
 * Providers without IDs still receive the territory-coloured roof treatment. */
export function buildingTerritoryPaint(buildings: GeoJSON.Feature[], territories: GeoJSON.Feature[], fallback: string): ExpressionSpecification | string {
  const colorAt = territoryColorAt(territories);
  const groups = new Map<string, Set<string>>();
  const seen = new Set<string>();
  for (const f of buildings) {
    if (f.id == null || seen.size >= 2400) continue;
    const id = String(f.id); if (seen.has(id)) continue; seen.add(id);
    const ring = f.geometry.type === 'Polygon' ? f.geometry.coordinates[0] : f.geometry.type === 'MultiPolygon' ? f.geometry.coordinates[0]?.[0] : null;
    if (!ring?.length) continue;
    const points = ring.slice(0, -1);
    const c: Point = [points.reduce((n,p) => n + p[0]!, 0) / points.length, points.reduce((n,p) => n + p[1]!, 0) / points.length];
    const color = colorAt(c); if (!color) continue;
    const tint = mixTerritoryColor(color, '#E9EFE8', .52);
    const ids = groups.get(tint) ?? new Set<string>(); ids.add(id); groups.set(tint, ids);
  }
  if (!groups.size) return fallback;
  const expression: unknown[] = ['match', ['to-string', ['id']]];
  for (const [color, ids] of groups) expression.push([...ids], color);
  expression.push(fallback);
  return expression as ExpressionSpecification;
}
