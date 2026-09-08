import { GeoJSONSource, Layer } from '@maplibre/maplibre-react-native';
import { memo, useEffect, useState } from 'react';

export const ContestedBorders = memo(function ContestedBorders({ data, active, reducedMotion, economy, zoom }: {
  data: GeoJSON.FeatureCollection<GeoJSON.LineString>; active: boolean; reducedMotion: boolean; economy: boolean; zoom: number;
}) {
  const [bright, setBright] = useState(false);
  useEffect(() => {
    if (!active || reducedMotion || economy || !data.features.length || zoom < 13) { setBright(false); return; }
    const timer = setInterval(() => setBright(v => !v), 1200);
    return () => clearInterval(timer);
  }, [active, reducedMotion, economy, data, zoom]);
  if (!data.features.length) return null;
  return <GeoJSONSource id="contested-borders" data={data}>
    <Layer beforeId="hud-border-anchor" id="contested-border-pulse" type="line" minzoom={13} layout={{ 'line-cap': 'round', 'line-join': 'round' }} paint={{ 'line-color': '#FFB477', 'line-width': bright ? 5 : 3, 'line-opacity': bright ? 0.95 : 0.45, 'line-width-transition': { duration: 1100 }, 'line-opacity-transition': { duration: 1100 } }} />
    <Layer beforeId="hud-border-anchor" id="contested-border-dashes" type="line" minzoom={13} paint={{ 'line-color': '#FFECD5', 'line-width': 1.5, 'line-dasharray': [2, 2] }} />
  </GeoJSONSource>;
});
