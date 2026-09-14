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

const f = load('src/lib/format.ts');

// Distance: precision falls as the number grows, units follow the athlete.
assert.equal(f.formatDistance(5200, 'km'), '5.20 km');
assert.equal(f.formatDistance(42195, 'km'), '42.2 km');
assert.equal(f.formatDistance(412600, 'km'), '413 km');
assert.equal(f.formatDistance(1609.344, 'mi'), '1.00 mi');
assert.equal(f.distanceNumber(0, 'km'), '0.00');

// Pace: per kilometre or per mile, never NaN on an empty run.
assert.equal(f.formatPace(f.paceSeconds(5000, 1500, 'km'), 'km'), '5:00 /km');
assert.equal(f.formatPace(f.paceSeconds(1609.344, 480, 'mi'), 'mi'), '8:00 /mi');
assert.equal(f.formatPaceValue(f.paceSeconds(0, 100, 'km')), '–:––');
assert.equal(f.formatPaceValue(359.6), '6:00', 'rounds to the nearest second without printing 5:60');

// Clocks and totals.
assert.equal(f.formatClock(2400), '40:00');
assert.equal(f.formatClock(3850), '1:04:10');
assert.equal(f.formatHours(148_320), '41h 12m');
assert.equal(f.formatHours(2280), '38m');

// Elevation converts to feet for miles.
assert.equal(f.formatElevation(100, 'km'), '100 m');
assert.equal(f.formatElevation(100, 'mi'), '328 ft');
assert.equal(f.formatElevation(null, 'km'), '–');

// Titles by local hour.
const at = hour => new Date(2026, 8, 13, hour, 30);
assert.equal(f.runTitle(at(6)), 'Morning run');
assert.equal(f.runTitle(at(12)), 'Lunch run');
assert.equal(f.runTitle(at(15)), 'Afternoon run');
assert.equal(f.runTitle(at(19)), 'Evening run');
assert.equal(f.runTitle(at(23)), 'Night run');
assert.equal(f.runTitle(at(2)), 'Night run');

// WMO weather codes.
assert.equal(f.weatherLabel(0), 'Clear');
assert.equal(f.weatherLabel(3), 'Overcast');
assert.equal(f.weatherLabel(63), 'Rain');
assert.equal(f.weatherLabel(96), 'Thunderstorm');
assert.equal(f.weatherLabel(null), null);

// Every server best-effort distance has a label.
for (const distance of [400, 805, 1000, 1609, 3219, 5000, 10000, 15000, 16093, 20000, 21097, 30000, 42195]) {
  assert.ok(f.EFFORT_LABELS[distance], `missing label for ${distance} m`);
}

// Server dates stay on their calendar day, whatever the phone's zone.
assert.equal(f.shortDate('2026-09-07'), 'Sep 7');

console.log('Format passed: distance, pace, clocks, elevation, run titles, weather and effort labels.');
