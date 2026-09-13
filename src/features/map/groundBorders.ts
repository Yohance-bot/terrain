import type { ExpressionSpecification, LayerSpecification, LineLayerSpecification } from '@maplibre/maplibre-gl-style-spec';
// Relative on purpose: the admin console compiles this file too, and there `@/`
// resolves to its own source tree.
import { withAlpha, type lightingPalette } from '../hud/lighting';

/**
 * How present the massing is — and, since the borders belong to the same
 * built world, how present its edges are.
 *
 * Solid. Translucent buildings (0.62 was tried) let the streets show through
 * the facades and read as washed out rather than as a lighter touch. One value
 * for facades, roofs, kerbs and outlines keeps them a single material. A fixed
 * per-layer opacity is the only kind MapLibre supports for extrusions (the
 * paint property is not data-driven), which is why territory tinting is baked
 * into the colour.
 */
export const STRUCTURE_OPACITY = 1;

type Palette = ReturnType<typeof lightingPalette>;

/** Kerbs only appear once streets are wide enough for two edges to separate. */
const KERB_MIN_ZOOM = 15;

const KERB_WIDTH: ExpressionSpecification = ['interpolate', ['linear'], ['zoom'], KERB_MIN_ZOOM, 1, 18, 2.4, 20, 3.4];
// Twice what shows: the line is centred on the footprint and the solid
// building covers its inner half.
const BUILDING_BORDER_WIDTH: ExpressionSpecification = ['interpolate', ['linear'], ['zoom'], KERB_MIN_ZOOM, 1.4, 18, 4.4, 20, 6];

/**
 * The drivable surfaces. Casings and centrelines are decoration on these, rail
 * is not a street, and paths are too narrow for two edges to read as anything
 * but a thicker line. Tunnels are underground.
 */
function isRoadSurface(layer: LayerSpecification): layer is LineLayerSpecification {
  return layer.type === 'line'
    && /^(road|bridge)_/.test(layer.id)
    && !/casing|centerline|rail|hatching|path|pedestrian/.test(layer.id);
}

export type PlacedLayer = { layer: LineLayerSpecification; beforeId: string };

/**
 * Borders for the ground: a kerb along both edges of every street, and an
 * outline around every building's footprint.
 *
 * Each kerb copies its road's own width into `line-gap-width`, so the two edge
 * lines sit exactly on the tarmac's edge at every zoom without a second width
 * table that could drift from the basemap. They are drawn beneath the road
 * surfaces: a crossing street then paints over them, and junctions stay clean
 * instead of being scored through by the edges of the road beneath.
 */
export function groundBorderLayers(styleLayers: LayerSpecification[], palette: Palette): { kerbs: PlacedLayer[]; building: PlacedLayer } {
  const kerbColor = withAlpha(palette.kerb, STRUCTURE_OPACITY);
  const borderColor = withAlpha(palette.edge, STRUCTURE_OPACITY);
  const kerbs: PlacedLayer[] = [];
  // Street and bridge surfaces sit in separate bands of the style; a kerb has to
  // go under the first surface of its own band, or bridges would be edged below
  // the streets they cross.
  const firstSurface = new Map<string, string>();
  for (const layer of styleLayers) {
    if (layer.type !== 'line' || !/^(road|bridge)_/.test(layer.id) || /casing/.test(layer.id)) continue;
    const band = layer.id.split('_')[0]!;
    if (!firstSurface.has(band)) firstSurface.set(band, layer.id);
  }
  for (const layer of styleLayers) {
    if (!isRoadSurface(layer)) continue;
    kerbs.push({
      beforeId: firstSurface.get(layer.id.split('_')[0]!)!,
      layer: {
        id: `ground-kerb-${layer.id}`,
        type: 'line',
        source: layer.source,
        'source-layer': layer['source-layer'],
        ...(layer.filter ? { filter: layer.filter } : {}),
        minzoom: KERB_MIN_ZOOM,
        // Butt caps: a round cap would draw a half-ring across every dead end.
        layout: { 'line-cap': 'butt', 'line-join': 'round' },
        paint: { 'line-color': kerbColor, 'line-width': KERB_WIDTH, 'line-gap-width': layer.paint?.['line-width'] ?? 0 },
      },
    });
  }
  // The outline is anchored in the base style, directly above the last street,
  // bridge or tunnel line — never relative to the building layers. Runtime
  // layers are added in whatever order their native views mount, so "mounted
  // first, therefore lower" does not hold: on a phone the outline landed above
  // the extrusions and drew every footprint straight across the roofs. A base
  // style layer always exists, and everything from here up to the building
  // anchor is labels, so the solid buildings cover the outline's inner half.
  let lastStreet = -1;
  styleLayers.forEach((layer, index) => {
    if (layer.type === 'line' && /^(road|bridge|tunnel)_/.test(layer.id)) lastStreet = index;
  });
  const aboveStreets = styleLayers[lastStreet + 1]!.id;
  return {
    kerbs,
    building: {
      beforeId: aboveStreets,
      layer: {
        id: 'ground-building-borders',
        type: 'line',
        source: 'openmaptiles',
        'source-layer': 'building',
        minzoom: KERB_MIN_ZOOM,
        layout: { 'line-join': 'round' },
        // Centred on the footprint, under the extrusion: the outer half is the
        // border, and the building hides the rest.
        paint: { 'line-color': borderColor, 'line-width': BUILDING_BORDER_WIDTH },
      },
    },
  };
}
