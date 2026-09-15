import type { RoofBudget } from './worldGeometry';

// Presentation budgets only: never used by GPS, capture, scoring or storage.
export const ANDROID_WORLD_BUDGET: RoofBudget = { maxDetails: 1400, detailScale: .65 };
export const ANDROID_WORLD_BUILDINGS = 360;
export const ANDROID_WORLD_INTERVAL_MS = 6000;
export const ANDROID_WORLD_BATCH_SIZE = 24;

/** Bound work before footprint analysis, preferring the visible neighbourhood. */
export function nearestBuildings(features: GeoJSON.Feature[], center: [number, number], limit = ANDROID_WORLD_BUILDINGS): GeoJSON.Feature[] {
  const seen = new Set<string>();
  const cos = Math.cos(center[1] * Math.PI / 180);
  return features.flatMap(feature => {
    const ring = feature.geometry.type === 'Polygon' ? feature.geometry.coordinates[0] : feature.geometry.type === 'MultiPolygon' ? feature.geometry.coordinates[0]?.[0] : null;
    if (!ring?.length || !ring[0] || !ring[0].every(Number.isFinite)) return [];
    const key = feature.id == null ? JSON.stringify(feature.geometry) : `${feature.id}:${JSON.stringify(feature.geometry)}`;
    if (seen.has(key)) return []; seen.add(key);
    const p = ring[0];
    return [{ feature, distance: Math.hypot((p[0]! - center[0]) * cos, p[1]! - center[1]) }];
  }).sort((a, b) => a.distance - b.distance).slice(0, limit).map(entry => entry.feature);
}

/** Yield between geometry batches so navigation/touches can run. Cancellation
 * discards the whole result; a partial/stale scene is never published. */
export async function buildInBatches<T, R>(items: T[], batchSize: number, build: (batch: T[], remaining: number) => R[], limit: number, cancelled: () => boolean, yieldToUI: () => Promise<void> = () => new Promise(resolve => setTimeout(resolve, 0))): Promise<R[] | null> {
  const result: R[] = [];
  for (let i = 0; i < items.length && result.length < limit; i += batchSize) {
    await yieldToUI();
    if (cancelled()) return null;
    result.push(...build(items.slice(i, i + batchSize), limit - result.length).slice(0, limit - result.length));
  }
  return cancelled() ? null : result;
}
