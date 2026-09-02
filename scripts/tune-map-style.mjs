import { readFile, writeFile } from 'node:fs/promises';

const STYLE_PATH = new URL('../assets/map/liberty-run.json', import.meta.url);

const style = JSON.parse(await readFile(STYLE_PATH, 'utf8'));

style.metadata = {
  ...(style.metadata ?? {}),
  'run:fork': 'pokemon-roads-parks-v5',
  'run:description': 'Deterministic OpenFreeMap Liberty fork for the Run game map',
};

const layersById = new Map(style.layers.map((layer) => [layer.id, layer]));

const ROAD_WIDTHS = {
  path: {
    surface: [12, 0.25, 14, 0.8, 16, 1.8, 18, 3.2, 20, 5],
    casing: [12, 0.5, 14, 1.4, 16, 2.8, 18, 4.6, 20, 6.8],
  },
  service: {
    surface: [12, 0, 13, 0.2, 14, 2.1, 16, 5.8, 18, 11, 20, 18],
    casing: [12, 0, 13, 0.7, 14, 3.6, 16, 8, 18, 14, 20, 22],
  },
  link: {
    surface: [10, 0.2, 12, 0.5, 14, 2.6, 16, 6.5, 18, 13, 20, 24],
    casing: [10, 0.8, 12, 1.3, 14, 4.2, 16, 8.8, 18, 16, 20, 28],
  },
  minor: {
    surface: [12, 0, 13, 0.35, 14, 3.2, 16, 8.5, 18, 17, 20, 29],
    casing: [12, 0, 13, 1, 14, 5, 16, 11, 18, 21, 20, 34],
  },
  secondary: {
    surface: [8, 0.25, 10, 0.45, 12, 0.8, 14, 3.8, 16, 9.5, 18, 18.5, 20, 31],
    casing: [8, 0.8, 10, 1, 12, 1.5, 14, 5.7, 16, 12, 18, 22.5, 20, 36],
  },
  primary: {
    surface: [7, 0.4, 10, 0.7, 12, 1.2, 14, 4.5, 16, 11, 18, 21, 20, 34],
    casing: [7, 1, 10, 1.3, 12, 2, 14, 6.5, 16, 14, 18, 25, 20, 40],
  },
  motorway: {
    surface: [5, 0.5, 8, 0.8, 10, 1.1, 12, 1.6, 14, 5.4, 16, 13, 18, 24, 20, 38],
    casing: [5, 1.1, 8, 1.5, 10, 1.9, 12, 2.6, 14, 7.5, 16, 16, 18, 28, 20, 44],
  },
};

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
  if (id.includes('path') || id.includes('pedestrian')) return '#D7DEDC';
  if (id.includes('service') || id.includes('track')) return '#737F84';
  if (id.includes('minor') || id.includes('street')) return '#69757D';
  if (id.includes('secondary') || id.includes('tertiary')) return '#606C74';
  if (id.includes('motorway') || id.includes('trunk') || id.includes('primary')) {
    return '#56616A';
  }
  return '#626E76';
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
    layer.paint['line-color'] = '#EEF2F2';
    layer.paint['line-opacity'] = 0.82;
    continue;
  }

  const isCasing = layer.id.includes('casing');
  if (isCasing) {
    layer.paint['line-color'] = layer.id.startsWith('bridge_') ? '#AEB7BE' : '#B9C1C6';
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

// Drop all building geometry — the game map stays flat for clarity and performance.
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

await writeFile(STYLE_PATH, `${JSON.stringify(style, null, 2)}\n`);
