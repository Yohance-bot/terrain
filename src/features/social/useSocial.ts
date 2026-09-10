import * as Location from 'expo-location';
import { create } from 'zustand';

import { useRecorder } from '@/features/recorder/useRecorder';

import {
  announceRunStart,
  clearPosition,
  fetchLive,
  fetchSocialEvents,
  markEventsRead,
  reportPosition,
} from '@/services/api/client';
import type { FriendPosition, RaceRecord, SocialEvent } from '@/services/api/types';

/**
 * The live social channel.
 *
 * There is no socket and no push transport: the client polls while there is a
 * reason to, and stops the moment there is not. Presence runs only when the
 * player is recording, racing, or has chosen to share with someone — never as a
 * background default.
 */

// One position every five seconds is enough to follow a runner on a map and
// cheap enough to sit alongside GPS recording.
const PRESENCE_INTERVAL_MS = 5_000;
// The event feed is checked far less often; nothing in it is time-critical.
const EVENT_INTERVAL_MS = 30_000;

type Fix = {
  lat: number;
  lon: number;
  accuracy_m: number | null;
  heading: number | null;
  speed_mps: number | null;
};

interface SocialState {
  friends: FriendPosition[];
  races: RaceRecord[];
  events: SocialEvent[];
  unreadCount: number;
  presenceActive: boolean;
  lastError: string | null;

  /** Feed a fix from whichever watch is already running. */
  pushFix: (fix: Fix, context?: { isRunning?: boolean; runId?: string | null }) => void;
  /** Begin reporting position. Safe to call repeatedly. */
  startPresence: (options?: { ownWatch?: boolean }) => Promise<void>;
  stopPresence: (options?: { disappear?: boolean }) => Promise<void>;
  refreshLive: () => Promise<void>;
  refreshEvents: () => Promise<void>;
  markRead: () => Promise<void>;
  announceRun: (runId: string) => Promise<void>;
}

let presenceTimer: ReturnType<typeof setInterval> | null = null;
let eventTimer: ReturnType<typeof setInterval> | null = null;
let watch: Location.LocationSubscription | null = null;
let latestFix: Fix | null = null;
let runContext: { isRunning: boolean; runId: string | null } = { isRunning: false, runId: null };

export const useSocial = create<SocialState>((set, get) => ({
  friends: [],
  races: [],
  events: [],
  unreadCount: 0,
  presenceActive: false,
  lastError: null,

  pushFix: (fix, context) => {
    latestFix = fix;
    if (context) {
      runContext = {
        isRunning: context.isRunning ?? runContext.isRunning,
        runId: context.runId ?? runContext.runId,
      };
    }
  },

  startPresence: async ({ ownWatch = false } = {}) => {
    if (get().presenceActive) return;
    set({ presenceActive: true, lastError: null });

    if (ownWatch && !watch) {
      // Only used when nothing else is watching location — during a race the
      // player may not be recording a run at all.
      const permission = await Location.getForegroundPermissionsAsync();
      if (permission.granted) {
        watch = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.Balanced, timeInterval: PRESENCE_INTERVAL_MS, distanceInterval: 10 },
          (position) => {
            latestFix = {
              lat: position.coords.latitude,
              lon: position.coords.longitude,
              accuracy_m: position.coords.accuracy ?? null,
              heading: position.coords.heading ?? null,
              speed_mps: position.coords.speed ?? null,
            };
          }
        );
      }
    }

    const tick = async () => {
      try {
        // Posting a position returns the visible friends in the same trip, so a
        // moving player never pays for two requests.
        const view = latestFix
          ? await reportPosition({
              ...latestFix,
              is_running: runContext.isRunning,
              run_id: runContext.runId,
            })
          : await fetchLive();
        set({ friends: view.friends, races: view.races, lastError: null });
      } catch (error) {
        set({ lastError: error instanceof Error ? error.message : 'Live sharing is offline' });
      }
    };
    void tick();
    presenceTimer = setInterval(() => void tick(), PRESENCE_INTERVAL_MS);
  },

  stopPresence: async ({ disappear = true } = {}) => {
    if (presenceTimer) clearInterval(presenceTimer);
    presenceTimer = null;
    watch?.remove();
    watch = null;
    latestFix = null;
    runContext = { isRunning: false, runId: null };
    set({ presenceActive: false, friends: [] });
    if (disappear) {
      // Leaving the screen should remove you from friends' maps straight away
      // rather than after the freshness window quietly expires.
      await clearPosition().catch(() => undefined);
    }
  },

  refreshLive: async () => {
    try {
      const view = await fetchLive();
      set({ friends: view.friends, races: view.races });
    } catch {
      // A failed poll is not worth surfacing; the next one usually succeeds.
    }
  },

  refreshEvents: async () => {
    try {
      const events = await fetchSocialEvents();
      set({ events, unreadCount: events.filter((event) => !event.read_at).length });
    } catch {
      // Same: the feed catches up on the next poll.
    }
  },

  markRead: async () => {
    await markEventsRead().catch(() => undefined);
    set((state) => ({
      unreadCount: 0,
      events: state.events.map((event) => ({
        ...event,
        read_at: event.read_at ?? new Date().toISOString(),
      })),
    }));
  },

  announceRun: async (runId) => {
    await announceRunStart(runId).catch(() => undefined);
  },
}));

/** Poll the event feed while the app is open. Idempotent. */
export function startEventPolling(): void {
  if (eventTimer) return;
  void useSocial.getState().refreshEvents();
  eventTimer = setInterval(() => void useSocial.getState().refreshEvents(), EVENT_INTERVAL_MS);
}

export function stopEventPolling(): void {
  if (eventTimer) clearInterval(eventTimer);
  eventTimer = null;
}

/**
 * Forward the recorder's GPS fixes into the presence channel.
 *
 * The recorder already holds the only location subscription during a run, and
 * its `liveFix` is the cleaned position the HUD draws — the same one a friend
 * should see, rather than a raw duplicate fix from a second watch.
 */
export function linkRecorderFixes(): () => void {
  return useRecorder.subscribe((state) => {
    const fix = state.liveFix;
    if (!fix) return;
    useSocial.getState().pushFix(
      {
        lat: fix.coordinate[1],
        lon: fix.coordinate[0],
        accuracy_m: fix.accuracyM ?? null,
        heading: fix.bearing ?? null,
        speed_mps: fix.speedMps ?? null,
      },
      { isRunning: state.status === 'recording', runId: state.runId }
    );
  });
}
