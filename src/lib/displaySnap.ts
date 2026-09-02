import type { GeoCoord } from '@/lib/gpsClean';

type Point = [number, number];

function nearestPointOnSegment(point: Point, a: Point, b: Point): Point {
  const latitude = (point[1] + a[1] + b[1]) / 3;
  const lonScale = 111_320 * Math.cos((latitude * Math.PI) / 180);
  const px = point[0] * lonScale;
  const py = point[1] * 111_320;
  const ax = a[0] * lonScale;
  const ay = a[1] * 111_320;
  const bx = b[0] * lonScale;
  const by = b[1] * 111_320;
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSquared));
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

function distanceSquaredMetres(a: Point, b: Point) {
  const latitude = (a[1] + b[1]) / 2;
  const dx = (a[0] - b[0]) * 111_320 * Math.cos((latitude * Math.PI) / 180);
  const dy = (a[1] - b[1]) * 111_320;
  return dx * dx + dy * dy;
}

function lineParts(feature: GeoJSON.Feature): Point[][] {
  const geometry = feature.geometry;
  if (!geometry) return [];
  if (geometry.type === 'LineString') return [geometry.coordinates as Point[]];
  if (geometry.type === 'MultiLineString') return geometry.coordinates as Point[][];
  return [];
}

/**
 * Rendering-only map matching against the currently visible vector road/path
 * features. The raw route is never passed back to the recorder or server.
 */
export function snapDisplayPathToVisibleRoads(
  path: GeoCoord[],
  roadFeatures: GeoJSON.Feature[],
  maxSnapMetres = 38,
): GeoCoord[] {
  const lines = roadFeatures.flatMap(lineParts).filter((line) => line.length > 1);
  if (!lines.length) return path;
  const maxDistanceSquared = maxSnapMetres * maxSnapMetres;

  return path.map((point) => {
    let closest: Point | null = null;
    let closestDistance = Number.POSITIVE_INFINITY;
    for (const line of lines) {
      for (let index = 1; index < line.length; index++) {
        const candidate = nearestPointOnSegment(point, line[index - 1]!, line[index]!);
        const distance = distanceSquaredMetres(point, candidate);
        if (distance < closestDistance) {
          closestDistance = distance;
          closest = candidate;
        }
      }
    }
    return closest && closestDistance <= maxDistanceSquared ? closest : point;
  });
}
