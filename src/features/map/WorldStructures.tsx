import { GeoJSONSource, Layer } from '@maplibre/maplibre-react-native';
import { memo } from 'react';
import type { lightingPalette } from '@/features/hud/lighting';
import type { ExpressionSpecification } from '@maplibre/maplibre-gl-style-spec';
import { BUILDING_HEIGHT, ROOF_DECK } from './worldGeometry';

/**
 * How present the massing is.
 *
 * Colours, heights and materials are untouched; this only decides how much the
 * buildings assert themselves against the streets and territory beneath them.
 * One value across all three extrusion layers, because facades and roofs fading
 * by different amounts would separate them instead of receding together.
 *
 * A fixed per-layer opacity is the only kind MapLibre supports here: the paint
 * property is not data-driven, which is why territory tinting is baked into the
 * colour instead.
 */
const STRUCTURE_OPACITY = 0.62;

export const WorldStructures = memo(function WorldStructures({ details, palette, facadeTint }: { details: GeoJSON.FeatureCollection<GeoJSON.Polygon>; facadeTint: ExpressionSpecification | string; palette: ReturnType<typeof lightingPalette> }) {
  return <>
    <Layer id="world-building-footprints" source="openmaptiles" source-layer="building" type="fill" beforeId="hud-base-anchor" minzoom={13} maxzoom={16} paint={{ 'fill-color': palette.building, 'fill-outline-color': palette.roofAccent }} />
    <Layer id="world-buildings" source="openmaptiles" source-layer="building" type="fill-extrusion" beforeId="hud-base-anchor" minzoom={16}
      paint={{ 'fill-extrusion-color': facadeTint, 'fill-extrusion-height': BUILDING_HEIGHT, 'fill-extrusion-base': 0, 'fill-extrusion-opacity': STRUCTURE_OPACITY, 'fill-extrusion-vertical-gradient': true }} />
    <Layer id="world-roof-rims" source="openmaptiles" source-layer="building" type="fill-extrusion" beforeId="hud-base-anchor" minzoom={16}
      paint={{ 'fill-extrusion-color': palette.roof, 'fill-extrusion-base': BUILDING_HEIGHT, 'fill-extrusion-height': ['+', BUILDING_HEIGHT, ROOF_DECK], 'fill-extrusion-opacity': STRUCTURE_OPACITY }} />
    <GeoJSONSource id="world-roof-details" data={details}>
      <Layer id="world-roof-sculptures" type="fill-extrusion" beforeId="hud-base-anchor" minzoom={16}
        paint={{ 'fill-extrusion-base': ['get', 'base'], 'fill-extrusion-height': ['get', 'height'], 'fill-extrusion-color': ['coalesce', ['get', 'color'], ['match', ['get', 'tone'], 'accent', palette.roofAccent, 'aqua', palette.roofAccent, 'garden', palette.park, 'panel', palette.panel, 'door', palette.doorway, 'clay', '#E4D3C4', 'slate', palette.structure, palette.roof]], 'fill-extrusion-opacity': STRUCTURE_OPACITY, 'fill-extrusion-vertical-gradient': true }} />
    </GeoJSONSource>
  </>;
});
