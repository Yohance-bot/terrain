import { useEffect, useState } from 'react';
import { useRecorder } from '@/features/recorder/useRecorder';

function snapshot() {
  const s = useRecorder.getState();
  return { cleanPath: s.cleanPath, fix: s.liveFix, segmentStarts: s.segmentStarts };
}
/** A bounded native publication cadence, independent of SQLite acquisition. */
export function useVisualRun(active: boolean, economy: boolean) {
  const recording = useRecorder(s => s.status === 'recording');
  const runId = useRecorder(s => s.runId);
  const [value, setValue] = useState(snapshot);
  useEffect(() => {
    const update = () => {
      const next = snapshot();
      setValue(prev => prev.cleanPath === next.cleanPath && prev.fix === next.fix ? prev : next);
    };
    update();
    if (!active || !recording) return;
    const timer = setInterval(update, economy ? 2000 : 1000);
    return () => clearInterval(timer);
  }, [active, recording, runId, economy]);
  return value;
}
