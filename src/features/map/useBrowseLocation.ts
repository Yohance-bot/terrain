import { useEffect, useState } from 'react';
import * as Location from 'expo-location';

/**
 * Ask for foreground location when the map is shown, not when a run starts.
 *
 * The browse map follows MapLibre's location feed, which never requests
 * permission itself. Until something else does, the camera sits on the bundled
 * Jayanagar centre — which reads as a random neighbourhood. Background access
 * is still only requested from the recorder, because walking around the map
 * does not need it.
 */
export function useBrowseLocation(enabled: boolean) {
  const [granted, setGranted] = useState(false);
  useEffect(() => {
    if (!enabled) {
      setGranted(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      const current = await Location.getForegroundPermissionsAsync();
      const result = current.granted ? current : await Location.requestForegroundPermissionsAsync();
      if (!cancelled) setGranted(result.granted);
    })().catch(() => {
      if (!cancelled) setGranted(false);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return granted;
}
