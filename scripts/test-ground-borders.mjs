import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';

// Execute the production TypeScript, the same way the other suites do.
const require = createRequire(import.meta.url);
const cache = new Map();
const tsPath = p => (existsSync(p + '.ts') ? p + '.ts' : resolve(p, 'index.ts'));
function load(file) {
  const path = resolve(file);
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const source = ts.transpileModule(readFileSync(path, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText;
  const localRequire = name => {
    if (name.startsWith('@/')) return load(tsPath(resolve('src', name.slice(2))));
    if (name.startsWith('.')) return load(tsPath(resolve(dirname(path), name)));
    return require(name);
  };
  vm.runInThisContext(`(function(require,module,exports){${source}\n})`, { filename: path })(
    localRequire, module, module.exports,
  );
  return module.exports;
}

const { groundBorderLayers, STRUCTURE_OPACITY } = load('src/features/map/groundBorders.ts');
const { lightingPalette } = load('src/features/hud/lighting.ts');
const style = JSON.parse(readFileSync('assets/map/liberty-run.json', 'utf8'));
const ids = style.layers.map(layer => layer.id);
const byId = new Map(style.layers.map(layer => [layer.id, layer]));

for (const hour of [12, 22]) {
  const palette = lightingPalette(new Date(2026, 8, 9, hour), null);
  const { kerbs, building: placed } = groundBorderLayers(style.layers, palette);
  const building = placed.layer;

  // The outline must sit under the buildings whatever order layers mount in, so
  // it is anchored to a base-style layer: above every street, bridge and tunnel
  // line, and below the anchor the extrusions are inserted at. On a phone it
  // once landed above them and drew footprints across the roofs.
  const outlineAt = ids.indexOf(placed.beforeId);
  assert.ok(outlineAt >= 0, `outline anchor ${placed.beforeId} must exist in the base style`);
  assert.doesNotMatch(placed.beforeId, /^hud-|^world-|^ground-/, 'outline must anchor to a base style layer, not a runtime one');
  assert.ok(outlineAt < ids.indexOf('hud-base-anchor'), 'outline must sit below the building anchor');
  style.layers.forEach((layer, index) => {
    if (layer.type === 'line' && /^(road|bridge|tunnel)_/.test(layer.id)) assert.ok(index < outlineAt, `${layer.id} should stay below the outline`);
  });

  // Every drivable surface gets exactly one kerb, and nothing else does.
  const edged = kerbs.map(({ layer }) => layer.id.replace('ground-kerb-', ''));
  assert.equal(new Set(edged).size, edged.length, 'no surface is edged twice');
  assert.equal(kerbs.length, 14, `expected 14 street and bridge surfaces, got ${kerbs.length}: ${edged.join(', ')}`);
  for (const id of edged) {
    assert.match(id, /^(road|bridge)_/, `${id} is not a street or bridge`);
    assert.doesNotMatch(id, /casing|centerline|rail|hatching|path|pedestrian|tunnel/, `${id} should not be edged`);
  }

  for (const { layer, beforeId } of kerbs) {
    const surface = byId.get(layer.id.replace('ground-kerb-', ''));
    // The whole point: edges sit on the tarmac's own width at every zoom.
    assert.deepEqual(layer.paint['line-gap-width'], surface.paint['line-width'], `${surface.id} kerb gap must equal its width`);
    assert.deepEqual(layer.filter, surface.filter, `${surface.id} kerb must select the same roads`);
    assert.equal(layer['source-layer'], surface['source-layer']);

    // Beneath every surface in its own band, so crossing streets paint over it,
    // but above that band's casings.
    const band = surface.id.split('_')[0];
    const anchor = ids.indexOf(beforeId);
    assert.ok(anchor >= 0, `${beforeId} must exist in the style`);
    assert.ok(beforeId.startsWith(band + '_'), `${surface.id} kerb anchored outside its band (${beforeId})`);
    assert.ok(anchor <= ids.indexOf(surface.id), `${surface.id} kerb must sit below its surface`);
    for (const id of ids) {
      if (id.startsWith(band + '_') && /casing/.test(id)) assert.ok(ids.indexOf(id) < anchor, `${id} should stay below the kerbs`);
    }
  }

  // Same opacity as the buildings, baked into both colours.
  const alphaOf = color => Number(color.match(/,([\d.]+)\)$/)?.[1]);
  assert.equal(alphaOf(kerbs[0].layer.paint['line-color']), STRUCTURE_OPACITY, 'kerbs match the buildings\' opacity');
  assert.equal(alphaOf(building.paint['line-color']), STRUCTURE_OPACITY, 'borders match the buildings\' opacity');
  assert.equal(new Set(kerbs.map(({ layer }) => layer.paint['line-color'])).size, 1, 'every kerb shares one colour');
  assert.equal(building['source-layer'], 'building');

  // A kerb lies on the road casing, so it has to stand out from the casing —
  // the first colour tried sat at 1.3:1 and simply vanished on screen.
  const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
  const luminance = c => {
    const [r, g, b] = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrast = (a, b) => { const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
  const casing = rgb(palette.casing);
  const kerbOnCasing = rgb(palette.kerb).map((v, i) => v * STRUCTURE_OPACITY + casing[i] * (1 - STRUCTURE_OPACITY));
  assert.ok(contrast(kerbOnCasing, casing) >= 1.6, `kerb must read against the casing at ${hour}:00 (got ${contrast(kerbOnCasing, casing).toFixed(2)}:1)`);
}

// Day and night must not share an edge colour, or one of them is unreadable.
const day = groundBorderLayers(style.layers, lightingPalette(new Date(2026, 8, 9, 12), null)).building.layer.paint['line-color'];
const night = groundBorderLayers(style.layers, lightingPalette(new Date(2026, 8, 9, 22), null)).building.layer.paint['line-color'];
assert.notEqual(day, night, 'the edge colour follows the lighting');

console.log('Ground borders passed: 14 kerbs on their roads\' own widths, under crossing streets, at building opacity, readable against the casing day and night.');
