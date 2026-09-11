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

const {
  mercator, worldSize, groundOffset, cameraDistance, cameraEye, cameraUp,
  projectGround, FOCAL_LENGTH_MM, MAP_FOV_RADIANS,
} = load('src/features/avatar/mapCamera.ts');

const VIEWPORT = { width: 393, height: 852 };   // iPhone 16, in points
const CENTRE = [77.5946, 12.9716];

// The focal length that produces MapLibre's field of view on a 35mm frame.
assert.ok(Math.abs(FOCAL_LENGTH_MM - 36) < 0.01, `focal length should be 36mm, got ${FOCAL_LENGTH_MM}`);

// Mercator basics.
assert.ok(Math.abs(mercator(0, 0).x - 0.5) < 1e-12);
assert.ok(Math.abs(mercator(0, 0).y - 0.5) < 1e-12);
assert.ok(mercator(0, 45).y < 0.5, 'northern latitudes sit above the equator');
assert.equal(worldSize(0), 512);
assert.equal(worldSize(10), 512 * 1024);

// A coordinate at the centre has no ground offset.
const flat = { center: CENTRE, zoom: 17, bearing: 0, pitch: 0 };
const here = groundOffset(flat, CENTRE);
assert.ok(Math.hypot(here.x, here.z) < 1e-9, 'the centre must be the origin');

// ── The load-bearing check ────────────────────────────────────────────────
// With the map flat, one map pixel of ground is one point on screen. So a point
// offset N map-pixels east must land exactly N points right of centre. This
// validates the camera distance and the field of view together: if either is
// wrong, the projection scale is wrong and this fails.
const size = worldSize(flat.zoom);
const eastLon = CENTRE[0] + (100 / size) * 360;
const east = groundOffset(flat, [eastLon, CENTRE[1]]);
assert.ok(Math.abs(east.x - 100) < 0.01, `expected 100px east, got ${east.x}`);
assert.ok(Math.abs(east.z) < 0.01, 'due east must not move north or south');

const screen = projectGround(east, flat, VIEWPORT);
assert.ok(screen, 'a point on the ground ahead of the camera must project');
assert.ok(
  Math.abs(screen.x - (VIEWPORT.width / 2 + 100)) < 0.5,
  `100 map-pixels east should be 100 points right of centre, got ${screen.x - VIEWPORT.width / 2}`,
);
assert.ok(Math.abs(screen.y - VIEWPORT.height / 2) < 0.5, 'due east must stay on the centre line');

// The centre of the map projects to the centre of the screen, at any tilt.
for (const pitch of [0, 30, 55, 60]) {
  const centred = projectGround({ x: 0, z: 0 }, { ...flat, pitch }, VIEWPORT);
  assert.ok(centred, `centre must project at pitch ${pitch}`);
  assert.ok(
    Math.abs(centred.x - VIEWPORT.width / 2) < 0.5 && Math.abs(centred.y - VIEWPORT.height / 2) < 0.5,
    `centre drifted at pitch ${pitch}: ${JSON.stringify(centred)}`,
  );
}

// ── Bearing ───────────────────────────────────────────────────────────────
// Bearing is the compass direction shown at the top of the screen. Turn the map
// to face east and something due north must appear on the left.
const north = [CENTRE[0], CENTRE[1] + 0.002];
const facingNorth = groundOffset({ ...flat, bearing: 0 }, north);
assert.ok(facingNorth.z < 0, 'with north up, a northern point is away from the viewer');
assert.ok(Math.abs(facingNorth.x) < 1e-6, 'and directly ahead');

const facingEast = groundOffset({ ...flat, bearing: 90 }, north);
assert.ok(facingEast.x < 0, 'facing east, north swings to the left');
assert.ok(Math.abs(facingEast.z) < 1e-6, 'and onto the centre line');

// ── Pitch ─────────────────────────────────────────────────────────────────
// Tilting pushes the horizon up: ground ahead of the player compresses toward
// the top of the screen rather than staying at a fixed distance.
const ahead = { x: 0, z: -200 };
const flatAhead = projectGround(ahead, flat, VIEWPORT);
const tiltedAhead = projectGround(ahead, { ...flat, pitch: 55 }, VIEWPORT);
assert.ok(flatAhead && tiltedAhead);
assert.ok(
  tiltedAhead.y > flatAhead.y,
  'tilting must foreshorten ground ahead, moving it toward the horizon',
);

// Nearer ground spreads out: a point toward the viewer moves down the screen.
const behind = projectGround({ x: 0, z: 200 }, { ...flat, pitch: 55 }, VIEWPORT);
assert.ok(behind && behind.y > VIEWPORT.height / 2, 'ground toward the viewer sits lower');

// ── Camera basis ──────────────────────────────────────────────────────────
const distance = cameraDistance(VIEWPORT.height);
assert.ok(Math.abs(distance - VIEWPORT.height / 2 / Math.tan(MAP_FOV_RADIANS / 2)) < 1e-9);

const overhead = cameraEye(0, distance);
assert.ok(Math.abs(overhead[0]) < 1e-9 && Math.abs(overhead[2]) < 1e-9, 'flat map looks straight down');
assert.ok(Math.abs(overhead[1] - distance) < 1e-9);
// Straight down needs an up vector that is not the view direction.
const upFlat = cameraUp(0);
assert.ok(Math.abs(upFlat[1]) < 1e-9 && Math.abs(upFlat[2] + 1) < 1e-9, 'screen-up is -z when flat');

const tiltedEye = cameraEye(60, distance);
assert.ok(tiltedEye[2] > 0, 'tilting pulls the camera back toward the viewer');
assert.ok(tiltedEye[1] > 0 && tiltedEye[1] < distance, 'and lowers it');

// Points behind the camera have no honest screen position.
assert.equal(projectGround({ x: 0, z: 100000 }, { ...flat, pitch: 60 }, VIEWPORT), null);

console.log('Map camera reconstruction passed: mercator, 1:1 ground scale, bearing, pitch and basis.');
