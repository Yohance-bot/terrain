import { GeoJSONSource, Layer } from '@maplibre/maplibre-react-native';
import { memo } from 'react';
import type { lightingPalette } from '@/features/hud/lighting';
import type { ExpressionSpecification } from '@maplibre/maplibre-gl-style-spec';
import { BUILDING_HEIGHT, ROOF_DECK } from './worldGeometry';
// Shared with the ground borders, which recede with the buildings they outline.
import { STRUCTURE_OPACITY } from './groundBorders';


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
