import { Layer, type LayerProps } from '@maplibre/maplibre-react-native';
import type { LayerSpecification } from '@maplibre/maplibre-gl-style-spec';
import { memo, useMemo } from 'react';
import { MAP_STYLE } from '@/constants/config';
import type { lightingPalette } from '@/features/hud/lighting';
import { groundBorderLayers } from './groundBorders';

const STYLE_LAYERS = MAP_STYLE.layers as LayerSpecification[];

/** Kerbs along the streets and outlines around the buildings. See `groundBorders`. */
export const GroundBorders = memo(function GroundBorders({ palette }: { palette: ReturnType<typeof lightingPalette> }) {
  const { kerbs, building } = useMemo(() => groundBorderLayers(STYLE_LAYERS, palette), [palette]);
  return <>
    {kerbs.map(({ layer, beforeId }) => <Layer key={layer.id} beforeId={beforeId} {...layer as LayerProps} />)}
    {/* Mounted ahead of the structures, so it lands beneath them at the anchor. */}
    <Layer key={building.id} beforeId="hud-base-anchor" {...building as LayerProps} />
  </>;
});
