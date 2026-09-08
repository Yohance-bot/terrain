import { Layer, type LayerProps } from '@maplibre/maplibre-react-native';
import type { LayerSpecification } from '@maplibre/maplibre-gl-style-spec';
import { memo, useMemo } from 'react';
import { roadPaintColor } from '@/features/map/roadStyle';
import { MAP_STYLE } from '@/constants/config';
import type { lightingPalette } from './lighting';

const BASE_LAYERS = (MAP_STYLE.layers as LayerSpecification[]).filter(l => !l.id.startsWith('hud-') && (l.type === 'background' || l.type === 'fill' || l.type === 'line' || l.type === 'symbol'));
/** Native Layer binds existing style IDs; the style object and ordering never swap. */
export const ThemeLayers = memo(function ThemeLayers({ palette, reducedMotion }: { palette: ReturnType<typeof lightingPalette>; reducedMotion: boolean }) {
  const layers = useMemo(() => BASE_LAYERS.map(layer => {
    const duration = reducedMotion ? 0 : 5000;
    if (layer.type === 'background') return { ...layer, paint: { ...layer.paint, 'background-color': palette.background, 'background-color-transition': { duration } } };
    if (layer.type === 'fill') return { ...layer, paint: { ...layer.paint, 'fill-color': /water/.test(layer.id) ? palette.water : /park|wood|grass|cemetery/.test(layer.id) ? palette.park : palette.land, 'fill-color-transition': { duration } } };
    if (layer.type === 'line') return { ...layer, paint: { ...layer.paint, 'line-color': /^(road|bridge|tunnel)_/.test(layer.id) && !/rail|hatching|arrow/.test(layer.id) ? roadPaintColor(layer.id, palette) : /water/.test(layer.id) ? palette.water : palette.casing, 'line-color-transition': { duration } } };
    if (layer.type === 'symbol') return { ...layer, layout: { ...layer.layout, ...(/^poi/.test(layer.id) ? { visibility: 'none' as const } : {}), ...(/road.*name|highway.*name|road_label/.test(layer.id) ? { 'text-size': ['interpolate', ['linear'], ['zoom'], 14, 10, 17, 11, 20, 13], 'text-letter-spacing': 0.03, 'symbol-spacing': 350 } : {}) }, paint: { ...layer.paint, 'text-color': palette.label, 'text-halo-color': palette.halo, 'text-color-transition': { duration }, 'text-halo-color-transition': { duration } } };
    return layer;
  }), [palette, reducedMotion]);
  return <>{layers.map(layer => <Layer key={layer.id} {...layer as LayerProps} />)}</>;
});
