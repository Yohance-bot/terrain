import { rollingPace, type TimedDistance } from '@/features/hud/telemetry';

export interface RunActivityNative {
  start(runId: string, startedAtMs: number, simulation: boolean, units: string): Promise<boolean>;
  update(runId: string, distanceM: number, paceSeconds: number | null, units: string): Promise<void>;
  end(runId: string, distanceM: number, endedAtMs: number): Promise<void>;
  endAll(): Promise<void>;
}
/** Serialized so a late start/update cannot recreate a run after Finish. */
export function createRunActivityClient(module: RunActivityNative | null, onError: (error: unknown) => void = () => undefined) {
  let queue = Promise.resolve();
  let activeRun: string | null = null;
  let lastUpdate = 0;
  const enqueue = (work: () => Promise<unknown>) => {
    queue = queue.then(work).then(() => undefined).catch(error => {
      // An optional OS surface must never prevent raw GPS from being saved.
      onError(error);
    });
    return queue;
  };
  return {
    start(runId: string, startedAtMs: number, simulation: boolean, units: string) {
      if (!module) return Promise.resolve();
      activeRun = runId;
      lastUpdate = 0;
      return enqueue(() => module.start(runId, startedAtMs, simulation, units));
    },
    update(runId: string, distanceM: number, points: TimedDistance[], units: string, now = Date.now()) {
      if (!module || activeRun !== runId || now - lastUpdate < 5000) return Promise.resolve();
      lastUpdate = now;
      const pace = rollingPace(points, now, units === 'mi' ? 1609.344 : 1000);
      return enqueue(() => module.update(runId, distanceM, pace, units));
    },
    end(runId: string, distanceM: number, endedAtMs: number) {
      if (activeRun === runId) activeRun = null;
      if (!module) return Promise.resolve();
      return enqueue(() => module.end(runId, distanceM, endedAtMs));
    },
    clear() {
      activeRun = null;
      if (!module) return Promise.resolve();
      return enqueue(() => module.endAll());
    },
  };
}
