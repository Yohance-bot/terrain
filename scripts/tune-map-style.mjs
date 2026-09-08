import { readFile, writeFile } from 'node:fs/promises';

const STYLE_PATH = new URL('../assets/map/liberty-run.json', import.meta.url);

const style = JSON.parse(await readFile(STYLE_PATH, 'utf8'));

style.metadata = {
  ...(style.metadata ?? {}),
  'run:fork': 'terrarun-garden-city-v6',
  'run:description': 'Deterministic OpenFreeMap Liberty fork for the Run game map',
};

const layersById = new Map(style.layers.map((layer) => [layer.id, layer]));

const ROAD_WIDTHS = JSON.parse(await readFile(new URL('../assets/map/road-widths.json', import.meta.url), 'utf8'));

function roadCategory(id) {
  if (id.includes('path') || id.includes('pedestrian')) return 'path';
  if (id.includes('service') || id.includes('track')) return 'service';
  if (id.includes('link')) return 'link';
  if (id.includes('minor') || id.includes('street')) return 'minor';
  if (id.includes('secondary') || id.includes('tertiary')) return 'secondary';
  if (id.includes('trunk') || id.includes('primary')) return 'primary';
  return 'motorway';
}

function zoomWidth(stops) {
  return ['interpolate', ['linear'], ['zoom'], ...stops];
}

function roadSurfaceColor(id) {
  if (/path|pedestrian/.test(id)) return '#C9F2E1';
  if (/motorway|trunk|primary/.test(id)) return '#FFE3A1';
  return '#FFF2D4';
}

for (const layer of style.layers) {
  if (!/^(road|bridge|tunnel)_/.test(layer.id) || layer.type !== 'line') continue;
  if (/rail|hatching|arrow/.test(layer.id)) continue;

  layer.layout = {
    ...(layer.layout ?? {}),
    'line-cap': layer.id.includes('centerline') ? 'butt' : 'round',
    'line-join': 'round',
  };

  if (!layer.paint) layer.paint = {};

  if (layer.id.includes('centerline')) {
    layer.filter = layersById.get(layer.id.replace('_centerline', ''))?.filter ?? layer.filter;
    layer.paint['line-color'] = '#D5B980';
    layer.paint['line-opacity'] = 0.82;
    continue;
  }

  const isCasing = layer.id.includes('casing');
  if (isCasing) {
    layer.paint['line-color'] = '#5C948B';
  } else {
    layer.paint['line-color'] = roadSurfaceColor(layer.id);
  }

  if (layer.id.startsWith('tunnel_')) {
    layer.paint['line-opacity'] = isCasing ? 0.7 : 0.78;
  }

  const widths = ROAD_WIDTHS[roadCategory(layer.id)];
  layer.paint['line-width'] = zoomWidth(isCasing ? widths.casing : widths.surface);
}

style.metadata['run:road-width-revision'] = 3;
style.metadata['run:structure-revision'] = 2;

Object.assign(layersById.get('background')?.paint ?? {}, {
  'background-color': '#E9EFE6',
});
Object.assign(layersById.get('park')?.paint ?? {}, {
  'fill-color': '#70CA64',
  'fill-opacity': 0.94,
  'fill-outline-color': '#3B9844',
});
Object.assign(layersById.get('park_outline')?.paint ?? {}, {
  'line-color': '#3B9844',
  'line-opacity': 0.9,
  'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.8, 14, 1.8, 17, 3.5],
});
Object.assign(layersById.get('landcover_wood')?.paint ?? {}, {
  'fill-color': '#4EAD49',
  'fill-opacity': 0.62,
});
Object.assign(layersById.get('landcover_grass')?.paint ?? {}, {
  'fill-color': '#87D674',
  'fill-opacity': 0.64,
});

// Structures are owned by the runtime WorldStructures component. Avoid duplicates.
const structureLayerIds = new Set([
  'building',
  'building-3d',
  'game-structure-body',
  'game-structure-roof',
]);
style.layers = style.layers.filter((layer) => !structureLayerIds.has(layer.id));

const parkOutlineIndex = style.layers.findIndex((layer) => layer.id === 'park_outline');
if (parkOutlineIndex >= 0 && !layersById.has('park_highlight')) {
  style.layers.splice(parkOutlineIndex + 1, 0, {
    id: 'park_highlight',
    type: 'line',
    source: 'openmaptiles',
    'source-layer': 'park',
    paint: {
      'line-color': '#B7EAA7',
      'line-opacity': 0.72,
      'line-width': ['interpolate', ['linear'], ['zoom'], 12, 0.4, 15, 0.8, 17, 1.25],
    },
  });
}

style.light = { anchor: 'viewport', color: '#FFF4DC', intensity: 0.42, position: [1.5, 210, 35] };
style.metadata['run:world-revision'] = 1;

await writeFile(STYLE_PATH, `${JSON.stringify(style, null, 2)}\n`);
