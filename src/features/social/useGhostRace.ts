import { create } from 'zustand';

import { fetchGhost, finishGhostAttempt, startGhostAttempt } from '@/services/api/client';
import type { GhostDetail } from '@/services/api/types';

import { cumulativeDistances, ghostAt, type GhostPoint, type GhostState } from './ghostPlayback';

/**
 * An in-progress race against a recorded ghost.
 *
 * The route is downloaded once and replayed from a local clock. The server is
 * told when the attempt starts and how it ended, and nothing in between.
 */

// The ghost marker moves on its own clock rather than on GPS fixes, so it keeps
// gliding between the fixes the phone actually delivers.
const PLAYBACK_INTERVAL_MS = 250;

interface GhostRaceState {
  ghost: GhostDetail | null;
  attemptId: string | null;
  startedAtMs: number | null;
  elapsedMs: number;
  ghostState: GhostState | null;
  loading: boolean;
  error: string | null;

  begin: (ghostId: string) => Promise<void>;
  /** Stop replaying and record the result. */
  end: (options: { runId?: string; save?: boolean }) => Promise<{ beatGhost: boolean } | null>;
  reset: () => void;
}

let playbackTimer: ReturnType<typeof setInterval> | null = null;
let distances: number[] = [];

function stopPlayback() {
  if (playbackTimer) clearInterval(playbackTimer);
  playbackTimer = null;
}

export const useGhostRace = create<GhostRaceState>((set, get) => ({
  ghost: null,
  attemptId: null,
  startedAtMs: null,
  elapsedMs: 0,
  ghostState: null,
  loading: false,
  error: null,

  begin: async (ghostId) => {
    set({ loading: true, error: null });
    try {
      const ghost = await fetchGhost(ghostId);
      const attempt = await startGhostAttempt(ghostId);
      const path = ghost.path as GhostPoint[];
      distances = cumulativeDistances(path);
      const startedAtMs = Date.now();
      set({
        ghost,
        attemptId: attempt.id,
        startedAtMs,
        elapsedMs: 0,
        ghostState: ghostAt(path, 0, distances),
        loading: false,
      });

      stopPlayback();
      playbackTimer = setInterval(() => {
        const state = get();
        if (!state.ghost || state.startedAtMs === null) return;
        const elapsedMs = Date.now() - state.startedAtMs;
        set({
          elapsedMs,
          ghostState: ghostAt(state.ghost.path as GhostPoint[], elapsedMs, distances),
        });
      }, PLAYBACK_INTERVAL_MS);
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : 'Could not load that ghost.',
      });
    }
  },

  end: async ({ runId, save = true }) => {
    const { attemptId, startedAtMs, ghost } = get();
    stopPlayback();
    if (!attemptId || startedAtMs === null || !ghost) {
      get().reset();
      return null;
    }
    const elapsedS = Math.max(1, Math.round((Date.now() - startedAtMs) / 1000));
    let beatGhost = elapsedS < ghost.duration_s;
    if (save) {
      try {
        const finished = await finishGhostAttempt(attemptId, elapsedS, runId);
        beatGhost = finished.beat_ghost ?? beatGhost;
      } catch {
        // An unreported attempt is a lost record, not a lost run; the run
        // itself is submitted through its own path.
      }
    }
    get().reset();
    return { beatGhost };
  },

  reset: () => {
    stopPlayback();
    distances = [];
    set({
      ghost: null,
      attemptId: null,
      startedAtMs: null,
      elapsedMs: 0,
      ghostState: null,
      error: null,
    });
  },
}));
