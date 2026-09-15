import { Platform } from 'react-native';
import { ANDROID_WORLD_BUDGET, ANDROID_WORLD_INTERVAL_MS, ANDROID_WORLD_BATCH_SIZE, nearestBuildings, buildInBatches } from './androidPerformance';
import type { MapRef } from '@maplibre/maplibre-react-native';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { buildingTerritoryPaint } from './territoryAppearance';
import type { ExpressionSpecification } from '@maplibre/maplibre-gl-style-spec';
import { MAP_STYLE } from '@/constants/config';
import { buildRoofDetails, geometryKey } from './worldGeometry';

const ROAD_LAYERS = (MAP_STYLE.layers as { id: string; type: string }[]).filter(l => l.type === 'line' && /^(road|bridge|tunnel)_/.test(l.id) && !/casing|centerline|rail|hatching|arrow/.test(l.id)).map(l => l.id);
const EMPTY: GeoJSON.FeatureCollection<GeoJSON.Polygon> = { type: 'FeatureCollection', features: [] };
/** Loaded vector geometry only. No extra map provider or GPS upload. Native
 * queries are bounded to one batch every 3/6 seconds, with one batch in flight. */
export function useWorldFeatures(map: RefObject<MapRef | null>, ready: boolean, active: boolean, economy: boolean, zoom: number, runId: string | null, territories: GeoJSON.Feature[], buildingColor: string, lastGesture?: RefObject<number>) {
  const [facadeTint, setFacadeTint] = useState<ExpressionSpecification | string>(buildingColor);
  const [roads, setRoads] = useState<GeoJSON.Feature[]>([]);
  const [details, setDetails] = useState(EMPTY);
  const roadCache = useRef(new Map<string, GeoJSON.Feature>());
  const running = useRef(false);
  const roadRun = useRef(runId);
  const zoomRef = useRef(zoom); zoomRef.current = zoom;
  useEffect(() => {
    if (roadRun.current !== runId) { roadRun.current = runId; roadCache.current.clear(); setRoads([]); }
  }, [runId]);
  useEffect(() => {
    if (!ready || !active) return;
    const android = Platform.OS === 'android';
    let alive = true;
    let lastView = '', lastQueryAt = 0;
    const update = async () => {
      if (android && Date.now() - (lastGesture?.current ?? 0) < 500) return;
      if (running.current || !map.current || zoomRef.current < 14) return;
      running.current = true;
      const gestureAtStart = lastGesture?.current ?? 0;
      try {
        const view = await map.current.getViewState();
        if (!alive) return;
        const viewKey = `${view.center.map(n => n.toFixed(4)).join(':')}:${view.zoom.toFixed(1)}:${Math.round(view.bearing / 5)}:${Math.round(view.pitch / 5)}`;
        if (viewKey === lastView && Date.now() - lastQueryAt < 15000) return;
        const [buildings, streets] = await Promise.all([
          zoomRef.current >= 16 ? map.current.queryRenderedFeatures({ layers: ['world-buildings'] }) : Promise.resolve([]),
          runId ? map.current.queryRenderedFeatures({ layers: ROAD_LAYERS }) : Promise.resolve([]),
        ]);
        if (!alive) return;
        lastView = viewKey; lastQueryAt = Date.now();
        const selected = android ? nearestBuildings(buildings, view.center) : buildings;
        let next: GeoJSON.FeatureCollection<GeoJSON.Polygon>;
        if (android) {
          const cancelled = () => !alive || (lastGesture?.current ?? 0) !== gestureAtStart;
          const features = await buildInBatches(selected, ANDROID_WORLD_BATCH_SIZE,
            (batch, remaining) => buildRoofDetails(batch, view.center, economy, view.bounds, territories, { ...ANDROID_WORLD_BUDGET, maxDetails: remaining }).features,
            ANDROID_WORLD_BUDGET.maxDetails, cancelled);
          if (!features) { lastView = ''; return; }
          next = { type: 'FeatureCollection', features };
        } else next = buildRoofDetails(buildings, view.center, economy, view.bounds, territories);
        const tint = buildingTerritoryPaint(selected, territories, buildingColor);
        setFacadeTint(old => JSON.stringify(old) === JSON.stringify(tint) ? old : tint);
        setDetails(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next);
        if (runId) {
          let changed = false;
          for (const feature of streets) {
            const lines = feature.geometry.type === 'LineString' ? [feature.geometry.coordinates] : feature.geometry.type === 'MultiLineString' ? feature.geometry.coordinates : [];
            for (const coordinates of lines) {
              if (coordinates.length > 2048) continue;
              const part: GeoJSON.Feature<GeoJSON.LineString> = { type: 'Feature', properties: feature.properties, geometry: { type: 'LineString', coordinates } };
              const key = geometryKey(part) + String(part.properties?.class);
              if (!roadCache.current.has(key)) { roadCache.current.set(key, part); changed = true; }
            }
          }
          // Bound memory and matching work during long runs. Older unloaded
          // streets safely fall back to GPS instead of speculative matching.
          let vertices = [...roadCache.current.values()].reduce((n, f) => n + (f.geometry.type === 'LineString' ? f.geometry.coordinates.length : 0), 0);
          while (roadCache.current.size > 1800 || vertices > 12000) {
            const key = roadCache.current.keys().next().value!;
            const feature = roadCache.current.get(key)!;
            if (feature.geometry.type === 'LineString') vertices -= feature.geometry.coordinates.length;
            roadCache.current.delete(key);
          }
          if (changed) setRoads([...roadCache.current.values()]);
        }
      } catch { /* Offline/missing vector tiles retain the last valid scene. */ }
      finally { running.current = false; }
    };
    // Let the Android page transition finish before querying native geometry.
    const kickoff = android ? setTimeout(() => void update(), 350) : null;
    if (!android) void update();
    const timer = setInterval(() => void update(), android ? ANDROID_WORLD_INTERVAL_MS : economy ? 6000 : 3000);
    return () => { alive = false; if (kickoff) clearTimeout(kickoff); clearInterval(timer); };
  }, [map, ready, active, economy, runId, territories, buildingColor, lastGesture]);
  return { roads, details, facadeTint };
}
