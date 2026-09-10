import type { ExpressionSpecification } from '@maplibre/maplibre-gl-style-spec';

import { ARCHETYPES, classify, describeFootprint, massing, type Ring, type Shape, type Volume } from './massing';
import { territoryColorAt, mixTerritoryColor } from './territoryAppearance';

type Point = [number, number];
/**
 * Most Bengaluru footprints carry no height, and defaulting all of them to one
 * value is what makes a whole block render at an identical altitude. Surveyed
 * heights are always used as-is; only the unsurveyed ones are spread across a
 * few storeys, keyed on the stable feature id so a building never changes.
 */
const FEATURE_ID: ExpressionSpecification = ['to-number', ['coalesce', ['id'], -1]];
// Without a feature id there is nothing stable to key on, so those tiles keep
// exactly the height they render at today rather than all shifting together.
const UNSURVEYED_HEIGHT: ExpressionSpecification = ['case', ['<', FEATURE_ID, 0], 12, ['+', 9, ['*', 1.9, ['%', ['abs', FEATURE_ID], 5]]]];
export const BUILDING_HEIGHT: ExpressionSpecification = ['min', 32, ['max', 5, ['*', 0.7,
  ['case', ['any', ['has', 'render_height'], ['has', 'height']], ['to-number', ['coalesce', ['get', 'render_height'], ['get', 'height'], 12]], UNSURVEYED_HEIGHT],
]]];
export function buildingHeight(properties: GeoJSON.GeoJsonProperties, id?: string | number): number {
  const surveyed = properties?.render_height ?? properties?.height;
  const numeric = Number(id ?? -1);
  const spread = !Number.isFinite(numeric) || numeric < 0 ? 12 : 9 + 1.9 * (Math.abs(numeric) % 5);
  const raw = surveyed != null ? Number(surveyed) : spread;
  return Math.min(32, Math.max(5, (Number.isFinite(raw) ? raw : 12) * 0.7));
}
/** Thin slab the tile layer draws over every footprint; massing starts on top. */
export const ROOF_DECK = 0.25;
const MAX_DETAILS = 4800;
/**
 * How far each material is pulled back towards ivory before the territory hue
 * is applied. Ownership has to stay readable, so the thin parapet keeps most of
 * its colour while the large roof surfaces are only faintly tinted. Rooftop
 * gardens and solar arrays are real materials and never take the territory hue.
 */
const TERRITORY_TINT: Partial<Record<string, number>> = { accent: 0.42, aqua: 0.74, clay: 0.8, cream: 0.88, slate: 0.72 };
const finite = (p: GeoJSON.Position) => p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]) && Math.abs(p[0]!) <= 180 && Math.abs(p[1]!) <= 85;
export function geometryKey(feature: GeoJSON.Feature): string {
  return JSON.stringify(feature.geometry);
}
function hash(text: string) { let value = 2166136261; for (let i = 0; i < text.length; i++) value = Math.imul(value ^ text.charCodeAt(i), 16777619); return value >>> 0; }

type Plan = { origin: Point; scale: Point; volumes: Volume[]; variant: number; seed: number };

/** Metric massing is expensive and never changes for a footprint, so it is kept
 * across frames; only the cheap projection back to lon/lat runs per update. */
const plans = new Map<string, Plan | null>();

function planFor(coordinates: GeoJSON.Position[][], height: number, key: string): Plan | null {
  const outer = coordinates[0]!;
  let cx = 0, cy = 0;
  for (let i = 0; i < outer.length - 1; i++) { cx += outer[i]![0]!; cy += outer[i]![1]!; }
  const count = Math.max(1, outer.length - 1);
  const origin: Point = [cx / count, cy / count];
  const xScale = 111320 * Math.cos(origin[1] * Math.PI / 180);
  const scale: Point = [xScale, 111320];
  if (!(xScale > 1)) return null;

  const shape: Shape = [];
  for (const ring of coordinates) {
    const metric: Ring = [];
    for (let i = 0; i < ring.length - 1; i++) {
      const p = ring[i]!;
      metric.push([(p[0]! - origin[0]) * xScale, (p[1]! - origin[1]) * 111320]);
    }
    if (metric.length < 3) return null;
    shape.push(metric);
  }
  // The outer ring must wind counter-clockwise and holes the other way, so that
  // an inset grows courtyards instead of swallowing them.
  const footprint = describeFootprint(orientShape(shape));
  if (!footprint) return null;
  const seed = hash(key);
  const archetype = classify(footprint, height);
  const volumes = massing(footprint, height, ROOF_DECK, seed, archetype);
  if (!volumes.length) return null;
  return { origin, scale, volumes, variant: ARCHETYPES.indexOf(archetype), seed };
}

function orientShape(shape: Shape): Shape {
  return shape.map((ring, index) => {
    let a = 0;
    for (let i = 0; i < ring.length; i++) { const p = ring[i]!, q = ring[(i + 1) % ring.length]!; a += p[0] * q[1] - q[0] * p[1]; }
    const ccw = a > 0;
    return (index === 0) === ccw ? ring : [...ring].reverse();
  });
}

/**
 * Every suitable loaded footprint in the viewport gets architectural massing
 * built from its real outline: setbacks, wings, terraces and parapets rather
 * than a box on a box. Nearby buildings receive the full composition; distant
 * and economy buildings keep the signature volume so coverage never drops.
 * Nothing is persisted or sent to a server.
 */
export function buildRoofDetails(features: GeoJSON.Feature[], center: Point, economy = false, bounds?: [number, number, number, number], territories: GeoJSON.Feature[] = []): GeoJSON.FeatureCollection<GeoJSON.Polygon> {
  const colorAt = territoryColorAt(territories);
  const seen = new Set<string>();
  const candidates: { plan: Plan; distance: number }[] = [];
  for (const feature of features) {
    const polygons = feature.geometry.type === 'Polygon' ? [feature.geometry.coordinates] : feature.geometry.type === 'MultiPolygon' ? feature.geometry.coordinates : [];
    for (const coordinates of polygons) {
      const outer = coordinates[0];
      if (!outer || outer.length < 4 || !coordinates.every(ring => ring.length >= 4 && ring.every(finite))) continue;
      const minX = Math.min(...outer.map(p => p[0]!)), maxX = Math.max(...outer.map(p => p[0]!));
      const minY = Math.min(...outer.map(p => p[1]!)), maxY = Math.max(...outer.map(p => p[1]!));
      // A small geographic guard band prevents roof pop-in at the screen edge.
      if (bounds && (maxX < bounds[0] - 0.0008 || minX > bounds[2] + 0.0008 || maxY < bounds[1] - 0.0008 || minY > bounds[3] + 0.0008)) continue;
      const key = JSON.stringify(coordinates);
      if (seen.has(key)) continue;
      seen.add(key);
      const height = buildingHeight(feature.properties, feature.id);
      const cacheKey = `${key}@${height.toFixed(1)}`;
      let plan = plans.get(cacheKey);
      if (plan === undefined) {
        plan = planFor(coordinates, height, key);
        plans.set(cacheKey, plan);
        if (plans.size > 4000) plans.delete(plans.keys().next().value!);
      }
      if (!plan) continue;
      const dx = (plan.origin[0] - center[0]) * Math.cos(center[1] * Math.PI / 180);
      candidates.push({ plan, distance: Math.hypot(dx, plan.origin[1] - center[1]) * 111320 });
    }
  }
  candidates.sort((a, b) => a.distance - b.distance);

  const result: GeoJSON.Feature<GeoJSON.Polygon>[] = [];
  for (const { plan, distance } of candidates) {
    if (result.length >= MAX_DETAILS) break;
    // Windows and doors only exist on the block the player is standing in.
    const detail = distance < 130 ? 3 : distance < 260 ? 2 : distance < 620 ? 1 : 0;
    // Economy keeps one volume per building: less architecture, same coverage.
    const drawn = economy ? plan.volumes.slice(0, 1) : plan.volumes.filter(v => v.tier <= detail);
    const territoryColor = colorAt(plan.origin);
    const buildingKey = plan.seed.toString(36);
    for (const volume of drawn) {
      const coordinates = volume.shape.map(ring => {
        const out = ring.map(p => [plan.origin[0] + p[0] / plan.scale[0], plan.origin[1] + p[1] / plan.scale[1]] as GeoJSON.Position);
        out.push(out[0]!);
        return out;
      });
      result.push({
        type: 'Feature',
        properties: {
          base: volume.base,
          height: volume.top,
          tone: volume.tone,
          variant: plan.variant,
          ...(territoryColor && TERRITORY_TINT[volume.tone] !== undefined ? { territoryColor, color: mixTerritoryColor(territoryColor, '#F6F3EC', TERRITORY_TINT[volume.tone]!) } : {}),
          buildingKey,
        },
        geometry: { type: 'Polygon', coordinates },
      });
    }
  }
  return { type: 'FeatureCollection', features: result };
}
