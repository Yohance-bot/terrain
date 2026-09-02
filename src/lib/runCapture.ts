import {
  LOOP_CLOSURE_DISTANCE_M,
  LOOP_MIN_AREA_M2,
  LOOP_MIN_DISTANCE_M,
  TRAVERSAL_GRID_METRES,
  TRAVERSAL_MAX_SEGMENT_METRES,
} from '@/constants/config';
import { haversineMetres } from '@/lib/geo';
import type { GeoCoord } from '@/lib/gpsClean';

export type LoopCandidate = {
  closed: boolean;
  areaM2: number;
  distanceM: number;
  polygon: GeoJSON.Feature<GeoJSON.Polygon> | null;
};

function metresPerDegreeLon(latitude: number) {
  return 111_320 * Math.cos((latitude * Math.PI) / 180);
}

function isValidCoordinate(point: GeoCoord): boolean {
  const [lon, lat] = point;
  return Number.isFinite(lon) && Number.isFinite(lat)
    && lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90;
}

function pathDistanceM(path: GeoCoord[]) {
  let distance = 0;
  for (let index = 1; index < path.length; index++) {
    const [lonA, latA] = path[index - 1]!;
    const [lonB, latB] = path[index]!;
    distance += haversineMetres({ lon: lonA, lat: latA }, { lon: lonB, lat: latB });
  }
  return distance;
}

/** POC loop candidate only: the server repeats this decision authoritatively. */
export function detectLoopCandidate(path: GeoCoord[]): LoopCandidate {
  // A single bad location must never reach a native GeoJSON source. Keeping
  // the candidate absent is safer than drawing a corrupt loop.
  if (path.length < 4 || path.some((point) => !isValidCoordinate(point))) {
    return { closed: false, areaM2: 0, distanceM: 0, polygon: null };
  }
  const distanceM = pathDistanceM(path);
  const [startLon, startLat] = path[0]!;
  const [endLon, endLat] = path[path.length - 1]!;
  const closureM = haversineMetres({ lon: startLon, lat: startLat }, { lon: endLon, lat: endLat });
  const latitude = path.reduce((sum, [, lat]) => sum + lat, 0) / path.length;
  const lonScale = metresPerDegreeLon(latitude);
  const latScale = 111_320;
  let twiceArea = 0;
  for (let index = 0; index < path.length; index++) {
    const [lonA, latA] = path[index]!;
    const [lonB, latB] = path[(index + 1) % path.length]!;
    twiceArea += lonA * lonScale * latB * latScale - lonB * lonScale * latA * latScale;
  }
  const areaM2 = Math.abs(twiceArea) / 2;
  const closed =
    distanceM >= LOOP_MIN_DISTANCE_M &&
    closureM <= LOOP_CLOSURE_DISTANCE_M &&
    areaM2 >= LOOP_MIN_AREA_M2;
  return {
    closed,
    areaM2: Math.round(areaM2),
    distanceM: Math.round(distanceM),
    polygon: closed
      ? {
          type: 'Feature',
          properties: {},
          geometry: { type: 'Polygon', coordinates: [[...path, path[0]!]] },
        }
      : null,
  };
}

/**
 * A deduplicated corridor network for rendering: adjacent fixes become one
 * activation segment, quantised to a small grid so a repeat lap does not draw
 * brighter duplicate lines. It is deliberately not presented as a GPS route.
 */
export function buildTraversedRoads(path: GeoCoord[]): GeoJSON.Feature<GeoJSON.MultiLineString> | null {
  const segments: GeoJSON.Position[][] = [];
  const seen = new Set<string>();
  for (let index = 1; index < path.length; index++) {
    const a = path[index - 1]!;
    const b = path[index]!;
    if (!isValidCoordinate(a) || !isValidCoordinate(b) || (a[0] === b[0] && a[1] === b[1])) continue;
    const gap = haversineMetres({ lon: a[0], lat: a[1] }, { lon: b[0], lat: b[1] });
    if (!Number.isFinite(gap) || gap < 1 || gap > TRAVERSAL_MAX_SEGMENT_METRES) continue;
    const latitude = (a[1] + b[1]) / 2;
    const lonScale = metresPerDegreeLon(latitude);
    const keyPoint = ([lon, lat]: GeoCoord) =>
      `${Math.round((lon * lonScale) / TRAVERSAL_GRID_METRES)}:${Math.round((lat * 111_320) / TRAVERSAL_GRID_METRES)}`;
    const left = keyPoint(a);
    const right = keyPoint(b);
    const key = left < right ? `${left}|${right}` : `${right}|${left}`;
    if (seen.has(key)) continue;
    seen.add(key);
    segments.push([a, b]);
  }
  if (!segments.length) return null;
  return {
    type: 'Feature',
    properties: { activated: true },
    geometry: { type: 'MultiLineString', coordinates: segments },
  };
}
