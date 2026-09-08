import { GeoJSONSource, Layer } from '@maplibre/maplibre-react-native';
import { memo } from 'react';
import type { lightingPalette } from '@/features/hud/lighting';
import { BUILDING_HEIGHT } from './worldGeometry';

export const WorldStructures = memo(function WorldStructures({ details, palette, }: { details: GeoJSON.FeatureCollection<GeoJSON.Polygon>; palette: ReturnType<typeof lightingPalette> }) {
  return <>
    <Layer id="world-building-footprints" source="openmaptiles" source-layer="building" type="fill" beforeId="hud-base-anchor" minzoom={13} maxzoom={16} paint={{ 'fill-color': palette.building, 'fill-outline-color': palette.roofAccent }} />
    <Layer id="world-buildings" source="openmaptiles" source-layer="building" type="fill-extrusion" beforeId="hud-base-anchor" minzoom={16}
      paint={{ 'fill-extrusion-color': palette.building, 'fill-extrusion-height': BUILDING_HEIGHT, 'fill-extrusion-base': 0, 'fill-extrusion-opacity': 0.96, 'fill-extrusion-vertical-gradient': true }} />
    <Layer id="world-roof-rims" source="openmaptiles" source-layer="building" type="fill-extrusion" beforeId="hud-base-anchor" minzoom={16}
      paint={{ 'fill-extrusion-color': palette.roof, 'fill-extrusion-base': BUILDING_HEIGHT, 'fill-extrusion-height': ['+', BUILDING_HEIGHT, 0.6], 'fill-extrusion-opacity': 1 }} />
    <GeoJSONSource id="world-roof-details" data={details}>
      <Layer id="world-roof-sculptures" type="fill-extrusion" beforeId="hud-base-anchor" minzoom={16}
        paint={{ 'fill-extrusion-base': ['get', 'base'], 'fill-extrusion-height': ['get', 'height'], 'fill-extrusion-color': ['match', ['get', 'tone'], 'aqua', palette.roofAccent, 'garden', palette.park, 'clay', '#D6A68B', 'slate', palette.casing, palette.roof], 'fill-extrusion-opacity': 1, 'fill-extrusion-vertical-gradient': true }} />
    </GeoJSONSource>
  </>;
});
