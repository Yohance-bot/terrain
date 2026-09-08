import type { MapRef } from '@maplibre/maplibre-react-native';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { MAP_STYLE } from '@/constants/config';
import { buildRoofDetails, geometryKey } from './worldGeometry';

const ROAD_LAYERS = (MAP_STYLE.layers as { id: string; type: string }[]).filter(l => l.type === 'line' && /^(road|bridge|tunnel)_/.test(l.id) && !/casing|centerline|rail|hatching|arrow/.test(l.id)).map(l => l.id);
const EMPTY: GeoJSON.FeatureCollection<GeoJSON.Polygon> = { type: 'FeatureCollection', features: [] };
/** Loaded vector geometry only. No extra map provider or GPS upload. Native
 * queries are bounded to one batch every 3/6 seconds, with one batch in flight. */
export function useWorldFeatures(map: RefObject<MapRef | null>, ready: boolean, active: boolean, economy: boolean, zoom: number, runId: string | null) {
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
    let alive = true;
    let lastView = '', lastQueryAt = 0;
    const update = async () => {
      if (running.current || !map.current || zoomRef.current < 14) return;
      running.current = true;
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
        const next = buildRoofDetails(buildings, view.center, economy, view.bounds);
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
    void update();
    const timer = setInterval(() => void update(), economy ? 6000 : 3000);
    return () => { alive = false; clearInterval(timer); };
  }, [map, ready, active, economy, runId]);
  return { roads, details };
}
