import type { ExpressionSpecification } from '@maplibre/maplibre-gl-style-spec';
import widths from '../../../assets/map/road-widths.json';
import type { lightingPalette } from '../hud/lighting';

export function roadCategory(id: string): keyof typeof widths {
  if (/path|pedestrian|footway|cycleway/.test(id)) return 'path';
  if (/service|track/.test(id)) return 'service';
  if (/link/.test(id)) return 'link';
  if (/minor|street|residential|living_street/.test(id)) return 'minor';
  if (/secondary|tertiary/.test(id)) return 'secondary';
  if (/trunk|primary/.test(id)) return 'primary';
  return 'motorway';
}
export function roadPaintColor(id: string, palette: ReturnType<typeof lightingPalette>) {
  if (/centerline/.test(id)) return palette.roadMarking;
  if (/casing/.test(id)) return palette.casing;
  const category = roadCategory(id);
  return category === 'path' ? palette.path : category === 'primary' || category === 'motorway' ? palette.avenue : palette.road;
}
/** Use the same zoom widths for street illumination as for the actual basemap. */
export const illuminatedRoadWidth = ['interpolate', ['linear'], ['zoom'], ...[12, 14, 16, 18, 20].flatMap(zoom => [zoom,
  ['match', ['get', 'roadClass'], ...Object.entries(widths).flatMap(([category, values]) => {
    const stops = values.surface;
    let width = stops[1]!;
    for (let i = 0; i < stops.length - 2; i += 2) {
      if (zoom >= stops[i]!) width = stops[i + 1]! + (stops[i + 3]! - stops[i + 1]!) * Math.min(1, (zoom - stops[i]!) / (stops[i + 2]! - stops[i]!));
    }
    return [category, Math.max(1.5, width)];
  }), 6],
])] as ExpressionSpecification;
