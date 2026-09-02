import type { StoredSample } from '@/lib/db';

/**
 * Run submission contract: GPS sample timestamps are epoch milliseconds as integers.
 * expo-location may supply sub-millisecond floats; normalize at recording and before
 * upload so queued runs with legacy fractional values still submit cleanly.
 */
export function normalizeSampleTimestampMs(ts: number): number {
  return Math.trunc(ts);
}

export function normalizeStoredSample(sample: StoredSample): StoredSample {
  return { ...sample, ts: normalizeSampleTimestampMs(sample.ts) };
}
