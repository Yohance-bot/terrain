import { Camera as MapCamera, type CameraRef, Map, type MapRef } from '@maplibre/maplibre-react-native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import {
  Camera,
  DefaultLight,
  FilamentScene,
  FilamentView,
  Model,
} from 'react-native-filament';
import { useSharedValue } from 'react-native-worklets-core';

import { JAYANAGAR_CENTER, MAP_STYLE } from '@/constants/config';
import { setMeta } from '@/lib/db';

/**
 * Does Filament work as a 3D layer on top of MapLibre?
 *
 * The earlier spike only proved Filament could load a GLB full-screen. This
 * puts it over a live map and measures the three things that decide whether the
 * approach is viable at all: whether both render at once, how far the 3D object
 * drifts from its map coordinate while the camera moves, and what that costs in
 * frame time.
 *
 * Everything here is measured and written to the console as well as the HUD,
 * because "looks about right" is not an answer to any of those questions.
 */

const ANCHOR: [number, number] = JAYANAGAR_CENTER;
const TAG = '[FILAMENT-TEST]';

/** One scripted camera move. Driving the camera in code exercises the same
 *  path a finger does, and makes the drift measurement repeatable. */
type Leg = {
  name: string;
  center: [number, number];
  zoom?: number;
  bearing?: number;
  pitch?: number;
  duration: number;
};

const OFF: [number, number] = [ANCHOR[0] + 0.004, ANCHOR[1] + 0.003];
const FLIGHT: Leg[] = [
  { name: 'settle', center: ANCHOR, zoom: 17, bearing: 0, pitch: 0, duration: 600 },
  { name: 'pan', center: OFF, zoom: 17, duration: 2500 },
  { name: 'pan back', center: ANCHOR, zoom: 17, duration: 2500 },
  { name: 'zoom in', center: ANCHOR, zoom: 19, duration: 2000 },
  { name: 'zoom out', center: ANCHOR, zoom: 15.5, duration: 2000 },
  { name: 'rotate', center: ANCHOR, zoom: 17, bearing: 120, duration: 2500 },
  { name: 'rotate back', center: ANCHOR, zoom: 17, bearing: 0, duration: 2000 },
  { name: 'pitch', center: ANCHOR, zoom: 17, pitch: 60, duration: 2000 },
  { name: 'pitch flat', center: ANCHOR, zoom: 17, pitch: 0, duration: 1500 },
];

type Sample = {
  leg: string;
  /** Round trip for one `project()` call: the floor on how fresh a synced
   *  position can possibly be. */
  projectMs: number;
  /** How far the anchor moved on screen between reading it and using it. This
   *  is the misalignment a synced object would show, in pixels. */
  driftPx: number;
};

function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * p))]!;
}

export default function FilamentMapTestScreen() {
  const mapRef = useRef<MapRef>(null);
  const cameraRef = useRef<CameraRef>(null);

  const [phase, setPhase] = useState('idle');
  const [samples, setSamples] = useState<Sample[]>([]);
  const [anchorPixel, setAnchorPixel] = useState<{ x: number; y: number } | null>(null);
  const [filamentFrames, setFilamentFrames] = useState(0);
  const [jsFps, setJsFps] = useState(0);
  const [notes, setNotes] = useState<string[]>([]);
  const [mapReady, setMapReady] = useState(false);
  const running = useRef(false);

  // The render callback is a worklet on Filament's own thread. A plain ref
  // mutated there never reaches JS, which would read as "zero frames" and look
  // exactly like Filament being dead — so the count crosses on a shared value.
  const frameCount = useSharedValue(0);
  const collected = useRef<Sample[]>([]);

  const transcript = useRef<string[]>([]);
  const note = useCallback((line: string) => {
    console.log(`${TAG} ${line}`);
    transcript.current.push(line);
    setNotes((current) => [...current.slice(-14), line]);
    // A Release build does not route console.log to the device console, so the
    // findings are written somewhere they can actually be read back.
    void setMeta('filament.test.log', transcript.current.join('\n')).catch(
      () => undefined,
    );
  }, []);

  // Filament's own render loop. Counting here answers "did the 3D layer draw at
  // all", which a screenshot cannot distinguish from a transparent view.
  const renderCallback = useCallback(() => {
    'worklet';
    frameCount.value += 1;
  }, [frameCount]);

  // JS frame rate during the flight. Not the GPU's rate, but it is what stalls
  // when the two renderers contend, and it is measurable without a profiler.
  useEffect(() => {
    let frames = 0;
    let last = Date.now();
    let raf: number;
    const tick = () => {
      frames += 1;
      const now = Date.now();
      if (now - last >= 1000) {
        setJsFps(frames);
        setFilamentFrames(frameCount.value);
        frames = 0;
        last = now;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  /** Project the anchor twice around a bridge round trip. The gap between the
   *  two answers is the misalignment any synced overlay inherits. */
  const measure = useCallback(async (leg: string): Promise<Sample | null> => {
    const map = mapRef.current;
    if (!map) return null;
    try {
      const started = Date.now();
      const first = await map.project(ANCHOR);
      const projectMs = Date.now() - started;
      const second = await map.project(ANCHOR);
      const driftPx = Math.hypot(second[0] - first[0], second[1] - first[1]);
      setAnchorPixel({ x: Math.round(second[0]), y: Math.round(second[1]) });
      return { leg, projectMs, driftPx };
    } catch (error) {
      note(`project() failed: ${(error as Error).message}`);
      return null;
    }
  }, [note]);

  const runFlight = useCallback(async () => {
    if (running.current || !mapRef.current || !cameraRef.current) return;
    running.current = true;
    collected.current = [];
    setSamples([]);
    setNotes([]);
    frameCount.value = 0;
    note(`start · anchor ${ANCHOR[1].toFixed(5)},${ANCHOR[0].toFixed(5)}`);

    const before = frameCount.value;
    for (const leg of FLIGHT) {
      setPhase(leg.name);
      cameraRef.current.easeTo({
        center: leg.center,
        zoom: leg.zoom,
        bearing: leg.bearing,
        pitch: leg.pitch,
        duration: leg.duration,
      });
      // Sample throughout the move, which is when drift actually happens.
      const until = Date.now() + leg.duration;
      while (Date.now() < until) {
        const sample = await measure(leg.name);
        if (sample) collected.current.push(sample);
      }
      const legSamples = collected.current.filter((row) => row.leg === leg.name);
      const worst = Math.max(0, ...legSamples.map((row) => row.driftPx));
      note(
        `${leg.name}: ${legSamples.length} samples · drift p50 ${percentile(
          legSamples.map((r) => r.driftPx),
          0.5,
        ).toFixed(1)}px p95 ${percentile(legSamples.map((r) => r.driftPx), 0.95).toFixed(1)}px max ${worst.toFixed(1)}px`,
      );
      setSamples([...collected.current]);
    }

    const all = collected.current;
    const drifts = all.map((row) => row.driftPx);
    const latencies = all.map((row) => row.projectMs);
    note('--- RESULT ---');
    note(`filament frames during flight: ${frameCount.value - before}`);
    note(
      `project() latency: p50 ${percentile(latencies, 0.5)}ms p95 ${percentile(latencies, 0.95)}ms max ${Math.max(...latencies, 0)}ms`,
    );
    note(
      `anchor drift: p50 ${percentile(drifts, 0.5).toFixed(1)}px p95 ${percentile(drifts, 0.95).toFixed(1)}px max ${Math.max(...drifts, 0).toFixed(1)}px`,
    );
    note(`js fps during flight: ${jsFps}`);
    setPhase('done');
    running.current = false;
  }, [measure, note, jsFps]);

  // Start on its own once the map has settled. The flight has to be able to run
  // without a finger on the screen, so results can be captured from a console
  // attached to the device rather than by watching it.
  useEffect(() => {
    if (!mapReady) return;
    note('map ready · auto-starting flight in 2s');
    const timer = setTimeout(() => void runFlight(), 2000);
    return () => clearTimeout(timer);
  }, [mapReady, note, runFlight]);

  const drifts = samples.map((row) => row.driftPx);

  return (
    <View style={styles.container}>
      <Map
        ref={mapRef}
        style={StyleSheet.absoluteFill}
        mapStyle={MAP_STYLE}
        attribution={false}
        compass={false}
        logo={false}
        onDidFinishLoadingMap={() => setMapReady(true)}
      >
        <MapCamera
          ref={cameraRef}
          initialViewState={{ center: ANCHOR, zoom: 17, pitch: 0, bearing: 0 }}
        />
      </Map>

      {/* The 3D layer. Transparent rendering is what decides whether the map
          survives underneath it — if this is opaque, the approach is dead. */}
      <View style={styles.overlay} pointerEvents="none">
        <FilamentScene>
          <FilamentView
            style={StyleSheet.absoluteFill}
            enableTransparentRendering
            renderCallback={renderCallback}
          >
            <Camera />
            <DefaultLight />
            <Model source={require('../assets/filament-spike/building.glb')} />
          </FilamentView>
        </FilamentScene>
      </View>

      <View style={styles.hud} pointerEvents="box-none">
        <Text style={styles.title}>Filament over MapLibre</Text>
        <Text style={styles.row}>
          phase <Text style={styles.value}>{phase}</Text> · map{' '}
          <Text style={styles.value}>{mapReady ? 'ready' : 'loading'}</Text>
        </Text>
        <Text style={styles.row}>
          filament frames <Text style={styles.value}>{filamentFrames}</Text> · js fps{' '}
          <Text style={styles.value}>{jsFps}</Text>
        </Text>
        <Text style={styles.row}>
          anchor on screen{' '}
          <Text style={styles.value}>
            {anchorPixel ? `${anchorPixel.x},${anchorPixel.y}` : '—'}
          </Text>
        </Text>
        <Text style={styles.row}>
          drift p50 <Text style={styles.value}>{percentile(drifts, 0.5).toFixed(1)}px</Text> · max{' '}
          <Text style={styles.value}>{Math.max(0, ...drifts).toFixed(1)}px</Text>
        </Text>
        <Pressable style={styles.button} onPress={() => void runFlight()}>
          <Text style={styles.buttonText}>Run camera flight</Text>
        </Pressable>
        <ScrollView style={styles.log}>
          {notes.map((line, index) => (
            <Text key={index} style={styles.logLine}>
              {line}
            </Text>
          ))}
        </ScrollView>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0B1220' },
  overlay: { ...StyleSheet.absoluteFillObject },
  hud: {
    position: 'absolute',
    left: 12,
    right: 12,
    bottom: 24,
    backgroundColor: '#0A1929EE',
    borderRadius: 14,
    padding: 14,
    gap: 4,
  },
  title: { color: '#DBFFF3', fontSize: 14, fontWeight: '700', marginBottom: 4 },
  row: { color: '#8FB3A6', fontSize: 11 },
  value: { color: '#DBFFF3', fontWeight: '700' },
  button: {
    marginTop: 8,
    backgroundColor: '#BBF37E',
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: 'center',
  },
  buttonText: { color: '#1B4434', fontWeight: '700', fontSize: 13 },
  log: { maxHeight: 150, marginTop: 8 },
  logLine: { color: '#7FA5C0', fontSize: 10, fontFamily: 'Menlo' },
});
