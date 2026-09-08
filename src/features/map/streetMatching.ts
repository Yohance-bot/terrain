import { roadCategory } from './roadStyle';
type Point = [number, number];
type Edge = { a: Point; b: Point; start: Point; end: Point; roadClass: string; id: number };
type Snap = { point: Point; geo: Point; t: number; distance: number; edge: Edge; score: number };
const indexCache = new WeakMap<GeoJSON.Feature[], { latitude: number; cells: Map<string, Edge[]> }>();
const distance = (a: Point, b: Point) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const mix = (a: Point, b: Point, t: number): Point => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
const valid = (p: GeoJSON.Position) => Number.isFinite(p[0]) && Number.isFinite(p[1]) && Math.abs(p[0]!) <= 180 && Math.abs(p[1]!) < 85;
export const STREET_VERTEX_BUDGET = 3072;

/** Local presentation matching against loaded street geometry. Never changes GPS,
 * distance, submission or ownership. Ambiguous/off-street portions stay GPS traces.
 */
export function illuminateStreets(route: GeoJSON.FeatureCollection<GeoJSON.LineString>, roads: GeoJSON.Feature[]): { streets: GeoJSON.FeatureCollection<GeoJSON.LineString>; unmatched: GeoJSON.FeatureCollection<GeoJSON.LineString> } {
  const streets: GeoJSON.Feature<GeoJSON.LineString>[] = [], unmatched: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  const latitude = route.features[0]?.geometry.coordinates[0]?.[1] ?? 0;
  const xScale = 111320 * Math.cos(latitude * Math.PI / 180);
  const project = (p: GeoJSON.Position): Point => [p[0]! * xScale, p[1]! * 111320];
  const cached = indexCache.get(roads);
  const reuse = cached?.latitude === latitude;
  const cells = reuse ? cached.cells : new Map<string, Edge[]>(); const dedupe = new Set<string>();
  let edges = 0;
  for (const feature of reuse ? [] : roads) {
    const lines = feature.geometry.type === 'LineString' ? [feature.geometry.coordinates] : feature.geometry.type === 'MultiLineString' ? feature.geometry.coordinates : [];
    const roadClass = roadCategory(String(feature.properties?.class ?? 'minor'));
    for (const line of lines) for (let i = 1; i < line.length && edges < 12000; i++) {
      const start = line[i - 1] as Point, end = line[i] as Point;
      if (!valid(start) || !valid(end) || Math.abs(start[0] - end[0]) > 1) continue;
      const a = project(start), b = project(end), length = distance(a, b);
      if (length < 0.2 || length > 2000) continue;
      const key = [start.join(','), end.join(',')].sort().join('|') + roadClass;
      if (dedupe.has(key)) continue; dedupe.add(key);
      const edge = { a, b, start, end, roadClass, id: edges++ };
      // Index the segment along its length, avoiding huge bounding-box grids.
      const count = Math.ceil(length / 40); const used = new Set<string>();
      for (let k = 0; k <= count; k++) {
        const p = mix(a, b, k / count), cell = `${Math.floor(p[0] / 60)}:${Math.floor(p[1] / 60)}`;
        if (used.has(cell)) continue; used.add(cell);
        const bucket = cells.get(cell) ?? []; bucket.push(edge); cells.set(cell, bucket);
      }
    }
  }
  if (!reuse) indexCache.set(roads, { latitude, cells });
  const snap = (geo: Point, heading: Point): Snap | null => {
    const p = project(geo), cx = Math.floor(p[0] / 60), cy = Math.floor(p[1] / 60);
    const seen = new Set<number>(); const candidates: Snap[] = [];
    for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (const edge of cells.get(`${cx + x}:${cy + y}`) ?? []) {
      if (seen.has(edge.id)) continue; seen.add(edge.id);
      const dx = edge.b[0] - edge.a[0], dy = edge.b[1] - edge.a[1], length = Math.hypot(dx, dy);
      const t = Math.max(0, Math.min(1, ((p[0] - edge.a[0]) * dx + (p[1] - edge.a[1]) * dy) / length ** 2));
      const point = mix(edge.a, edge.b, t), d = distance(p, point);
      if (d > 22) continue;
      const alignment = Math.abs((heading[0] * dx + heading[1] * dy) / (Math.hypot(...heading) * length || 1));
      candidates.push({ point, geo: mix(edge.start, edge.end, t), t, distance: d, edge, score: d + (1 - alignment) * 9 });
    }
    candidates.sort((a, b) => a.score - b.score);
    const best = candidates[0]; if (!best) return null;
    // Parallel streets with similarly plausible offsets must not be guessed.
    if (candidates.some(c => c.edge.id !== best.edge.id && c.score - best.score < 2.5 && distance(c.point, best.point) > 7)) return null;
    return best;
  };
  let vertices = 0, observations = 0;
  const append = (list: GeoJSON.Feature<GeoJSON.LineString>[], points: Point[], roadClass = 'minor') => {
    if (vertices + points.length > STREET_VERTEX_BUDGET || distance(project(points[0]!), project(points.at(-1)!)) < 0.1) return;
    const last = list.at(-1);
    if (last && last.properties?.roadClass === roadClass && distance(project(last.geometry.coordinates.at(-1)!), project(points[0]!)) < 0.1) {
      last.geometry.coordinates.push(...points.slice(1)); vertices += points.length - 1;
    } else { list.push({ type: 'Feature', properties: { roadClass }, geometry: { type: 'LineString', coordinates: points } }); vertices += points.length; }
  };
  for (const feature of route.features) {
    let previous: Snap | null = null; let previousGeo: Point | null = null;
    for (let i = 1; i < feature.geometry.coordinates.length && vertices < STREET_VERTEX_BUDGET && observations < 9000; i++) {
      const a = feature.geometry.coordinates[i - 1] as Point, b = feature.geometry.coordinates[i] as Point;
      if (!valid(a) || !valid(b) || Math.abs(a[0] - b[0]) > 1) { previous = null; previousGeo = null; continue; }
      const pa = project(a), pb = project(b), heading: Point = [pb[0] - pa[0], pb[1] - pa[1]];
      const steps = Math.min(200, Math.max(1, Math.ceil(distance(pa, pb) / 10)));
      for (let j = 0; j <= steps && vertices < STREET_VERTEX_BUDGET && observations++ < 9000; j++) {
        const geo = mix(a, b, j / steps), current = snap(geo, heading);
        if (previousGeo && distance(project(previousGeo), project(geo)) > 0.1) {
          let connected = false;
          if (previous && current) {
            if (previous.edge.id === current.edge.id) { append(streets, [previous.geo, current.geo], current.edge.roadClass); connected = true; }
            else {
              // Follow real vertices through a junction; never draw a diagonal
              // between unrelated parallel roads or light an entire unseen block.
              const ends = [previous.edge.start, previous.edge.end]; const nextEnds = [current.edge.start, current.edge.end];
              for (const end of ends) for (const nextEnd of nextEnds) {
                const join = distance(project(end), project(nextEnd));
                const travel = distance(previous.point, project(end)) + join + distance(project(nextEnd), current.point);
                if (!connected && join < 2 && travel <= distance(project(previousGeo), project(geo)) * 2 + 8) {
                  append(streets, [previous.geo, end], previous.edge.roadClass);
                  append(streets, [nextEnd, current.geo], current.edge.roadClass); connected = true;
                }
              }
            }
          }
          if (!connected) append(unmatched, [previousGeo, geo]);
        }
        previous = current; previousGeo = geo;
      }
    }
  }
  return { streets: { type: 'FeatureCollection', features: streets }, unmatched: { type: 'FeatureCollection', features: unmatched } };
}
