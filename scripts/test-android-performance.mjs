import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
const require = createRequire(import.meta.url);
function loader(stubs = new Map()) {
  const cache = new Map();
  const fileAt = p => ['.ts', '.tsx', '/index.ts'].map(ext => p + ext).find(existsSync);
  function load(file) {
    const path = resolve(file);
    if (cache.has(path)) return cache.get(path).exports;
    const module = { exports: {} }; cache.set(path, module);
    const source = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const localRequire = name => {
      if (stubs.has(name)) return stubs.get(name);
      if (name.startsWith('@/')) return load(fileAt(resolve('src', name.slice(2))));
      if (name.startsWith('.')) return load(fileAt(resolve(dirname(path), name)));
      return require(name);
    };
    vm.runInNewContext(`(function(require,module,exports){${source}\n})`, { console, setTimeout, setInterval: () => 1, clearInterval() {} }, { filename: path })(localRequire, module, module.exports);
    return module.exports;
  }
  return load;
}
const load = loader();
const { nearestBuildings, buildInBatches, ANDROID_WORLD_BUDGET } = load('src/features/map/androidPerformance.ts');
const { buildRoofDetails } = load('src/features/map/worldGeometry.ts');
const buildings = Array.from({ length: 600 }, (_, i) => {
  const lon = 77 + (i % 30) * .0004, lat = 13 + Math.floor(i / 30) * .0004;
  return { type: 'Feature', id: i, properties: { render_height: 14 }, geometry: { type: 'Polygon', coordinates: [[[lon, lat], [lon + .0002, lat], [lon + .0002, lat + .0002], [lon, lat + .0002], [lon, lat]]] } };
});
const selected = nearestBuildings([...buildings, buildings[0]], [77, 13]);
assert.equal(selected.length, 360);
assert.equal(new Set(selected.map(b => b.id)).size, 360);
assert.equal(selected[0].id, 0);
let yields = 0;
const reduced = await buildInBatches(selected, 24, (batch, remaining) => buildRoofDetails(batch, [77, 13], false, undefined, [], { ...ANDROID_WORLD_BUDGET, maxDetails: remaining }).features, 1400, () => false, async () => { yields++; });
assert.ok(yields > 1, 'geometry yields to UI between batches');
assert.ok(reduced.length <= 1400);
const normal = buildRoofDetails(selected, [77, 13]).features;
assert.ok(reduced.length < normal.length);
let cancelled = false, built = 0, turns = 0;
const discarded = await buildInBatches([1, 2, 3, 4], 2, batch => { built += batch.length; return batch; }, 4, () => cancelled, async () => { if (++turns === 2) cancelled = true; });
assert.equal(discarded, null);
assert.equal(built, 2, 'cancelled batches do no further geometry work');
console.log(`Android geometry: ${normal.length} → ${reduced.length} detail polygons for the selected fixture; ${yields} UI yields. Not a device FPS measurement.`);

// Execute the production render callback with native boundaries stubbed. Host
// arrays deliberately throw out of bounds, matching worklets-core (not JS).
function hostArray(a) { return new Proxy(a, { get(target, key) { if (typeof key === 'string' && /^\d+$/.test(key) && Number(key) >= target.length) throw new Error('host array out of bounds'); return Reflect.get(target, key); } }); }
for (const platform of ['android', 'ios']) {
  const callbacks = [], writes = [], shared = [], scenes = [];
  let pauses = 0;
  const matrix = () => ({ translate: () => matrix(), scaling: () => matrix(), rotate: () => matrix() });
  const context = { camera: { setLensProjection() {}, lookAt() {} }, view: { getAspectRatio: () => .5 }, transformManager: { createIdentityMatrix: matrix, setTransform: (root, transform) => writes.push(root.id) }, choreographer: { start() {}, stop() { pauses++; } } };
  const leaf = () => null;
  const Scene = props => { scenes.push(props); return props.children; };
  const jsx = (type, props) => typeof type === 'function' ? type(props) : props;
  const stubs = new Map([
    ['react', { useCallback: fn => fn, useMemo: fn => fn(), useState: initial => [typeof initial === 'function' ? initial() : initial, () => {}], useRef: value => ({ current: value }), useEffect: fn => fn() }],
    ['react/jsx-runtime', { jsx, jsxs: jsx }],
    ['react-native', { Platform: { OS: platform }, View: leaf, StyleSheet: { absoluteFill: {} } }],
    ['react-native-worklets-core', { useSharedValue: initial => { let current = Array.isArray(initial) ? hostArray(initial) : initial; const value = { get value() { return current; }, set value(v) { current = Array.isArray(v) ? hostArray(v) : v; } }; shared.push(value); return value; } }],
    ['react-native-filament', { Animator: leaf, DefaultLight: leaf, FilamentScene: Scene, FilamentView: leaf, ModelInstance: leaf, ModelRenderer: leaf, useFilamentContext: () => context, RenderCallbackContext: { useRenderCallback: fn => callbacks.push(fn) }, useModel: () => ({ state: 'loaded', asset: { getAssetInstances: () => Array.from({ length: 8 }, (_, id) => ({ getRoot: () => ({ id }) })) }, boundingBox: { max: [1, 2, 1], min: [-1, 0, -1], center: [0, 1, 0] } }) }],
    ['@/features/social/useSocial', { useSocial: selector => selector({ friends: [] }) }],
    ['@/features/social/useGhostRace', { useGhostRace: selector => selector({ ghostState: null }) }],
    ['./visibility', { useAvatarVisibility: { setState() {} } }],
    ['../../../assets/avatar/runner.glb', 1],
  ]);
  const player = loader(stubs)('src/features/avatar/PlayerAvatar.tsx');
  const frame = { value: { eye: [0, 100, 0], target: [0, 0, 0], up: [0, 0, -1], yaw: 0, origin: [77, 13], pose: { center: [77, 13], zoom: 17, pitch: 45, bearing: 0 } } };
  player.PlayerAvatar({ camera: { placed: true, frame }, running: false, active: true });
  assert.equal(callbacks.length, 1);
  callbacks[0]();
  assert.equal(writes.length, 8, 'initialize player and hide every unused model once');
  writes.length = 0;
  for (let i = 0; i < 60; i++) callbacks[0]();
  assert.equal(writes.length, platform === 'android' ? 0 : 480, 'Android avoids redundant writes; iOS render path remains unchanged');
  frame.value.yaw = 1;
  writes.length = 0; callbacks[0]();
  assert.equal(writes.length, platform === 'android' ? 1 : 8, 'heading changes still update immediately');
  if (platform === 'android') {
    shared.find(s => typeof s.value === 'boolean').value = false;
    writes.length = 0; callbacks[0]();
    assert.equal(writes.length, 0); assert.equal(pauses, 1);
    assert.equal(scenes[0].shadowing, false);
  } else assert.equal(scenes[0].dynamicResolutionOptions, undefined);
}
console.log('Android render regression: bounded host arrays, cached transforms, immediate headings, hidden-scene pause; iOS path unchanged.');
