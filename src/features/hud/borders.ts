export type SharedBorder = GeoJSON.Feature<GeoJSON.LineString, { left: string; right: string }>;
const key = (p: GeoJSON.Position) => `${p[0]!.toFixed(7)},${p[1]!.toFixed(7)}`;
/** Published mosaic has shared vertices. Only common edges, never whole polygon perimeters. */
export function sharedBorders(features: GeoJSON.Feature[]): SharedBorder[] {
  const index = new Map<string, { id: string; edge: GeoJSON.Position[] }>();
  const result: SharedBorder[] = [];
  for (const feature of features) {
    const id = String(feature.properties?.territory_id ?? feature.id ?? '');
    if (!id) continue;
    const g = feature.geometry;
    const rings = g.type === 'Polygon' ? g.coordinates : g.type === 'MultiPolygon' ? g.coordinates.flat() : [];
    for (const ring of rings) for (let i = 1; i < ring.length; i++) {
      const a = ring[i - 1]!, b = ring[i]!;
      const ka = key(a), kb = key(b);
      if (ka === kb) continue;
      const edgeKey = ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`;
      const previous = index.get(edgeKey);
      if (previous && previous.id !== id) result.push({ type: 'Feature', properties: { left: previous.id, right: id }, geometry: { type: 'LineString', coordinates: previous.edge } });
      else index.set(edgeKey, { id, edge: [a, b] });
    }
  }
  return result;
}

export function selectBorders(edges: SharedBorder[], yours: Set<string>, others: Set<string>, demo = false): GeoJSON.FeatureCollection<GeoJSON.LineString> {
  const selected = edges.filter(e => (yours.has(e.properties.left) && others.has(e.properties.right)) || (yours.has(e.properties.right) && others.has(e.properties.left)));
  // Deterministic fixture derived from a genuine shared edge, labelled in the HUD.
  const pair = edges[0]?.properties;
  return { type: 'FeatureCollection', features: demo && pair ? edges.filter(e => e.properties.left === pair.left && e.properties.right === pair.right) : selected };
}

/** Two tiny adjacent QA territories; never enter ownership, matching or the API. */
export function mockAdjacentBorders(center: [number, number]): GeoJSON.FeatureCollection<GeoJSON.LineString> {
  const [lon, lat] = center;
  const boundary = lon + 0.0006;
  const square = (id: string, west: number, east: number): GeoJSON.Feature<GeoJSON.Polygon> => ({ type: 'Feature', properties: { territory_id: id }, geometry: { type: 'Polygon', coordinates: [[[west, lat - 0.001], [east, lat - 0.001], [east, lat + 0.001], [west, lat + 0.001], [west, lat - 0.001]]] } });
  return { type: 'FeatureCollection', features: sharedBorders([square('demo-you', lon - 0.001, boundary), square('demo-rival', boundary, lon + 0.002)]) };
}
