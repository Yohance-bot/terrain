import { useCallback, useEffect, useRef, useState } from "react";
import { api, asRunner, type TestRunner } from "../lib/api";

/**
 * The roster of disposable runners the lab drives, and the live channel that
 * makes sharing and races observable while someone moves the joystick.
 *
 * Positions are pushed on the same endpoint the phone uses, at the same cadence,
 * so what the lab sees is what a friend on a real device would see.
 */

const POSITION_INTERVAL_MS = 4000;

export type LiveFriend = {
  account: { id: string; display_name: string; handle: string };
  lat: number;
  lon: number;
  is_running: boolean;
};

export type LabState = {
  runners: TestRunner[];
  loading: boolean;
  error: string;
  active: TestRunner | null;
  setActiveId: (id: string | null) => void;
  refresh: () => Promise<void>;
  addRunner: (label: string) => Promise<TestRunner>;
  removeRunner: (id: string) => Promise<void>;
  resetLab: () => Promise<void>;
  /** Friends of the active runner who are currently visible to it. */
  live: LiveFriend[];
  races: any[];
};

export function useTestLab(): LabState {
  const [runners, setRunners] = useState<TestRunner[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [live, setLive] = useState<LiveFriend[]>([]);
  const [races, setRaces] = useState<any[]>([]);

  const refresh = useCallback(async () => {
    try {
      const result = await api.listRunners();
      setRunners(result.runners);
      setError("");
      setActiveId((current) =>
        current && result.runners.some((row) => row.account_id === current)
          ? current
          : (result.runners[0]?.account_id ?? null),
      );
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const active = runners.find((row) => row.account_id === activeId) ?? null;

  // Poll what the active runner can see, so turning sharing on or starting a
  // race has a visible effect without a manual refresh.
  useEffect(() => {
    if (!active) {
      setLive([]);
      setRaces([]);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      try {
        const view = await asRunner<any>(active, "/social/live");
        if (!cancelled) {
          setLive(view.friends ?? []);
          setRaces(view.races ?? []);
        }
      } catch {
        // A dropped poll is not worth a banner; the next one usually lands.
      }
    };
    void tick();
    const timer = setInterval(() => void tick(), POSITION_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [active]);

  const addRunner = useCallback(
    async (label: string) => {
      const runner = (await api.addRunner(label)) as TestRunner;
      await refresh();
      setActiveId(runner.account_id);
      return runner;
    },
    [refresh],
  );

  const removeRunner = useCallback(
    async (id: string) => {
      await api.removeRunner(id);
      await refresh();
    },
    [refresh],
  );

  const resetLab = useCallback(async () => {
    await api.resetLab();
    setActiveId(null);
    await refresh();
  }, [refresh]);

  return {
    runners,
    loading,
    error,
    active,
    setActiveId,
    refresh,
    addRunner,
    removeRunner,
    resetLab,
    live,
    races,
  };
}

/**
 * Stream the joystick's position as the active runner while it is moving.
 *
 * Only runs while a runner is selected and movement is on, because a position
 * that keeps arriving after someone stops testing would leave a test account
 * visible to its friends indefinitely.
 */
export function useLivePosition(
  runner: TestRunner | null,
  position: [number, number],
  enabled: boolean,
) {
  const latest = useRef(position);
  latest.current = position;

  useEffect(() => {
    if (!runner || !enabled) return;
    const send = async () => {
      try {
        await asRunner(runner, "/social/position", {
          method: "POST",
          body: JSON.stringify({
            lat: latest.current[1],
            lon: latest.current[0],
            is_running: true,
          }),
        });
      } catch {
        // Same reasoning as the live poll: a missed frame is not an error.
      }
    };
    void send();
    const timer = setInterval(() => void send(), POSITION_INTERVAL_MS);
    return () => {
      clearInterval(timer);
      // Disappear from friends' maps as soon as movement stops.
      void asRunner(runner, "/social/position", { method: "DELETE" }).catch(
        () => undefined,
      );
    };
  }, [runner, enabled]);
}
