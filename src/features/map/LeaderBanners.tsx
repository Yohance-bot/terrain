import { memo, useMemo } from 'react';
import { GeoJSONSource, Layer } from '@maplibre/maplibre-react-native';
import type { TerritoryState } from '@/services/api/types';

type Props = { states: TerritoryState[]; capturedAreas?: GeoJSON.FeatureCollection | null; colors: Map<string, string> };

/** Native extrusion poles/flags and collision-managed labels; no React markers. */
export const LeaderBanners = memo(function LeaderBanners({ states, capturedAreas, colors }: Props) {
  const { signs, structures } = useMemo(() => {
    const leaders = states.filter(s => s.owner_device_id && s.owner_display_name && s.label_coordinate).map(s => ({
      id: s.territory_id, name: s.owner_display_name!, point: s.label_coordinate!, color: colors.get(s.territory_id) ?? '#F6BD25',
    }));
    for (const area of capturedAreas?.features ?? []) {
      const p = area.properties;
      if (p?.owner_display_name && Array.isArray(p.label_coordinate)) leaders.push({ id: `loop-${area.id}`, name: p.owner_display_name, point: p.label_coordinate as [number, number], color: p.capture_color ?? '#F6BD25' });
    }
    const signs: GeoJSON.FeatureCollection<GeoJSON.Point> = { type: 'FeatureCollection', features: [] };
    const structures: GeoJSON.FeatureCollection<GeoJSON.Polygon> = { type: 'FeatureCollection', features: [] };
    for (const leader of leaders) {
      const [lon, lat] = leader.point;
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
      signs.features.push({ type: 'Feature', id: leader.id, properties: { name: leader.name, color: leader.color }, geometry: { type: 'Point', coordinates: [lon, lat] } });
      const dx = 1 / (111320 * Math.max(.1, Math.cos(lat * Math.PI / 180))), dy = 1 / 111320;
      const box = (x: number, width: number, depth: number, base: number, height: number, color: string) => {
        const ring = [[lon + x * dx, lat - depth * dy], [lon + (x + width) * dx, lat - depth * dy], [lon + (x + width) * dx, lat + depth * dy], [lon + x * dx, lat + depth * dy]];
        ring.push(ring[0]!);
        structures.features.push({ type: 'Feature', properties: { base, height, color }, geometry: { type: 'Polygon', coordinates: [ring] } });
      };
      box(-.3, .6, .3, 0, 18, '#445455');
      box(.3, 5, .25, 13, 18, leader.color);
      box(-1.1, 2.2, 1.1, 0, .8, leader.color);
    }
    return { signs, structures };
  }, [states, capturedAreas, colors]);
  if (!signs.features.length) return null;
  return <>
    <GeoJSONSource id="leader-banner-structures" data={structures}>
      <Layer id="leader-banner-3d" beforeId="hud-player-anchor" type="fill-extrusion" minzoom={16} paint={{ 'fill-extrusion-color': ['get', 'color'], 'fill-extrusion-base': ['get', 'base'], 'fill-extrusion-height': ['get', 'height'], 'fill-extrusion-opacity': 1 }} />
    </GeoJSONSource>
    <GeoJSONSource id="leader-banner-labels" data={signs}>
      <Layer id="leader-banner-names" beforeId="hud-player-anchor" type="symbol" minzoom={12} layout={{ 'text-field': ['concat', '⚑ ', ['get', 'name']], 'text-size': ['interpolate', ['linear'], ['zoom'], 12, 10, 17, 13], 'text-anchor': 'bottom', 'text-offset': [0, -1.2], 'text-max-width': 12, 'text-padding': 12, 'text-allow-overlap': false }} paint={{ 'text-color': ['get', 'color'], 'text-halo-color': '#162322', 'text-halo-width': 2 }} />
    </GeoJSONSource>
  </>;
});
