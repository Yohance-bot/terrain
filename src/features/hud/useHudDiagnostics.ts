import { useCallback, useEffect, useRef } from 'react';
import { useRecorder } from '@/features/recorder/useRecorder';

const ENABLED = __DEV__ && process.env.EXPO_PUBLIC_HUD_DIAGNOSTICS === 'true';
/** Opt-in only: per-frame bridge callbacks add overhead, so production keeps them absent. */
export function useHudDiagnostics(active: boolean) {
  const frames = useRef(0);
  const onFrame = useCallback(() => { frames.current++; }, []);
  useEffect(() => {
    if (!ENABLED || !active) return;
    let previous = Date.now(), start = previous, maxDrift = 0, ticks = 0;
    frames.current = 0;
    const timer = setInterval(() => {
      const now = Date.now();
      maxDrift = Math.max(maxDrift, now - previous - 1000); previous = now;
      if (++ticks < 10) return;
      const s = useRecorder.getState();
      console.info('[HUD diagnostic]', JSON.stringify({ seconds: (now - start) / 1000, renderedFrames: frames.current, maxTimerDriftMs: maxDrift, acceptedFixes: s.sampleCount, rejectedFixes: s.droppedCount, routePoints: s.cleanPath.length, sections: s.segmentStarts.length + 1 }));
      ticks = 0; start = now; frames.current = 0; maxDrift = 0;
    }, 1000);
    return () => clearInterval(timer);
  }, [active]);
  return ENABLED && active ? onFrame : undefined;
}
