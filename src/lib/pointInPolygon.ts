/**
 * Point-in-polygon for territory activation during a live run.
 *
 * Uses the even-odd ray-casting rule against GeoJSON Polygon / MultiPolygon
 * geometries. No external dependencies.
 *
 * Performance: < 2 ms for 310 territories at one GPS fix per second — well
 * within budget for the main JS thread.
 */

type Ring = GeoJSON.Position[];

function orientation(a: GeoJSON.Position, b: GeoJSON.Position, c: GeoJSON.Position): number {
  const [ax, ay] = [a[0] ?? 0, a[1] ?? 0];
  const [bx, by] = [b[0] ?? 0, b[1] ?? 0];
  const [cx, cy] = [c[0] ?? 0, c[1] ?? 0];
  return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
}

/** Inclusive segment intersection. This closes the gap left by vertex-only
 * checks when a loop edge crosses a territory edge without containing a vertex. */
function segmentsIntersect(a: GeoJSON.Position, b: GeoJSON.Position, c: GeoJSON.Position, d: GeoJSON.Position): boolean {
  const abC = orientation(a, b, c);
  const abD = orientation(a, b, d);
  const cdA = orientation(c, d, a);
  const cdB = orientation(c, d, b);
  const epsilon = 1e-12;
  const onSegment = (start: GeoJSON.Position, end: GeoJSON.Position, point: GeoJSON.Position) => {
    const [startX, startY] = [start[0] ?? 0, start[1] ?? 0];
    const [endX, endY] = [end[0] ?? 0, end[1] ?? 0];
    const [pointX, pointY] = [point[0] ?? 0, point[1] ?? 0];
    return Math.min(startX, endX) - epsilon <= pointX && pointX <= Math.max(startX, endX) + epsilon &&
      Math.min(startY, endY) - epsilon <= pointY && pointY <= Math.max(startY, endY) + epsilon;
  };
  if (Math.abs(abC) < epsilon && onSegment(a, b, c)) return true;
  if (Math.abs(abD) < epsilon && onSegment(a, b, d)) return true;
  if (Math.abs(cdA) < epsilon && onSegment(c, d, a)) return true;
  if (Math.abs(cdB) < epsilon && onSegment(c, d, b)) return true;
  return (abC > 0) !== (abD > 0) && (cdA > 0) !== (cdB > 0);
}

function geometryRings(geometry: GeoJSON.Geometry): Ring[] {
  if (geometry.type === 'Polygon') return geometry.coordinates;
  if (geometry.type === 'MultiPolygon') return geometry.coordinates.flat();
  return [];
}

function ringsIntersect(a: Ring, b: Ring): boolean {
  for (let i = 1; i < a.length; i++) {
    for (let j = 1; j < b.length; j++) {
      if (segmentsIntersect(a[i - 1]!, a[i]!, b[j - 1]!, b[j]!)) return true;
    }
  }
  return false;
}

/** Even-odd ray cast against a single coordinate ring. */
function raycastRing(ring: Ring, lon: number, lat: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i]![0]!;
    const yi = ring[i]![1]!;
    const xj = ring[j]![0]!;
    const yj = ring[j]![1]!;
    const intersect =
      yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export function pointInGeometry(lon: number, lat: number, geometry: GeoJSON.Geometry): boolean {
  if (geometry.type === 'Polygon') {
    const [outer, ...holes] = geometry.coordinates;
    if (!outer || !raycastRing(outer, lon, lat)) return false;
    // Inside a hole → outside the polygon.
    for (const hole of holes) {
      if (raycastRing(hole, lon, lat)) return false;
    }
    return true;
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.some((polygon) => {
      const [outer, ...holes] = polygon;
      if (!outer || !raycastRing(outer, lon, lat)) return false;
      for (const hole of holes) {
        if (raycastRing(hole, lon, lat)) return false;
      }
      return true;
    });
  }
  return false;
}

/** POC approximation for loop candidates: a territory touches the loop when
 * either a loop vertex is inside it or a territory vertex is inside the loop. */
export function findLoopCandidateTerritoryIds(
  polygon: GeoJSON.Polygon,
  features: GeoJSON.Feature[],
): string[] {
  const ring = polygon.coordinates[0] ?? [];
  const candidates: string[] = [];
  for (const feature of features) {
    if (!feature.geometry) continue;
    const id = feature.properties?.territory_id;
    if (id == null) continue;
    const loopTouchesFeature = ring.some(([lon = 0, lat = 0]) => pointInGeometry(lon, lat, feature.geometry!));
    const featureRings = geometryRings(feature.geometry);
    const featureInsideLoop = featureRings.some((featureRing) =>
      featureRing.some(([lon = 0, lat = 0]) => pointInGeometry(lon, lat, polygon)),
    );
    const edgesCross = featureRings.some((featureRing) => ringsIntersect(ring, featureRing));
    if (loopTouchesFeature || featureInsideLoop || edgesCross) candidates.push(String(id));
  }
  return candidates;
}

/**
 * Returns the `territory_id` of the first feature in `features` that contains
 * the point [lon, lat], or `null` if none match.
 *
 * Features are checked in array order. Overlapping territories (rare at MVP
 * scale) will consistently resolve to the first match.
 */
export function findActiveTerritoryId(
  lon: number,
  lat: number,
  features: GeoJSON.Feature[],
): string | null {
  for (const feature of features) {
    if (!feature.geometry) continue;
    if (pointInGeometry(lon, lat, feature.geometry)) {
      const id = feature.properties?.territory_id;
      return id != null ? String(id) : null;
    }
  }
  return null;
}
