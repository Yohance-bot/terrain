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

const { createRunActivityClient } = load('src/features/liveActivity/controller.ts');
const calls = [];
let releaseStart;
const native = {
  start: async (...args) => { calls.push(['start', ...args]); await new Promise(resolve => { releaseStart = resolve; }); return true; },
  update: async (...args) => { calls.push(['update', ...args]); },
  end: async (...args) => { calls.push(['end', ...args]); },
  endAll: async () => { calls.push(['clear']); },
};
const client = createRunActivityClient(native);
const start = client.start('one', 1000, false, 'km');
await Promise.resolve();
const points = [{ ts: 10000, distanceM: 0 }, { ts: 20000, distanceM: 30 }];
const update = client.update('one', 30, points, 'mi', 20000);
const throttled = client.update('one', 31, points, 'mi', 21000);
const finish = client.end('one', 32, 22000);
await client.update('one', 33, points, 'mi', 27000); // No update after Finish.
releaseStart();
await Promise.all([start, update, throttled, finish]);
assert.deepEqual(calls.map(c => c[0]), ['start', 'update', 'end']);
assert.ok(Math.abs(calls[1][3] - 536.448) < 0.001, 'pace must use selected miles');
await client.clear();
assert.equal(calls.at(-1)[0], 'clear');
let ended = false;
const failing = createRunActivityClient({ ...native, start: async () => { throw new Error('OS disabled activity'); }, end: async () => { ended = true; } });
await failing.start('two', 0, true, 'km');
await failing.end('two', 0, 1);
assert.ok(ended, 'OS failure must not poison subsequent cleanup');
const unavailable = createRunActivityClient(null);
await unavailable.start('android', 0, false, 'km');
await unavailable.update('android', 0, [], 'km');
await unavailable.end('android', 0, 1);
console.log('Live Activity: start/update/finish ordering, throttling, unit conversion, failure recovery and unsupported OS pass.');
