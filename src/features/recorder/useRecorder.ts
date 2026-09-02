import * as Crypto from 'expo-crypto';
import * as Location from 'expo-location';
import * as TaskManager from 'expo-task-manager';
import { create } from 'zustand';
import { AppState, type AppStateStatus } from 'react-native';

import { ENABLE_SIMULATION, GPS_INTERVAL_MS, MAX_ACCURACY_M } from '@/constants/config';
import {
  appendSample,
  createLocalRun,
  finishLocalRun,
  getMeta,
  recordRunInterruption,
  setMeta,
  type StoredSample,
} from '@/lib/db';
import { haversineMetres } from '@/lib/geo';
import { IncrementalGpsCleaner, type GeoCoord } from '@/lib/gpsClean';
import { normalizeSampleTimestampMs } from '@/lib/runSamples';

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
 * On run end, cleanPath is finalized with RDP + turn smoothing via flush().
 * Raw samples in SQLite are untouched — the backend remains authoritative.
 *
 * Note what this store does NOT expose: any territory information. Per
 * `01_CORE_MECHANICS` Chapters 10 and 12, nothing about territories is shown
 * while a run is in progress. Distance and elapsed time only.
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
   * On run end it is finalized with RDP + turn smoothing.
   */
  cleanPath: GeoCoord[];
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

// Module-level cleaner — lives as long as the JS bundle, reset on each run.
const gpsCleaner = new IncrementalGpsCleaner();

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

      const { latitude, longitude, accuracy, speed } = location.coords;
      const sample: StoredSample = {
        ts: normalizeSampleTimestampMs(location.timestamp),
        lat: latitude,
        lon: longitude,
        accuracy_m: accuracy ?? null,
        speed_mps: speed ?? null,
        provider: location.mocked === undefined ? null : 'expo-location',
        is_mock: location.mocked ?? false,
      };

      try {
        await appendSample(activeRun.runId, activeRun.nextSequence, sample);
      } catch {
        await recordRunInterruption(activeRun.runId, 'sample_persist_failed').catch(() => undefined);
        return;
      }

      const recorder = useRecorder.getState();
      if (recorder.status !== 'recording' || recorder.runId !== activeRun.runId) return;

      // Push through the cleaning pipeline (applies its own accuracy + spike filters).
      // This runs for every sample, including ones that fail MAX_ACCURACY_M below,
      // so the cleaner's tighter GPS_ACCURACY_CUTOFF_M gate fires independently.
      const newCleanPath = gpsCleaner.push({
        lat: latitude,
        lon: longitude,
        accuracy: accuracy ?? undefined,
      });

      // Raw path: loose accuracy gate (MAX_ACCURACY_M). Used for debug stats only.
      const usable = accuracy == null || accuracy <= MAX_ACCURACY_M;
      if (!usable) {
        useRecorder.setState((state) => ({
          droppedCount: state.droppedCount + 1,
          cleanPath: newCleanPath,
        }));
        return;
      }

      // The HUD follows accepted cleaned points, not every raw device fix.
      // That keeps both distance and pace aligned with what the map activates.
      const previousCleanPoint = recorder.cleanPath.at(-1);
      const latestCleanPoint = newCleanPath.at(-1);
      const acceptedNewCleanPoint =
        latestCleanPoint && latestCleanPoint !== previousCleanPoint
          ? haversineMetres(
              { lon: previousCleanPoint?.[0] ?? latestCleanPoint[0], lat: previousCleanPoint?.[1] ?? latestCleanPoint[1] },
              { lon: latestCleanPoint[0], lat: latestCleanPoint[1] },
            )
          : 0;

      useRecorder.setState((state) => ({
        sampleCount: state.sampleCount + 1,
        liveDistanceM: state.liveDistanceM + acceptedNewCleanPoint,
        path: [...state.path, [longitude, latitude]],
        cleanPath: newCleanPath,
      }));
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

  start: async () => {
    if (get().status !== 'idle') return;
    set({ status: 'starting', error: null, isSimulation: false });

    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') {
      set({ status: 'idle', error: 'Location permission is required to record a run.' });
      return;
    }

    const runId = Crypto.randomUUID();
    const startedAt = new Date();
    await createLocalRun(runId, startedAt);

    gpsCleaner.reset();

    try {
      await setActiveRun({ runId, nextSequence: 0 });

      const locationOptions = {
        accuracy: Location.Accuracy.BestForNavigation,
        timeInterval: GPS_INTERVAL_MS,
        distanceInterval: 0,
      };
      const canUseBackgroundTask =
        (await TaskManager.isAvailableAsync()) && (await Location.isBackgroundLocationAvailableAsync());
      const backgroundPermission = canUseBackgroundTask
        ? await Location.requestBackgroundPermissionsAsync()
        : null;

      if (backgroundPermission?.granted) {
        await Location.startLocationUpdatesAsync(BACKGROUND_LOCATION_TASK, {
          ...locationOptions,
          activityType: Location.ActivityType.Fitness,
          showsBackgroundLocationIndicator: true,
          foregroundService: {
            notificationTitle: 'Run recording in progress',
            notificationBody: 'Your route is being recorded.',
            killServiceOnDestroy: true,
          },
        });
      } else {
        // Background permission and TaskManager availability are enhancements,
        // not prerequisites for recording a run.
        subscription = await Location.watchPositionAsync(locationOptions, (position) => {
          void enqueueLocationSample(position);
        });
      }
      observeForegroundInterruption(runId);
      set({
        status: 'recording',
        runId,
        startedAt,
        sampleCount: 0,
        droppedCount: 0,
        liveDistanceM: 0,
        path: [],
        cleanPath: [],
      });
    } catch (error) {
      const endedAt = new Date();
      subscription?.remove();
      subscription = null;
      await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK).catch(() => undefined);
      await setActiveRun(null);
      await recordRunInterruption(runId, 'location_subscription_failed', endedAt);
      await finishLocalRun(runId, endedAt);
      gpsCleaner.reset();
      set({
        status: 'idle',
        runId: null,
        startedAt: null,
        error: error instanceof Error ? error.message : 'Could not start location recording.',
      });
    }
  },

  startSimulation: async () => {
    if (!ENABLE_SIMULATION || get().status !== 'idle') return;
    const runId = Crypto.randomUUID();
    const startedAt = new Date();
    await createLocalRun(runId, startedAt);
    gpsCleaner.reset();
    await setActiveRun({ runId, nextSequence: 0 });
    set({ status: 'recording', runId, startedAt, sampleCount: 0, droppedCount: 0, liveDistanceM: 0, path: [], cleanPath: [], error: null, isSimulation: true });
  },

  addSimulatedPoint: async (lon: number, lat: number) => {
    if (!ENABLE_SIMULATION || get().status !== 'recording') return;
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
        timestamp: Date.now() + index * 1_000,
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

    // Finalize the clean path with RDP + turn smoothing before clearing state.
    const finalCleanPath = gpsCleaner.flush();
    gpsCleaner.reset();

    const endedAt = new Date();
    await finishLocalRun(runId, endedAt);

    set({ status: 'idle', runId: null, startedAt: null, cleanPath: finalCleanPath, isSimulation: false });
    return { runId, startedAt, endedAt };
  },
}));

export function resetRecorderStats() {
  useRecorder.setState({ sampleCount: 0, droppedCount: 0, liveDistanceM: 0, path: [], cleanPath: [], isSimulation: false });
}
