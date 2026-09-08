import { GeoJSONSource, Layer } from '@maplibre/maplibre-react-native';
import { smoothTrail, RUN_TRAIL_COLOR } from './smoothTrail';
import { memo, useMemo } from 'react';

export const TrailLayers = memo(function TrailLayers({ data, economy }: { data: GeoJSON.FeatureCollection<GeoJSON.LineString>; economy: boolean }) {
  const curved = useMemo(() => smoothTrail(data, 8, economy ? 2304 : 4608), [data, economy]);
  const color = RUN_TRAIL_COLOR;
  if (!data.features.length) return null;
  return <GeoJSONSource id="run-trail" data={curved} lineMetrics tolerance={0.1}>
    {!economy && <Layer beforeId="hud-trail-anchor" id="run-trail-halo" type="line" minzoom={14} layout={{ 'line-cap': 'round', 'line-join': 'round' }} paint={{ 'line-color': color, 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 10, 17, 16], 'line-blur': 4, 'line-opacity': 0.22 }} />}
    <Layer beforeId="hud-trail-anchor" id="run-trail-body" type="line" layout={{ 'line-cap': 'round', 'line-join': 'round' }} paint={{ 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 2, 15, 5, 18, 7], 'line-gradient': ['interpolate', ['linear'], ['line-progress'], 0, '#00ACCF', 0.65, color, 1, '#AEF8FF'], 'line-opacity': 0.92 }} />
    {!economy && <Layer beforeId="hud-trail-anchor" id="run-trail-core" type="line" minzoom={15} layout={{ 'line-cap': 'round', 'line-join': 'round' }} paint={{ 'line-color': '#DFFFFF', 'line-width': 1.2, 'line-opacity': 0.7 }} />}
  </GeoJSONSource>;
});
