import { useEffect, useRef } from 'react';
import { create } from 'zustand';
import { useRecorder } from '@/features/recorder/useRecorder';
import { CheckpointLedger, type HudCue, type Waypoint } from './events';
import { useHudPreferences } from './usePresentation';

export const useRunCues = create<{ cue: HudCue | null; emit: (cue: HudCue) => void; clear: () => void }>((set, get) => ({
  cue: null,
  emit: cue => {
    const previous = get().cue;
    if (previous?.id === cue.id) return;
    if (cue.kind === 'checkpoint' && previous && previous.kind !== 'checkpoint' && Date.now() - previous.createdAt < 3200) return;
    set({ cue });
  },
  clear: () => set({ cue: null }),
}));
const NO_WAYPOINTS: Waypoint[] = [];
export function useCheckpoints(active: boolean, waypoints: Waypoint[] = NO_WAYPOINTS) {
  const ledger = useRef(new CheckpointLedger());
  const units = useHudPreferences(s => s.units);
  useEffect(() => {
    const handle = (state: ReturnType<typeof useRecorder.getState>) => {
      if (!state.runId || !state.liveFix || state.status !== 'recording') return;
      const cue = ledger.current.update(state.runId, state.liveDistanceM, state.liveFix, active && Date.now() - state.liveFix.ts < 10_000, units === 'mi' ? 1609.344 : 1000, waypoints);
      if (cue) useRunCues.getState().emit(cue);
    };
    handle(useRecorder.getState());
    return useRecorder.subscribe(handle);
  }, [active, units, waypoints]);
}
