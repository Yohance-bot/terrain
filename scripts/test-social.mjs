import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';

// Execute the production TypeScript rather than a reimplementation, the same
// way test-hud.mjs does. Only pure modules are loaded here: everything social
// that touches the network or the map is covered by the backend suite.
const require = createRequire(import.meta.url);
const cache = new Map();
const tsPath = path => (existsSync(path + '.ts') ? path + '.ts' : resolve(path, 'index.ts'));
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
    localRequire,
    module,
    module.exports,
  );
  return module.exports;
}

const { ghostAt, cumulativeDistances, leadMetres, beatsGhost, formatLead, metresBetween } = load(
  'src/features/social/ghostPlayback.ts',
);

// A straight ghost heading north: one fix every 10 seconds, ~20 m apart.
const STEP_DEG = 20 / 111_320;
const path = Array.from({ length: 11 }, (_, index) => [
  77.5946,
  12.9716 + STEP_DEG * index,
  index * 10_000,
]);
const totals = cumulativeDistances(path);

assert.ok(Math.abs(totals.at(-1) - 200) < 1, 'cumulative distance follows the recorded route');

// Position at a recorded fix, and between two of them.
const atStart = ghostAt(path, 0, totals);
assert.deepEqual(atStart.coordinate, [path[0][0], path[0][1]]);
assert.equal(atStart.progress, 0);
assert.equal(atStart.finished, false);

const atThirtySeconds = ghostAt(path, 30_000, totals);
assert.ok(Math.abs(atThirtySeconds.distanceM - 60) < 1, 'a ghost is where its pacing puts it');

// Interpolation: halfway between two fixes is halfway between two positions,
// so the marker glides instead of stepping once a second.
const halfway = ghostAt(path, 35_000, totals);
assert.ok(Math.abs(halfway.distanceM - 70) < 1, 'position is interpolated between recorded fixes');
assert.ok(halfway.coordinate[1] > atThirtySeconds.coordinate[1]);

// Past the end, the ghost stops at its finish rather than running on forever.
const afterTheEnd = ghostAt(path, 500_000, totals);
assert.equal(afterTheEnd.finished, true);
assert.equal(afterTheEnd.progress, 1);
assert.deepEqual(afterTheEnd.coordinate, [path.at(-1)[0], path.at(-1)[1]]);

// Degenerate inputs must not throw on a screen someone is looking at mid-run.
assert.equal(ghostAt([], 1000), null);
assert.equal(ghostAt([path[0]], 1000).progress, 0);
assert.equal(ghostAt(path, -5_000, totals).progress, 0);

// The runner's standing against the ghost.
assert.equal(leadMetres(100, ghostAt(path, 30_000, totals)) > 0, true, 'ahead reads positive');
assert.equal(leadMetres(10, ghostAt(path, 30_000, totals)) < 0, true, 'behind reads negative');
assert.equal(leadMetres(100, null), 0);
assert.equal(formatLead(2), 'Level');
assert.equal(formatLead(-40), '40 m behind');
assert.equal(formatLead(1500), '1.50 km ahead');

// Beating a ghost is finishing its route in less time than it took.
assert.equal(beatsGhost(90, 100), true);
assert.equal(beatsGhost(100, 100), false);
assert.equal(beatsGhost(120, 100), false);

// The arrival radius a race uses has to be forgiving enough to hit at speed.
assert.ok(metresBetween([77.6, 12.98], [77.6, 12.98018]) < 25);
assert.ok(metresBetween([77.6, 12.98], [77.6, 12.99]) > 25);

console.log('Ghost playback, pacing interpolation, lead reporting and proximity passed.');
