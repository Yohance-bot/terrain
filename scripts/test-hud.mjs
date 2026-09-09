import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';
import { performance } from 'node:perf_hooks';

// Execute production TS, not reimplementations. Native/platform and persistence boundaries are stubbed.
const require = createRequire(import.meta.url);
const cache = new Map();
const stubs = new Map();
process.env.EXPO_PUBLIC_ENABLE_SIMULATOR = 'true';
const tsPath = path => existsSync(path + '.ts') ? path + '.ts' : resolve(path, 'index.ts');
function load(file) {
  const path = resolve(file);
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} }; cache.set(path, module);
  const source = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const localRequire = name => {
    if (stubs.has(name)) return stubs.get(name);
    if (name === 'expo-constants') return { expoConfig: {} };
    if (name.startsWith('@/')) return load(tsPath(resolve('src', name.slice(2))));
    if (name.startsWith('.')) {
      const resolved = resolve(dirname(path), name);
      return name.endsWith('.json') ? JSON.parse(readFileSync(resolved, 'utf8')) : load(tsPath(resolved));
    }
    return require(name);
  };
  vm.runInThisContext(`(function(require,module,exports){${source}\n})`, { filename: path })(localRequire, module, module.exports);
  return module.exports;
}
const { rollingPace, formatPace, smoothBearing } = load('src/features/hud/telemetry.ts');
assert.equal(formatPace(359.7), '6:00');
assert.equal(formatPace(null), '—');
const times = Array.from({ length: 21 }, (_, i) => ({ ts: 100000 + i * 1000, distanceM: i * 3 }));
assert.equal(Math.round(rollingPace(times, 120000)), 333);
assert.equal(rollingPace(times, 131000), null);
assert.equal(rollingPace(times.slice(0, 3), 102000), null);
assert.equal(rollingPace(times.map(p => ({ ...p, distanceM: 0 })), 120000), null);
assert.ok(Math.abs(smoothBearing(359, 1) - 359) < 1);
assert.ok(Math.abs(smoothBearing(1, 359) - 1) < 1);

const { IncrementalGpsCleaner } = load('src/lib/gpsClean.ts');
const cleaner = new IncrementalGpsCleaner();
const first = cleaner.push({ lon: 77.5, lat: 13, accuracy: 5 });
assert.equal(cleaner.push({ lon: NaN, lat: 13, accuracy: 5 }), first);
assert.equal(cleaner.push({ lon: 77.5, lat: 13, accuracy: 100 }), first);
assert.equal(cleaner.push({ lon: 78, lat: 13, accuracy: 5 }), first);
cleaner.breakSegment();
assert.equal(cleaner.push({ lon: 78, lat: 13, accuracy: 5 }).length, 2);
cleaner.reset();
assert.equal(cleaner.push({ lon: 0, lat: 0, accuracy: 5 }).length, 1);

const { CheckpointLedger } = load('src/features/hud/events.ts');
const ledger = new CheckpointLedger();
const fix = { coordinate: [77.5, 13], ts: 1000, speedMps: 3, bearing: 90, accuracyM: 5, segment: 0 };
assert.equal(ledger.update('run1', 0, fix, true, 1000), null);
assert.match(ledger.update('run1', 1001, fix, true, 1000).title, /1 KM/);
assert.equal(ledger.update('run1', 1002, fix, true, 1000), null);
assert.equal(ledger.update('run1', 3200, fix, false, 1000), null);
assert.equal(ledger.update('run1', 3201, fix, true, 1000), null);
assert.equal(ledger.update('run2', 0, fix, true, 1609.344), null);
assert.match(ledger.update('run2', 1610, fix, true, 1609.344).title, /1 MI/);
const waypoint = { id: 'w1', name: 'Park gate', coordinate: [77.5, 13], radiusM: 20 };
assert.equal(ledger.update('run2', 1610, fix, true, 1609.344, [waypoint]).title, 'Park gate');
assert.equal(ledger.update('run2', 1611, fix, true, 1609.344, [waypoint]), null);

const { buildTrail, TRAIL_POINT_BUDGET } = load('src/features/hud/trail.ts');
const path = Array.from({ length: 5400 }, (_, i) => [77.5 + i * 0.00001, 13 + Math.sin(i / 20) * 0.0005]);
const started = performance.now();
const trail = buildTrail(path, [2700]);
const ms = performance.now() - started;
assert.equal(trail.features.length, 2);
assert.deepEqual(trail.features[0].geometry.coordinates.at(-1), path[2699]);
assert.deepEqual(trail.features[1].geometry.coordinates[0], path[2700]);
assert.ok(trail.features.reduce((n, f) => n + f.geometry.coordinates.length, 0) <= TRAIL_POINT_BUDGET);
assert.ok(buildTrail(path, [], true).features.reduce((n, f) => n + f.geometry.coordinates.length, 0) <= 768);
assert.equal(buildTrail([[179.9, 0], [-179.9, 0]], []).features.length, 0);

const { sharedBorders, selectBorders } = load('src/features/hud/borders.ts');
const square = (id, x) => ({ type: 'Feature', properties: { territory_id: id }, geometry: { type: 'Polygon', coordinates: [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]] } });
const borders = sharedBorders([square('a', 0), square('b', 1), square('c', 5)]);
assert.equal(borders.length, 1);
assert.equal(selectBorders(borders, new Set(['a']), new Set(['b'])).features.length, 1);
assert.equal(selectBorders(borders, new Set(['a']), new Set(['a'])).features.length, 0);

const { daylight, lightingPalette } = load('src/features/hud/lighting.ts');
assert.equal(daylight(new Date(2026, 8, 7, 12), null), 1);
assert.equal(daylight(new Date(2026, 8, 7, 0), null), 0);
const noon = new Date(2026, 8, 7, 12);
assert.notEqual(lightingPalette(noon, null).road, lightingPalette(noon, { code: 61, cloud: 90 }).road);
const { followPose } = load('src/features/hud/camera.ts');
const pose = { bearing: 359, pitch: 30, zoom: 16 };
assert.equal(followPose(pose, { ...fix, speedMps: 0, bearing: 180 }, false).bearing, 359);
assert.equal(followPose(pose, fix, true).pitch, 0);
assert.equal(followPose(pose, fix, true).bearing, 0);
console.log(`HUD production-module tests passed. Desktop synthetic 90-minute route: trail ${ms.toFixed(1)} ms. These are not device FPS or battery measurements.`);

// Recorder integration: real store/actions and queue, mocked platform + durable boundary.
const meta = new Map();
const persisted = [];
let recovered = 0, callback, permission = true, created = 0;
stubs.set('@/lib/db', {
  getMeta: async key => meta.get(key) ?? null,
  setMeta: async (key, value) => { meta.set(key, value); },
  createLocalRun: async () => { created++; }, finishLocalRun: async () => {},
  recoverInterruptedRuns: async () => { recovered++; return []; },
  appendSample: async (runId, seq, sample) => { persisted.push({ runId, seq, sample }); },
  recordRunInterruption: async () => {},
});
stubs.set('expo-crypto', { randomUUID: () => `run-${created}` });
stubs.set('expo-task-manager', { defineTask() {}, isAvailableAsync: async () => false });
stubs.set('react-native', { AppState: { currentState: 'active', addEventListener: () => ({ remove() {} }) } });
stubs.set('expo-location', {
  Accuracy: { High: 4 }, ActivityType: { Fitness: 3 },
  requestForegroundPermissionsAsync: async () => ({ granted: permission }),
  stopLocationUpdatesAsync: async () => {},
  watchPositionAsync: async (options, handler) => { assert.equal(options.accuracy, 4); callback = handler; return { remove() {} }; },
});
const { useRecorder, recoverRecorderOnce } = load('src/features/recorder/useRecorder.ts');
await recoverRecorderOnce(); await recoverRecorderOnce(); assert.equal(recovered, 1);
await useRecorder.getState().start();
assert.equal(useRecorder.getState().status, 'recording');
await recoverRecorderOnce(); assert.equal(recovered, 1);
const flush = () => new Promise(resolve => setImmediate(resolve));
const baseTime = Date.now();
const emit = (seconds, lon, accuracy = 5) => callback({ timestamp: baseTime + seconds * 1000, coords: { longitude: lon, latitude: 13, accuracy, speed: 3 } });
emit(0, 77.5); await flush();
assert.equal(useRecorder.getState().cleanPath.length, 1);
const stablePath = useRecorder.getState().cleanPath;
emit(1, 77.5, 60); await flush(); assert.equal(useRecorder.getState().cleanPath, stablePath);
emit(0, 78); await flush(); assert.equal(useRecorder.getState().cleanPath, stablePath);
emit(20, 77.502); await flush();
assert.equal(useRecorder.getState().liveDistanceM, 0);
assert.deepEqual(useRecorder.getState().segmentStarts, [1]);
emit(21, 77.50203); await flush(); assert.ok(useRecorder.getState().liveDistanceM > 0);
emit(45, 77.50203); await flush();
assert.deepEqual(useRecorder.getState().segmentStarts, [1], 'a stationary traffic-light pause must not create a new section');
const beforeStop = useRecorder.getState().liveDistanceM;
emit(46, 77.50206);
const finished = await useRecorder.getState().stop();
assert.ok(finished?.runId);
assert.equal(useRecorder.getState().status, 'idle');
assert.ok(useRecorder.getState().liveDistanceM > beforeStop, 'stop must drain the last queued fix');
assert.equal(useRecorder.getState().cleanPath.length, useRecorder.getState().sampleCount, 'stop must preserve section indices through the claim animation');
assert.deepEqual(useRecorder.getState().segmentStarts, [1]);
assert.equal(persisted.length, 7, 'raw duplicates and inaccurate fixes remain durable evidence');
permission = false; await useRecorder.getState().start();
assert.equal(useRecorder.getState().status, 'idle'); assert.match(useRecorder.getState().error, /permission/);
console.log('Recorder integration passed: recovery/remount, permission denial, chronological fixes, gap reacquisition, raw persistence and stop queue drain.');

const { confirmedClaimCue } = load('src/features/hud/claims.ts');
const result = { run_id: 'claim-run', status: 'provisional', segments: [{ territory_id: 'a', is_owned_by_you: true, ownership_changed: true, capture_method: 'loop' }] };
assert.equal(confirmedClaimCue(result, [77, 13]), null);
assert.equal(confirmedClaimCue({ ...result, status: 'rejected' }, [77, 13]), null);
assert.equal(confirmedClaimCue({ ...result, status: 'applied' }, [77, 13]).title, 'TERRITORY CLAIMED');
assert.equal(confirmedClaimCue({ ...result, status: 'applied', segments: [{ ...result.segments[0], is_owned_by_you: false }] }, [77, 13]), null);
assert.equal(confirmedClaimCue({ ...result, status: 'applied', segments: [result.segments[0], result.segments[0]] }, [77, 13]).territoryIds.length, 1);
const { weatherKind } = load('src/features/hud/lighting.ts');
assert.equal(weatherKind(71, 100), 'Snow'); assert.equal(weatherKind(95, 100), 'Storm'); assert.equal(weatherKind(48, 80), 'Fog');
console.log('Authoritative claim gating and weather classification passed.');

const { illuminateStreets, STREET_VERTEX_BUDGET } = load('src/features/map/streetMatching.ts');
const lineFeature = (points, roadClass = 'minor') => ({ type: 'Feature', properties: { class: roadClass }, geometry: { type: 'LineString', coordinates: points } });
const routeOf = (...lines) => ({ type: 'FeatureCollection', features: lines.map(p => lineFeature(p)) });
const straight = lineFeature([[77, 13], [77.01, 13]]);
const trace = routeOf([[77.002, 13.00004], [77.003, 13.00004]]);
const lit = illuminateStreets(trace, [straight]);
assert.ok(lit.streets.features.length > 0);
assert.equal(lit.unmatched.features.length, 0);
for (const feature of lit.streets.features) for (const p of feature.geometry.coordinates) {
  assert.equal(p[1], 13); assert.ok(p[0] >= 77.002 && p[0] <= 77.003, 'only the traversed part of a road is lit');
}
assert.ok(illuminateStreets(trace, []).unmatched.features.length > 0, 'missing tiles preserve the GPS trace');
const parallel = [lineFeature([[77, 12.99995], [77.01, 12.99995]]), lineFeature([[77, 13.00005], [77.01, 13.00005]])];
assert.equal(illuminateStreets(routeOf([[77.002, 13], [77.003, 13]]), parallel).streets.features.length, 0, 'do not guess between equally plausible parallel streets');
assert.equal(illuminateStreets(routeOf([[77.002, 13.001], [77.003, 13.001]]), [straight]).streets.features.length, 0);
const cornerRoad = lineFeature([[77, 13], [77.001, 13], [77.001, 13.001]]);
const corner = illuminateStreets(routeOf([[77.0005, 13], [77.001, 13], [77.001, 13.0005]]), [cornerRoad]);
for (const f of corner.streets.features) for (const p of f.geometry.coordinates) assert.ok(p[1] === 13 || p[0] === 77.001, 'junction must follow actual road vertices');
const disconnected = illuminateStreets(routeOf([[77.002, 13], [77.003, 13]], [[77.007, 13], [77.008, 13]]), [straight]);
assert.equal(disconnected.streets.features.length, 2, 'signal gap must stay disconnected');
const matchStart = performance.now();
const longMatch = illuminateStreets({ type: 'FeatureCollection', features: trail.features }, [lineFeature(path)]);
assert.ok([...longMatch.streets.features, ...longMatch.unmatched.features].reduce((n, f) => n + f.geometry.coordinates.length, 0) <= STREET_VERTEX_BUDGET);

const matchMs = performance.now() - matchStart;
const { buildRoofDetails, buildingHeight, BUILDING_HEIGHT } = load('src/features/map/worldGeometry.ts');
const footprint = { type: 'Feature', properties: { render_height: 20 }, geometry: { type: 'Polygon', coordinates: [[[77, 13], [77.0002, 13], [77.0002, 13.0002], [77, 13.0002], [77, 13]]] } };
const roofs = buildRoofDetails([footprint, footprint], [77, 13]);
assert.deepEqual(buildRoofDetails([{ ...footprint, geometry: { type: 'MultiPolygon', coordinates: [footprint.geometry.coordinates] } }], [77, 13]), roofs, 'native tiles group buildings in MultiPolygons');
assert.ok(roofs.features.length >= 3 && roofs.features.length <= 6);
assert.deepEqual(roofs, buildRoofDetails([footprint], [77, 13]), 'roof shape is deterministic and duplicate tiles are ignored');
for (const f of roofs.features) {
  assert.ok(f.properties.height > f.properties.base && f.properties.base >= buildingHeight(footprint.properties));
  assert.deepEqual(f.geometry.coordinates[0][0], f.geometry.coordinates[0].at(-1));
  for (const p of f.geometry.coordinates[0]) assert.ok(p[0] >= 77 && p[0] <= 77.0002 && p[1] >= 13 && p[1] <= 13.0002, 'roof must stay inside its actual footprint');
}
assert.equal(buildRoofDetails([{ ...footprint, geometry: { ...footprint.geometry, coordinates: [...footprint.geometry.coordinates, footprint.geometry.coordinates[0]] } }], [77, 13]).features.length, 0, 'do not cover courtyards');
assert.equal(buildRoofDetails([footprint], [77, 13], true).features.length, 1);
const { illuminatedRoadWidth, roadPaintColor } = load('src/features/map/roadStyle.ts');
const { validateStyleMin } = require('@maplibre/maplibre-gl-style-spec');
const nativeStyle = { version: 8, sources: { test: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } } }, layers: [
  { id: 'street', source: 'test', type: 'line', paint: { 'line-width': illuminatedRoadWidth } },
  { id: 'building', source: 'test', type: 'fill-extrusion', paint: { 'fill-extrusion-height': BUILDING_HEIGHT } },
] };
assert.deepEqual(validateStyleMin(nativeStyle).map(e => e.message), [], 'new native paint expressions must validate');
const dayPalette = lightingPalette(noon, null);
assert.notEqual(roadPaintColor('road_minor', dayPalette), roadPaintColor('road_minor_casing', dayPalette));
assert.notEqual(roadPaintColor('road_minor', dayPalette), roadPaintColor('road_minor_centerline', dayPalette));
console.log(`World/road tests passed: partial streets, junctions, ambiguity, off-road fallback, GPS gaps, footprint-safe roof geometry and native expressions. Desktop long-route matching ${matchMs.toFixed(1)} ms.`);


const { smoothTrail, RUN_TRAIL_COLOR } = load('src/features/hud/smoothTrail.ts');
assert.equal(RUN_TRAIL_COLOR, '#11D9F1');
const sharp = routeOf([[77, 13], [77.001, 13], [77.001, 13.001]]);
const curved = smoothTrail(sharp);
assert.deepEqual(curved.features[0].geometry.coordinates[0], sharp.features[0].geometry.coordinates[0]);
assert.deepEqual(curved.features[0].geometry.coordinates.at(-1), sharp.features[0].geometry.coordinates.at(-1));
assert.ok(curved.features[0].geometry.coordinates.some(p => p[0] < 77.001 && p[1] > 13), 'the square corner must become a curve');
for (const p of curved.features[0].geometry.coordinates) assert.ok(p[0] >= 77 && p[0] <= 77.001 && p[1] >= 13 && p[1] <= 13.001, 'rounding must never overshoot');
assert.equal(smoothTrail(routeOf([[77,13],[77.001,13]], [[77.003,13],[77.004,13]])).features.length, 2);
assert.ok(smoothTrail(trail).features.reduce((n,f)=>n+f.geometry.coordinates.length,0) <= 4608);
assert.deepEqual(sharp.features[0].geometry.coordinates[1], [77.001,13], 'smoothing must not mutate the recorded path');
const manyBuildings = Array.from({length:180}, (_,i) => ({...footprint, geometry: {...footprint.geometry, coordinates: [footprint.geometry.coordinates[0].map(([x,y])=>[x + (i%15)*.0003,y+Math.floor(i/15)*.0003])]}}));
const coverageStart = performance.now();
const coverage = buildRoofDetails(manyBuildings,[77,13]);
assert.equal(new Set(coverage.features.map(f=>f.properties.buildingKey)).size,180,'every footprint gets an ornament beyond the old 90-building limit');
assert.equal(new Set(buildRoofDetails(manyBuildings,[77,13],true).features.map(f=>f.properties.buildingKey)).size,180,'economy reduces roof complexity, not building coverage');
const concave = {...footprint,geometry:{type:'Polygon',coordinates:[[[77,13],[77.0004,13],[77.0004,13.0001],[77.0001,13.0001],[77.0001,13.0004],[77,13.0004],[77,13]]]}};
const concaveRoofs = buildRoofDetails([concave],[77,13]);
assert.ok(concaveRoofs.features.length > 0,'L-shaped buildings also get a rooftop structure');
for(const f of concaveRoofs.features) for(const p of f.geometry.coordinates[0]) assert.ok(p[0]<=77.0001 || p[1]<=13.0001,'an L-shaped roof cannot bridge its empty corner');
const courtyard = {...footprint,geometry:{type:'Polygon',coordinates:[[[77,13],[77.001,13],[77.001,13.001],[77,13.001],[77,13]],[[77.0003,13.0003],[77.0007,13.0003],[77.0007,13.0007],[77.0003,13.0007],[77.0003,13.0003]]]}};
const courtyardRoofs = buildRoofDetails([courtyard],[77,13]);
assert.ok(courtyardRoofs.features.length > 0,'courtyard buildings get a safe pavilion on a wing');
for(const f of courtyardRoofs.features) for(const p of f.geometry.coordinates[0]) assert.ok(!(p[0]>77.0003&&p[0]<77.0007&&p[1]>13.0003&&p[1]<13.0007),'a pavilion cannot cover a courtyard');
console.log(`Cyan curve and complete rooftop coverage tests passed (${(performance.now()-coverageStart).toFixed(1)} ms desktop coverage/complex-footprint checks).`);

const { territoryColorAt, territoryFill, buildingTerritoryPaint } = load('src/features/map/territoryAppearance.ts');
const zone = { ...courtyard, properties: { terrain_color: '#A855F7' } };
const captureZone = { ...zone, properties: { capture_color: '#22C55E' } };
const colorAt = territoryColorAt([captureZone, zone]);
assert.equal(colorAt([77.0001,13.0001]), '#22C55E', 'visible captures take precedence over fixed territory color');
assert.equal(colorAt([77.0005,13.0005]), undefined, 'territory holes must not tint another building');
assert.equal(colorAt([76,12]), undefined);
assert.equal(territoryColorAt([{...zone,geometry:{type:'MultiPolygon',coordinates:[zone.geometry.coordinates]}}])([77.0001,13.0001]), '#A855F7');
const coloredRoofs = buildRoofDetails([footprint],[77,13],false,undefined,[zone]);
assert.ok(coloredRoofs.features.every(f=>f.properties.territoryColor === '#A855F7' && /^#[0-9a-f]{6}$/i.test(f.properties.color)));
const recoloredRoofs = buildRoofDetails([footprint],[77,13],false,undefined,[captureZone]);
assert.deepEqual(coloredRoofs.features.map(f=>f.geometry),recoloredRoofs.features.map(f=>f.geometry),'ownership changes recolor buildings without changing architecture');
assert.equal(new Set(coverage.features.map(f=>f.properties.variant)).size,12,'all twelve architectural families are represented');
const allRoofs = buildRoofDetails(manyBuildings,[77,13],false,undefined,[zone]);
for(const roof of allRoofs.features) {
 const owner = manyBuildings.find(b => buildRoofDetails([b],[77,13],true).features[0]?.properties.buildingKey===roof.properties.buildingKey);
 assert.ok(owner);
 const ring=owner.geometry.coordinates[0];const xs=ring.map(p=>p[0]),ys=ring.map(p=>p[1]);
 for(const p of roof.geometry.coordinates[0]) assert.ok(p[0]>=Math.min(...xs)&&p[0]<=Math.max(...xs)&&p[1]>=Math.min(...ys)&&p[1]<=Math.max(...ys),'offset towers stay inside footprints');
}
const facade = buildingTerritoryPaint([{...footprint,id:42}],[zone],'#C6DEDC');
assert.ok(Array.isArray(facade));
assert.equal(buildingTerritoryPaint([footprint],[zone],'#C6DEDC'),'#C6DEDC','missing vector IDs retain safe facade fallback');
assert.deepEqual(validateStyleMin({...nativeStyle,layers:[
 {id:'zoom-fill',source:'test',type:'fill',paint:{'fill-color':territoryFill('terrain_fill')}},
 {id:'facade',source:'test',type:'fill-extrusion',paint:{'fill-extrusion-color':facade}},
]}).map(e=>e.message),[]);
console.log('Twelve roof families, footprint containment, territory recoloring, facade fallback and zoom colour expressions passed.');
