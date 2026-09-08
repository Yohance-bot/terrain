import { GeoJSONSource, Layer } from '@maplibre/maplibre-react-native';
import { smoothTrail, RUN_TRAIL_COLOR } from '@/features/hud/smoothTrail';
import { memo, useMemo } from 'react';
import { illuminatedRoadWidth } from './roadStyle';

export const StreetTrailLayers = memo(function StreetTrailLayers({ streets, unmatched, economy }: {
  streets: GeoJSON.FeatureCollection<GeoJSON.LineString>; unmatched: GeoJSON.FeatureCollection<GeoJSON.LineString>; economy: boolean;
}) {
  const curvedStreets = useMemo(() => smoothTrail(streets, 2, 6144), [streets]);
  const curvedFallback = useMemo(() => smoothTrail(unmatched, 8, 4608), [unmatched]);
  const color = RUN_TRAIL_COLOR;
  return <>
    <GeoJSONSource id="run-lit-streets" data={curvedStreets} tolerance={0.1}>
      {!economy && <Layer id="run-street-aura" beforeId="hud-trail-anchor" type="line" minzoom={14} layout={{ 'line-cap': 'round', 'line-join': 'round' }} paint={{ 'line-color': color, 'line-width': illuminatedRoadWidth, 'line-blur': 3, 'line-opacity': 0.25 }} />}
      <Layer id="run-street-surface" beforeId="hud-trail-anchor" type="line" layout={{ 'line-cap': 'round', 'line-join': 'round' }} paint={{ 'line-color': color, 'line-width': illuminatedRoadWidth, 'line-opacity': 0.82 }} />
      <Layer id="run-street-ribbon" beforeId="hud-trail-anchor" type="line" minzoom={15} layout={{ 'line-cap': 'round', 'line-join': 'round' }} paint={{ 'line-color': '#DFFFFF', 'line-width': 1.2, 'line-opacity': 0.9 }} />
    </GeoJSONSource>
    <GeoJSONSource id="run-unmatched-trace" data={curvedFallback} tolerance={0.1}>
      <Layer id="run-unmatched-trace-line" beforeId="hud-trail-anchor" type="line" layout={{ 'line-cap': 'round' }} paint={{ 'line-color': color, 'line-width': 3, 'line-dasharray': [2, 2], 'line-opacity': 0.85 }} />
    </GeoJSONSource>
  </>;
});
