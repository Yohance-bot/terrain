import { GeoJSONSource, Layer } from '@maplibre/maplibre-react-native';
import { memo, useEffect, useState } from 'react';
import { useRunCues } from './useRunCues';

export const CueMapLayers = memo(function CueMapLayers({ active, reducedMotion, territories }: { active: boolean; reducedMotion: boolean; territories: GeoJSON.FeatureCollection }) {
  const cue = useRunCues(s => s.cue);
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    if (!cue || !active || Date.now() - cue.createdAt > 3500) { setPhase(0); return; }
    setPhase(1);
    const fade = setTimeout(() => setPhase(2), reducedMotion ? 1600 : 400);
    const end = setTimeout(() => setPhase(0), cue.kind === 'checkpoint' ? 1800 : 3200);
    return () => { clearTimeout(fade); clearTimeout(end); };
  }, [cue, active, reducedMotion]);
  if (!cue || !phase) return null;
  const data: GeoJSON.FeatureCollection = cue.polygon
    ? { type: 'FeatureCollection', features: [cue.polygon] }
    : { type: 'FeatureCollection', features: territories.features.filter(f => cue.territoryIds?.includes(String(f.properties?.territory_id))) };
  return <>
    {cue.kind !== 'checkpoint' && data.features.length > 0 && <GeoJSONSource id="claim-burst" data={data}>
      <Layer beforeId="hud-cue-anchor" id="claim-burst-fill" type="fill" paint={{ 'fill-color': phase === 1 ? '#FFDD8866' : '#FFDD8811', 'fill-color-transition': { duration: reducedMotion ? 0 : 2200 } }} />
      <Layer beforeId="hud-cue-anchor" id="claim-burst-outline" type="line" paint={{ 'line-color': '#FFE09B', 'line-width': reducedMotion ? 3 : phase === 1 ? 7 : 2, 'line-opacity': phase === 1 ? 1 : 0.3, 'line-width-transition': { duration: reducedMotion ? 0 : 1600 }, 'line-opacity-transition': { duration: reducedMotion ? 0 : 1600 } }} />
    </GeoJSONSource>}
    <GeoJSONSource id="checkpoint-location" data={{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: cue.coordinate } }}>
      <Layer beforeId="hud-cue-anchor" id="checkpoint-pulse" type="circle" paint={{ 'circle-radius': reducedMotion ? 12 : phase === 1 ? 12 : 55, 'circle-color': '#80FFDD', 'circle-opacity': 0.05, 'circle-stroke-color': cue.kind === 'checkpoint' ? '#80FFDD' : '#FFE09B', 'circle-stroke-width': 3, 'circle-stroke-opacity': phase === 1 ? 0.9 : 0, 'circle-radius-transition': { duration: reducedMotion ? 0 : 1200 }, 'circle-stroke-opacity-transition': { duration: reducedMotion ? 0 : 1400 } }} />
    </GeoJSONSource>
  </>;
});
