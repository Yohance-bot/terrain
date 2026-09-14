import * as Crypto from 'expo-crypto';
import * as Location from 'expo-location';
import * as TaskManager from 'expo-task-manager';
import { create } from 'zustand';
import { AppState, type AppStateStatus } from 'react-native';

import { ENABLE_SIMULATION, GPS_INTERVAL_MS } from '@/constants/config';
import {
  appendSample,
  createLocalRun,
  finishLocalRun,
  getMeta,
  recordRunInterruption,
  recoverInterruptedRuns,
  setMeta,
  type StoredSample,
} from '@/lib/db';
import { haversineMetres } from '@/lib/geo';
import { IncrementalGpsCleaner, type GeoCoord } from '@/lib/gpsClean';
import { normalizeSampleTimestampMs } from '@/lib/runSamples';
import { bearingBetween, type RunFix, type TimedDistance } from '@/features/hud/telemetry';
import { currentConditions } from '@/features/hud/weatherCache';
import type { RunConditions } from '@/services/api/types';

/**
 * Run recorder with an optional background location task.
 *
 * Samples and the active run context are persisted locally so an Expo
 * TaskManager invocation can write fixes when no React view is mounted.
 *
 * State exposes two paths:
 *   path      — raw GPS coords that passed MAX_ACCURACY_M (for debug / stats)
 *   cleanPath — accuracy-filtered, spike-rejected, EMA-smoothed coords
 *               (use this for map rendering and territory activation)
 *
 * Visual simplification is gap-aware and performed by the trail presentation layer.
 * Raw samples in SQLite are untouched — the backend remains authoritative.
 *
 * Territory ownership stays server-authoritative. HUD presentation consumes
 * timestamped accepted fixes; visual cadence never controls durable GPS writes.
 */

export type RecorderStatus = 'idle' | 'starting' | 'recording' | 'stopping';

const BACKGROUND_LOCATION_TASK = 'run-background-location';
const ACTIVE_RUN_META_KEY = 'recorder.active-run.v1';

type ActiveRun = {
  runId: string;
  nextSequence: number;
};

type RecorderState = {
  status: RecorderStatus;
  runId: string | null;
  startedAt: Date | null;
  sampleCount: number;
  droppedCount: number;
  liveDistanceM: number;
  isSimulation: boolean;
  /** Raw GPS coords that passed the loose MAX_ACCURACY_M gate. Debug / stats use only. */
  path: [number, number][];
  /**
   * Cleaned GPS coords: accuracy-filtered, spike-rejected, EMA-smoothed.
   * This is the authoritative path for map rendering and territory activation.
   * Segment indices remain stable through stop; the trail layer handles LOD.
   */
  cleanPath: GeoCoord[];
  liveFix: RunFix | null;
  paceWindow: TimedDistance[];
  /** Indices starting a new observed section after signal loss. */
  segmentStarts: number[];
  error: string | null;
  start: () => Promise<void>;
  /** Development-only virtual recorder; never shown in production UI. */
  startSimulation: () => Promise<void>;
  addSimulatedPoint: (lon: number, lat: number) => Promise<void>;
  stop: () => Promise<{ runId: string; startedAt: Date; endedAt: Date } | null>;
};

let subscription: Location.LocationSubscription | null = null;
let appStateSubscription: ReturnType<typeof AppState.addEventListener> | null = null;
let appState: AppStateStatus = AppState.currentState;
let sampleWriteQueue: Promise<void> = Promise.resolve();
let lastDisplayTimestamp = 0;
let recovery: Promise<unknown> | null = null;

/** One cold-process recovery; never finalize a recorder just because a view remounts. */
export function recoverRecorderOnce(): Promise<unknown> {
  if (useRecorder.getState().status !== 'idle') return Promise.resolve();
  if (!recovery) recovery = (async () => {
    await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK).catch(() => undefined);
    await sampleWriteQueue;
    await setActiveRun(null);
    return recoverInterruptedRuns();
  })().catch(error => { recovery = null; throw error; });
  return recovery;
}

// Module-level cleaner — lives as long as the JS bundle, reset on each run.
const gpsCleaner = new IncrementalGpsCleaner();

/** The weather a run started in, kept with the run until it is submitted. */
async function recordStartConditions(runId: string): Promise<void> {
  const conditions = currentConditions();
  if (conditions) await setMeta(`run.conditions.${runId}`, JSON.stringify(conditions)).catch(() => undefined);
}

export async function startConditions(runId: string): Promise<RunConditions | null> {
  const raw = await getMeta(`run.conditions.${runId}`).catch(() => null);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as RunConditions;
  } catch {
    return null;
  }
}

async function getActiveRun(): Promise<ActiveRun | null> {
  const value = await getMeta(ACTIVE_RUN_META_KEY);
  if (!value) return null;

  try {
    const activeRun = JSON.parse(value) as ActiveRun;
    return typeof activeRun.runId === 'string' && Number.isInteger(activeRun.nextSequence)
      ? activeRun
      : null;
  } catch {
    return null;
  }
}

async function setActiveRun(activeRun: ActiveRun | null): Promise<void> {
  await setMeta(ACTIVE_RUN_META_KEY, activeRun ? JSON.stringify(activeRun) : '');
}

function enqueueLocationSample(location: Location.LocationObject): Promise<void> {
  sampleWriteQueue = sampleWriteQueue
    .catch(() => undefined)
    .then(async () => {
      const activeRun = await getActiveRun();
      if (!activeRun) return;

      // Reserve a sequence before writing the sample. A process death can leave
      // a gap, but never lets a later task overwrite an already persisted fix.
      await setActiveRun({ ...activeRun, nextSequence: activeRun.nextSequence + 1 });

      const { latitude, longitude, accuracy, speed, altitude, altitudeAccuracy } = location.coords;
      const sample: StoredSample = {
        ts: normalizeSampleTimestampMs(location.timestamp),
        lat: latitude,
        lon: longitude,
        accuracy_m: accuracy ?? null,
        speed_mps: speed ?? null,
        provider: location.mocked === undefined ? null : 'expo-location',
        is_mock: location.mocked ?? false,
        altitude_m: altitude ?? null,
        altitude_accuracy_m: altitudeAccuracy ?? null,
      };

      try {
        await appendSample(activeRun.runId, activeRun.nextSequence, sample);
      } catch {
        await recordRunInterruption(activeRun.runId, 'sample_persist_failed').catch(() => undefined);
        return;
      }

      const recorder = useRecorder.getState();
      if (!['recording', 'stopping'].includes(recorder.status) || recorder.runId !== activeRun.runId) return;
      // Preserve raw evidence above, but duplicate/out-of-order fixes cannot move the HUD.
      if (sample.ts <= lastDisplayTimestamp) return;
      lastDisplayTimestamp = sample.ts;
      const previousFix = recorder.liveFix;
      const gap = Boolean(previousFix && sample.ts - previousFix.ts > 15_000 && haversineMetres({ lon: previousFix.coordinate[0], lat: previousFix.coordinate[1] }, { lon: longitude, lat: latitude }) > 30);
      if (gap) gpsCleaner.breakSegment();
      const newCleanPath = gpsCleaner.push({ lat: latitude, lon: longitude, accuracy: accuracy ?? undefined });
      if (newCleanPath === recorder.cleanPath || newCleanPath.length <= recorder.cleanPath.length) {
        useRecorder.setState({ droppedCount: recorder.droppedCount + 1 });
        return;
      }
      const coordinate = newCleanPath.at(-1)!;
      const distanceM = previousFix && !gap
        ? haversineMetres({ lon: previousFix.coordinate[0], lat: previousFix.coordinate[1] }, { lon: coordinate[0], lat: coordinate[1] }) : 0;
      const seconds = previousFix ? (sample.ts - previousFix.ts) / 1000 : 0;
      const speedMps = seconds > 0 && !gap ? Math.min(12, distanceM / seconds) : 0;
      const liveDistanceM = recorder.liveDistanceM + distanceM;
      const segment = (previousFix?.segment ?? 0) + (gap ? 1 : 0);
      useRecorder.setState({
        sampleCount: recorder.sampleCount + 1,
        liveDistanceM,
        path: [...recorder.path, [longitude, latitude]],
        cleanPath: newCleanPath,
        segmentStarts: gap ? [...recorder.segmentStarts, newCleanPath.length - 1] : recorder.segmentStarts,
        liveFix: { coordinate, ts: sample.ts, speedMps, bearing: previousFix && distanceM > 1 && !gap ? bearingBetween(previousFix.coordinate, coordinate) : previousFix?.bearing ?? null, accuracyM: accuracy, segment },
        paceWindow: [...(gap ? [] : recorder.paceWindow.filter(p => p.ts >= sample.ts - 25_000)), { ts: sample.ts, distanceM: liveDistanceM }],
      });
    });

  return sampleWriteQueue;
}

// TaskManager requires this registration at the module scope because it can
// launch the JavaScript bundle while the app has no mounted React views.
TaskManager.defineTask(BACKGROUND_LOCATION_TASK, async ({ data, error }) => {
  const activeRun = await getActiveRun();
  if (!activeRun) return;

  if (error) {
    await recordRunInterruption(activeRun.runId, 'background_location_task_failed').catch(
      () => undefined,
    );
    return;
  }

  const locations = (data as { locations?: Location.LocationObject[] }).locations ?? [];
  for (const location of locations) {
    await enqueueLocationSample(location);
  }
});

function removeAppStateListener() {
  appStateSubscription?.remove();
  appStateSubscription = null;
}

function observeForegroundInterruption(runId: string) {
  removeAppStateListener();
  appState = AppState.currentState;
  appStateSubscription = AppState.addEventListener('change', (nextState) => {
    const wasActive = appState === 'active';
    appState = nextState;
    if (wasActive && nextState !== 'active') {
      // This is evidence of an interruption, not a claim that the route ended
      // or that its samples are valid. The server remains authoritative.
      void recordRunInterruption(runId, `app_state_${nextState}`).catch(() => undefined);
    }
  });
}

export const useRecorder = create<RecorderState>((set, get) => ({
  status: 'idle',
  runId: null,
  startedAt: null,
  sampleCount: 0,
  droppedCount: 0,
  liveDistanceM: 0,
  isSimulation: false,
  path: [],
  cleanPath: [],
  error: null,
  liveFix: null, paceWindow: [], segmentStarts: [],

  start: async () => {
    if (get().status !== 'idle') return;
    try { await recoverRecorderOnce(); } catch {
      set({ error: 'Could not recover saved runs. Please try again.' });
      return;
    }
    if (get().status !== 'idle') return;
    set({ status: 'starting', error: null, isSimulation: false });
    let runId: string | null = null;
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (!permission.granted) throw new Error('Location permission is required to record a run.');
      runId = Crypto.randomUUID();
      const startedAt = new Date();
      await createLocalRun(runId, startedAt);
      await recordStartConditions(runId);
      gpsCleaner.reset();
      lastDisplayTimestamp = 0;
      await setActiveRun({ runId, nextSequence: 0 });
      const locationOptions = { accuracy: Location.Accuracy.High, timeInterval: GPS_INTERVAL_MS, distanceInterval: 1 };
      const canUseBackgroundTask = (await TaskManager.isAvailableAsync()) && (await Location.isBackgroundLocationAvailableAsync());
      const backgroundPermission = canUseBackgroundTask ? await Location.requestBackgroundPermissionsAsync() : null;
      // Publish context before the subscription can deliver its first fix.
      set({ status: 'recording', runId, startedAt, sampleCount: 0, droppedCount: 0, liveDistanceM: 0, path: [], cleanPath: [], liveFix: null, paceWindow: [], segmentStarts: [] });
      if (backgroundPermission?.granted) {
        await Location.startLocationUpdatesAsync(BACKGROUND_LOCATION_TASK, {
          ...locationOptions, activityType: Location.ActivityType.Fitness,
          pausesUpdatesAutomatically: false,
          deferredUpdatesInterval: 5_000,
          showsBackgroundLocationIndicator: true,
          foregroundService: { notificationTitle: 'Run recording in progress', notificationBody: 'Your route is being recorded.', killServiceOnDestroy: true },
        });
      } else {
        subscription = await Location.watchPositionAsync(locationOptions, position => {
          void enqueueLocationSample(position).catch(() => set({ error: 'A GPS fix could not be saved.' }));
        });
        set({ error: 'Keep TerraRun open to record: background location is unavailable.' });
      }
      observeForegroundInterruption(runId);
    } catch (error) {
      subscription?.remove(); subscription = null;
      removeAppStateListener();
      await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK).catch(() => undefined);
      await setActiveRun(null).catch(() => undefined);
      if (runId) {
        await recordRunInterruption(runId, 'location_subscription_failed').catch(() => undefined);
        await finishLocalRun(runId, new Date()).catch(() => undefined);
      }
      gpsCleaner.reset();
      set({ status: 'idle', runId: null, startedAt: null, liveFix: null, paceWindow: [], error: error instanceof Error ? error.message : 'Could not start recording.' });
    }
  },

  startSimulation: async () => {
    if (!ENABLE_SIMULATION || get().status !== 'idle') return;
    await recoverRecorderOnce();
    if (get().status !== 'idle') return;
    set({ status: 'starting', error: null });
    try {
      const runId = Crypto.randomUUID();
      const startedAt = new Date();
      await createLocalRun(runId, startedAt);
      await recordStartConditions(runId);
      gpsCleaner.reset(); lastDisplayTimestamp = 0;
      await setActiveRun({ runId, nextSequence: 0 });
      set({ status: 'recording', runId, startedAt, sampleCount: 0, droppedCount: 0, liveDistanceM: 0, path: [], cleanPath: [], error: null, isSimulation: true, liveFix: null, paceWindow: [], segmentStarts: [] });
    } catch (error) {
      set({ status: 'idle', error: 'Could not start simulation.' });
      throw error;
    }
  },

  addSimulatedPoint: async (lon: number, lat: number) => {
    if (!ENABLE_SIMULATION || get().status !== 'recording' || !get().isSimulation) return;
    const from = get().cleanPath.at(-1);
    const distance = from
      ? haversineMetres({ lon: from[0], lat: from[1] }, { lon, lat })
      : 0;
    // Feed a few short virtual fixes so the same spike-cleaning path used by
    // a real run accepts long map taps instead of treating them as teleports.
    const steps = Math.max(1, Math.ceil(distance / 30));
    for (let index = 1; index <= steps; index++) {
      const progress = index / steps;
      await enqueueLocationSample({
        coords: {
          latitude: from ? from[1] + (lat - from[1]) * progress : lat,
          longitude: from ? from[0] + (lon - from[0]) * progress : lon,
          accuracy: 5,
          speed: 3,
        },
        timestamp: Math.max(Date.now(), lastDisplayTimestamp + 1),
        mocked: false,
      } as Location.LocationObject);
    }
  },

  stop: async () => {
    const { status, runId, startedAt } = get();
    if (status !== 'recording' || !runId || !startedAt) return null;

    set({ status: 'stopping' });
    subscription?.remove();
    subscription = null;
    removeAppStateListener();
    await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK).catch(() => undefined);
    await sampleWriteQueue;
    await setActiveRun(null);

    // Preserve indices at GPS gaps. The trail layer simplifies each section
    // independently; flushing the whole path here would join unobserved gaps.
    const finalCleanPath = get().cleanPath;

    const endedAt = new Date();
    await finishLocalRun(runId, endedAt);
    gpsCleaner.reset();

    set({ status: 'idle', runId: null, startedAt: null, cleanPath: finalCleanPath, isSimulation: false });
    return { runId, startedAt, endedAt };
  },
}));

export function resetRecorderStats() {
  useRecorder.setState({ sampleCount: 0, droppedCount: 0, liveDistanceM: 0, path: [], cleanPath: [], isSimulation: false, liveFix: null, paceWindow: [], segmentStarts: [] });
}
