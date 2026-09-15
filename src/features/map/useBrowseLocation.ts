import { useEffect, useState } from 'react';
import * as Location from 'expo-location';
import { getMeta, setMeta } from '@/lib/db';
import type { RunFix } from '@/features/hud/telemetry';

const LAST_CENTER_KEY = 'map.last-center.v1';

function asFix(lon: number, lat: number, ts: number, speed = 0, heading: number | null = null, accuracy: number | null = null): RunFix | null {
  if (!Number.isFinite(lon) || !Number.isFinite(lat) || Math.abs(lat) > 85 || Math.abs(lon) > 180) return null;
  return { coordinate: [lon, lat], ts, speedMps: speed, bearing: heading, accuracyM: accuracy, segment: 0 };
}

function fromExpo(pos: Location.LocationObject): RunFix | null {
  return asFix(
    pos.coords.longitude,
    pos.coords.latitude,
    pos.timestamp,
    pos.coords.speed ?? 0,
    pos.coords.heading != null && pos.coords.heading >= 0 ? pos.coords.heading : null,
    pos.coords.accuracy ?? null,
  );
}

/**
 * Permission plus a real coordinate, as soon as either exists.
 *
 * MapLibre's location feed never asks, and does not always emit a first point
 * until the device moves. The camera used to sit on the bundled Jayanagar
 * centre in that gap. Expo last-known / current position, and the last centre
 * we ourselves stored, are enough to open on the player.
 */
export function useBrowseLocation(enabled: boolean): { granted: boolean; fix: RunFix | null } {
  const [granted, setGranted] = useState(false);
  const [fix, setFix] = useState<RunFix | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getMeta(LAST_CENTER_KEY).then(raw => {
      if (cancelled || !raw) return;
      try {
        const parsed = JSON.parse(raw) as { lon?: number; lat?: number; ts?: number };
        const next = asFix(Number(parsed.lon), Number(parsed.lat), Number(parsed.ts) || Date.now());
        if (next) setFix(current => current ?? next);
      } catch { /* ignore a corrupt cache and wait for GPS */ }
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!enabled) {
      setGranted(false);
      return;
    }
    let cancelled = false;
    const publish = (next: RunFix) => {
      setFix(next);
      void setMeta(LAST_CENTER_KEY, JSON.stringify({ lon: next.coordinate[0], lat: next.coordinate[1], ts: next.ts })).catch(() => undefined);
    };
    void (async () => {
      const current = await Location.getForegroundPermissionsAsync();
      const result = current.granted ? current : await Location.requestForegroundPermissionsAsync();
      if (cancelled) return;
      setGranted(result.granted);
      if (!result.granted) return;
      const last = await Location.getLastKnownPositionAsync().catch(() => null);
      if (last && !cancelled) {
        const next = fromExpo(last);
        if (next) publish(next);
      }
      const now = await Promise.race([
        Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
        new Promise<Location.LocationObject | null>(resolve => setTimeout(() => resolve(null), 8_000)),
      ]).catch(() => null);
      if (now && !cancelled) {
        const next = fromExpo(now);
        if (next) publish(next);
      }
    })().catch(() => {
      if (!cancelled) setGranted(false);
    });
    return () => { cancelled = true; };
  }, [enabled]);

  return { granted, fix };
}
