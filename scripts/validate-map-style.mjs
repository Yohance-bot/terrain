import { readFile } from 'node:fs/promises';

const STYLE_PATH = new URL('../assets/map/liberty-run.json', import.meta.url);
const style = JSON.parse(await readFile(STYLE_PATH, 'utf8'));
const errors = [];

function requireValue(condition, message) {
  if (!condition) errors.push(message);
}

requireValue(style.version === 8, 'style.version must be 8');
requireValue(style.sources?.openmaptiles?.type === 'vector', 'openmaptiles vector source is missing');
requireValue(style.sources?.ne2_shaded?.type === 'raster', 'Natural Earth raster source is missing');
requireValue(typeof style.sprite === 'string', 'sprite URL is missing');
requireValue(typeof style.glyphs === 'string', 'glyph URL is missing');
requireValue(Array.isArray(style.layers), 'layers must be an array');
requireValue(style.metadata?.['run:road-width-revision'] === 3, 'road width revision is stale');
requireValue(style.metadata?.['run:structure-revision'] === 2, 'structure revision is stale');

const layers = Array.isArray(style.layers) ? style.layers : [];
const layerIds = new Set(layers.map((layer) => layer.id));
const requiredLayerIds = [
  'background',
  'park',
  'park_outline',
  'park_highlight',
  'road_minor_casing',
  'road_minor',
  'road_secondary_tertiary',
  'road_trunk_primary',
  'road_motorway',
  'bridge_street',
  'tunnel_minor',
];

for (const id of requiredLayerIds) {
  requireValue(layerIds.has(id), `required layer "${id}" is missing`);
}
requireValue(!layerIds.has('building'), 'flat building layer must be removed');
requireValue(!layerIds.has('building-3d'), '3D building layer must be removed');
requireValue(!layerIds.has('game-structure-body'), 'game structure body layer must be removed');
requireValue(!layerIds.has('game-structure-roof'), 'game structure roof layer must be removed');

const extrusionLayers = layers.filter((layer) => layer.type === 'fill-extrusion');
requireValue(extrusionLayers.length === 0, 'style must not contain fill-extrusion layers');

const roadLayers = layers.filter(
  (layer) =>
    /^(road|bridge|tunnel)_/.test(layer.id) &&
    layer.type === 'line' &&
    !/rail|hatching|arrow/.test(layer.id)
);

for (const layer of roadLayers) {
  requireValue(
    layer.layout?.['line-join'] === 'round',
    `${layer.id} must use rounded line joins`
  );
  requireValue(layer.paint?.['line-width'] != null, `${layer.id} must define line-width`);
}

const roadGroups = new Set(roadLayers.map((layer) => layer.id.split('_', 1)[0]));
for (const group of ['road', 'bridge', 'tunnel']) {
  requireValue(roadGroups.has(group), `${group} road group is missing`);
}

if (errors.length > 0) {
  console.error(`Map style validation failed:\n- ${errors.join('\n- ')}`);
  process.exit(1);
}

console.log(`Map style valid: ${layers.length} layers (${roadLayers.length} styled road layers).`);
