/**
 * Soft pastel palette for territory zone fills + outlines.
 *
 * Each entry is a pair: [fill, border]. The fill is used at ~35-45% opacity
 * inside the territory polygon; the border is a slightly more saturated
 * version of the same hue used for the outline glow.
 *
 * Designed so that adjacent territories are always visually distinct,
 * even when semi-transparent fills overlap the base map.
 */
export const ZONE_PALETTE = [
  '#3E88C7', // blue district
  '#3D9B68', // green district
  '#7759B8', // violet district
  '#B67936', // amber district
  '#B14F83', // magenta district
  '#3972B7', // royal blue district
  '#5C9B46', // leaf green district
  '#328A98', // teal district
  '#9B5AAB', // orchid district
  '#A66A52', // terracotta district
  '#4D8FA8', // slate blue district
  '#7A8D44', // olive district
] as const;

function paletteIndex(territoryId: string): number {
  let hash = 0;
  for (let i = 0; i < territoryId.length; i += 1) {
    hash = (hash * 31 + territoryId.charCodeAt(i)) >>> 0;
  }
  return hash % ZONE_PALETTE.length;
}

function snapKey(lon: number, lat: number): string {
  return `${lon.toFixed(5)},${lat.toFixed(5)}`;
}

function edgeKey(a: GeoJSON.Position, b: GeoJSON.Position): string {
  const left = snapKey(a[0]!, a[1]!);
  const right = snapKey(b[0]!, b[1]!);
  return left < right ? `${left}|${right}` : `${right}|${left}`;
}

function exteriorRings(geometry: GeoJSON.Geometry): GeoJSON.Position[][] {
  if (geometry.type === 'Polygon') {
    return geometry.coordinates.length > 0 ? [geometry.coordinates[0]!] : [];
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates
      .map((polygon) => polygon[0]!)
      .filter((ring): ring is GeoJSON.Position[] => ring != null && ring.length > 0);
  }
  return [];
}

function boundaryEdges(geometry: GeoJSON.Geometry): Set<string> {
  const edges = new Set<string>();
  for (const ring of exteriorRings(geometry)) {
    for (let i = 0; i < ring.length - 1; i += 1) {
      edges.add(edgeKey(ring[i]!, ring[i + 1]!));
    }
  }
  return edges;
}

function shareBoundary(a: Set<string>, b: Set<string>): boolean {
  for (const edge of a) {
    if (b.has(edge)) return true;
  }
  return false;
}

function buildAdjacency(features: GeoJSON.Feature[]): Map<string, Set<string>> {
  const indexed = features
    .map((feature) => {
      const id = String(feature.properties?.territory_id ?? '');
      const geometry = feature.geometry;
      if (!id || !geometry) return null;
      return { id, edges: boundaryEdges(geometry) };
    })
    .filter((item): item is { id: string; edges: Set<string> } => item !== null);

  const adjacency = new Map<string, Set<string>>();
  for (const { id } of indexed) {
    adjacency.set(id, new Set());
  }

  for (let i = 0; i < indexed.length; i += 1) {
    for (let j = i + 1; j < indexed.length; j += 1) {
      if (!shareBoundary(indexed[i]!.edges, indexed[j]!.edges)) continue;
      adjacency.get(indexed[i]!.id)?.add(indexed[j]!.id);
      adjacency.get(indexed[j]!.id)?.add(indexed[i]!.id);
    }
  }

  return adjacency;
}

/**
 * Assign zone colours so no two territories that share a border get the same
 * colour. Falls back to id-hash only when the local neighbourhood exhausts
 * the palette (should not happen with 12 colours on this map).
 */
export function assignTerritoryColors(
  features: GeoJSON.Feature[]
): Map<string, string> {
  const adjacency = buildAdjacency(features);
  const ids = features
    .map((f) => String(f.properties?.territory_id ?? ''))
    .filter(Boolean);

  const sorted = [...ids].sort((a, b) => {
    const degreeDelta = (adjacency.get(b)?.size ?? 0) - (adjacency.get(a)?.size ?? 0);
    if (degreeDelta !== 0) return degreeDelta;
    return a.localeCompare(b);
  });

  const assigned = new Map<string, string>();
  for (const id of sorted) {
    const blocked = new Set(
      [...(adjacency.get(id) ?? [])]
        .map((neighborId) => assigned.get(neighborId))
        .filter((color): color is string => Boolean(color))
    );

    const color =
      ZONE_PALETTE.find((candidate) => !blocked.has(candidate)) ??
      ZONE_PALETTE[paletteIndex(id)]!;

    assigned.set(id, color);
  }

  return assigned;
}
