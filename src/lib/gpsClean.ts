/**
 * GPS Cleaning Pipeline
 *
 * Pure functions — no React, no side effects, fully unit-testable.
 *
 * Pipeline order (full-batch):
 *   raw GPS → accuracy filter → spike rejection → EMA smooth
 *           → RDP simplify → turn detection → local turn smooth
 *           → cleanedPath
 *
 * For live tracking, use IncrementalGpsCleaner which maintains running EMA
 * state so it doesn't replay the whole buffer on every GPS fix.
 *
 * All thresholds live in GpsCleanOptions sourced from config.ts constants so
 * they can be tuned without touching algorithm code.
 */

import {
  GPS_ACCURACY_CUTOFF_M,
  GPS_EMA_ALPHA,
  GPS_RDP_EPSILON_M,
  GPS_SPIKE_MAX_JUMP_M,
  GPS_TURN_ANGLE_DEG,
  GPS_TURN_SMOOTH_RADIUS_M,
} from '@/constants/config';
import { haversineMetres } from '@/lib/geo';

export type LatLon = { lat: number; lon: number; accuracy?: number };

/** [lon, lat] — GeoJSON coordinate order, matching useRecorder's path. */
export type GeoCoord = [number, number];

export interface GpsCleanOptions {
  /** Drop points with horizontal accuracy worse than this (metres). */
  accuracyCutoffM: number;
  /** Reject a point if it would require speed > this to reach from the prior clean point. */
  spikeMaxJumpM: number;
  /** EMA smoothing factor. 0 = frozen, 1 = no smoothing. */
  emaAlpha: number;
  /** RDP epsilon in metres. */
  rdpEpsilonM: number;
  /** Bearing-change threshold to classify a point as a turn vertex (degrees). */
  turnAngleDeg: number;
  /** Radius around each turn within which local smoothing is applied (metres). */
  turnSmoothRadiusM: number;
}

export const DEFAULT_CLEAN_OPTIONS: GpsCleanOptions = {
  accuracyCutoffM: GPS_ACCURACY_CUTOFF_M,
  spikeMaxJumpM: GPS_SPIKE_MAX_JUMP_M,
  emaAlpha: GPS_EMA_ALPHA,
  rdpEpsilonM: GPS_RDP_EPSILON_M,
  turnAngleDeg: GPS_TURN_ANGLE_DEG,
  turnSmoothRadiusM: GPS_TURN_SMOOTH_RADIUS_M,
};

// ── 1. Accuracy filter ─────────────────────────────────────────────────────

/** Drop any point whose reported horizontal accuracy is worse than cutoff. */
export function filterAccuracy(pts: LatLon[], cutoffM: number): LatLon[] {
  return pts.filter((p) => p.accuracy == null || p.accuracy <= cutoffM);
}

// ── 2. Spike / outlier rejection ───────────────────────────────────────────

/**
 * Reject a point if the distance from the last accepted point exceeds maxJumpM.
 * A runner doing 6 min/km covers ~2.8 m/s; even at 3-second intervals they
 * move < 10 m. 80 m catches GPS teleports while remaining safe for cycling.
 */
export function filterSpikes(pts: LatLon[], maxJumpM: number): LatLon[] {
  if (pts.length === 0) return [];
  const result: LatLon[] = [pts[0]!];
  for (let i = 1; i < pts.length; i++) {
    const prev = result[result.length - 1]!;
    const curr = pts[i]!;
    const dist = haversineMetres(
      { lat: prev.lat, lon: prev.lon },
      { lat: curr.lat, lon: curr.lon },
    );
    if (dist <= maxJumpM) {
      result.push(curr);
    }
    // silently drop — raw data in SQLite preserves it for debugging
  }
  return result;
}

// ── 3. EMA smoothing ───────────────────────────────────────────────────────

/**
 * Exponential Moving Average smoothing applied independently to lat and lon.
 * alpha=1 → output === input (no smoothing).
 * alpha=0.4 → moderate smoothing; retains directional changes faster than
 * a sliding-window average.
 *
 * Accuracy values are not smoothed — they're only used for pre-filtering.
 */
export function emaSmooth(pts: LatLon[], alpha: number): LatLon[] {
  if (pts.length === 0) return [];
  const result: LatLon[] = [pts[0]!];
  for (let i = 1; i < pts.length; i++) {
    const prev = result[i - 1]!;
    const curr = pts[i]!;
    result.push({
      lat: alpha * curr.lat + (1 - alpha) * prev.lat,
      lon: alpha * curr.lon + (1 - alpha) * prev.lon,
      accuracy: curr.accuracy,
    });
  }
  return result;
}

// ── 4. RDP simplification ──────────────────────────────────────────────────

/** Flat-earth perpendicular distance from `point` to the line (lineStart→lineEnd). */
function perpendicularDistanceM(
  point: LatLon,
  lineStart: LatLon,
  lineEnd: LatLon,
): number {
  // Degrees-to-metres conversion at the local latitude.
  const lat0 = (lineStart.lat + lineEnd.lat) / 2;
  const cosLat = Math.cos((lat0 * Math.PI) / 180);
  const EARTH_R = 6_371_008.8;
  const DEG_LAT = (EARTH_R * Math.PI) / 180;
  const DEG_LON = DEG_LAT * cosLat;

  const x1 = lineStart.lon * DEG_LON;
  const y1 = lineStart.lat * DEG_LAT;
  const x2 = lineEnd.lon * DEG_LON;
  const y2 = lineEnd.lat * DEG_LAT;
  const px = point.lon * DEG_LON;
  const py = point.lat * DEG_LAT;

  const dx = x2 - x1;
  const dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.hypot(px - x1, py - y1);

  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lenSq));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function rdpRecursive(
  pts: LatLon[],
  start: number,
  end: number,
  epsilonM: number,
  kept: Set<number>,
): void {
  if (end <= start + 1) return;
  let maxDist = 0;
  let maxIdx = start;
  for (let i = start + 1; i < end; i++) {
    const d = perpendicularDistanceM(pts[i]!, pts[start]!, pts[end]!);
    if (d > maxDist) {
      maxDist = d;
      maxIdx = i;
    }
  }
  if (maxDist > epsilonM) {
    kept.add(maxIdx);
    rdpRecursive(pts, start, maxIdx, epsilonM, kept);
    rdpRecursive(pts, maxIdx, end, epsilonM, kept);
  }
}

/** Ramer-Douglas-Peucker simplification. Always preserves start and end. */
export function rdpSimplify(pts: LatLon[], epsilonM: number): LatLon[] {
  if (pts.length <= 2) return [...pts];
  const kept = new Set<number>([0, pts.length - 1]);
  rdpRecursive(pts, 0, pts.length - 1, epsilonM, kept);
  return [...kept].sort((a, b) => a - b).map((i) => pts[i]!);
}

// ── 5. Turn detection ──────────────────────────────────────────────────────

function bearingDeg(from: LatLon, to: LatLon): number {
  const dLon = ((to.lon - from.lon) * Math.PI) / 180;
  const lat1 = (from.lat * Math.PI) / 180;
  const lat2 = (to.lat * Math.PI) / 180;
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x =
    Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function angleDiff(a: number, b: number): number {
  const diff = Math.abs(a - b) % 360;
  return diff > 180 ? 360 - diff : diff;
}

/** Returns indices of points where a genuine direction change >= thresholdDeg occurs. */
export function detectTurns(pts: LatLon[], thresholdDeg: number): number[] {
  if (pts.length < 3) return [];
  const turns: number[] = [];
  for (let i = 1; i < pts.length - 1; i++) {
    const bearingIn = bearingDeg(pts[i - 1]!, pts[i]!);
    const bearingOut = bearingDeg(pts[i]!, pts[i + 1]!);
    if (angleDiff(bearingIn, bearingOut) >= thresholdDeg) {
      turns.push(i);
    }
  }
  return turns;
}

// ── 6. Local turn smoothing ────────────────────────────────────────────────

/**
 * Around each detected turn apex, insert chord midpoints within smoothRadiusM
 * to soften the corner. Straight-road segments are not touched.
 */
export function turnSmooth(
  pts: LatLon[],
  turnIndices: number[],
  smoothRadiusM: number,
): LatLon[] {
  if (turnIndices.length === 0 || pts.length < 3) return pts;
  const turnSet = new Set(turnIndices);
  const result: LatLon[] = [];

  for (let i = 0; i < pts.length; i++) {
    const pt = pts[i]!;
    if (!turnSet.has(i) || i === 0 || i === pts.length - 1) {
      result.push(pt);
      continue;
    }
    const prev = pts[i - 1]!;
    const next = pts[i + 1]!;
    const dPrev = haversineMetres({ lat: pt.lat, lon: pt.lon }, { lat: prev.lat, lon: prev.lon });
    const dNext = haversineMetres({ lat: pt.lat, lon: pt.lon }, { lat: next.lat, lon: next.lon });

    // Interpolation params — never go past the midpoint of each segment.
    const tPrev = dPrev > 0 ? Math.min(smoothRadiusM / dPrev, 0.5) : 0;
    const tNext = dNext > 0 ? Math.min(smoothRadiusM / dNext, 0.5) : 0;

    const approachLat = pt.lat + tPrev * (prev.lat - pt.lat);
    const approachLon = pt.lon + tPrev * (prev.lon - pt.lon);
    const exitLat = pt.lat + tNext * (next.lat - pt.lat);
    const exitLon = pt.lon + tNext * (next.lon - pt.lon);
    const midLat = (approachLat + exitLat) / 2;
    const midLon = (approachLon + exitLon) / 2;

    result.push({ lat: approachLat, lon: approachLon });
    result.push({ lat: midLat, lon: midLon });
    result.push({ lat: exitLat, lon: exitLon });
  }
  return result;
}

// ── Full batch pipeline ────────────────────────────────────────────────────

export interface CleanResult {
  /** Cleaned path in GeoJSON [lon, lat] order. */
  cleanedPath: GeoCoord[];
  /** How many raw points were dropped (accuracy or spike). */
  droppedCount: number;
}

/**
 * Run the full cleaning pipeline on a complete array of raw GPS points.
 * Suitable for post-run finalization. For live tracking, use IncrementalGpsCleaner.
 */
export function cleanGps(rawPts: LatLon[], options: Partial<GpsCleanOptions> = {}): CleanResult {
  const opts: GpsCleanOptions = { ...DEFAULT_CLEAN_OPTIONS, ...options };

  const afterAccuracy = filterAccuracy(rawPts, opts.accuracyCutoffM);
  const afterSpikes = filterSpikes(afterAccuracy, opts.spikeMaxJumpM);
  const droppedCount = rawPts.length - afterSpikes.length;
  const smoothed = emaSmooth(afterSpikes, opts.emaAlpha);
  const simplified = rdpSimplify(smoothed, opts.rdpEpsilonM);
  const turns = detectTurns(simplified, opts.turnAngleDeg);
  const finalPts = turnSmooth(simplified, turns, opts.turnSmoothRadiusM);

  return {
    cleanedPath: finalPts.map((p) => [p.lon, p.lat]),
    droppedCount,
  };
}

// ── Incremental cleaner (live tracking) ───────────────────────────────────

/**
 * Maintains running EMA state so live tracking is O(1) per GPS fix rather
 * than replaying the whole buffer.
 *
 * Usage:
 *   const cleaner = new IncrementalGpsCleaner();
 *   // on each GPS fix:
 *   const liveCleanPath = cleaner.push({ lat, lon, accuracy });
 *   // on run end:
 *   const finalCleanPath = cleaner.flush(); // applies RDP + turn smooth
 *   cleaner.reset();
 */
export class IncrementalGpsCleaner {
  private readonly opts: GpsCleanOptions;
  private emaLat: number | null = null;
  private emaLon: number | null = null;
  private smoothedBuffer: LatLon[] = [];
  private lastCleanPoint: LatLon | null = null;
  private _droppedCount = 0;
  private coordinates: GeoCoord[] = [];

  get droppedCount(): number {
    return this._droppedCount;
  }

  constructor(opts: Partial<GpsCleanOptions> = {}) {
    this.opts = { ...DEFAULT_CLEAN_OPTIONS, ...opts };
  }

  /**
   * Push a new raw GPS fix through the incremental pipeline.
   * Returns the updated clean path (EMA-smoothed, no RDP yet — see flush()).
   * Dropped points return the existing clean path unchanged.
   */
  push(pt: LatLon): GeoCoord[] {
    if (!Number.isFinite(pt.lat) || !Number.isFinite(pt.lon) || Math.abs(pt.lat) > 90 || Math.abs(pt.lon) > 180 || (pt.accuracy != null && (!Number.isFinite(pt.accuracy) || pt.accuracy < 0))) {
      this._droppedCount++;
      return this.coordinates;
    }
    // Step 1: accuracy filter
    if (pt.accuracy != null && pt.accuracy > this.opts.accuracyCutoffM) {
      this._droppedCount++;
      return this.liveCleanPath();
    }

    // Step 2: spike rejection
    if (this.lastCleanPoint !== null) {
      const dist = haversineMetres(
        { lat: this.lastCleanPoint.lat, lon: this.lastCleanPoint.lon },
        { lat: pt.lat, lon: pt.lon },
      );
      if (dist > this.opts.spikeMaxJumpM) {
        this._droppedCount++;
        return this.liveCleanPath();
      }
    }

    // Step 3: incremental EMA smoothing
    if (this.emaLat === null || this.emaLon === null) {
      this.emaLat = pt.lat;
      this.emaLon = pt.lon;
    } else {
      this.emaLat = this.opts.emaAlpha * pt.lat + (1 - this.opts.emaAlpha) * this.emaLat;
      this.emaLon = this.opts.emaAlpha * pt.lon + (1 - this.opts.emaAlpha) * this.emaLon;
    }

    const smoothed: LatLon = { lat: this.emaLat, lon: this.emaLon, accuracy: pt.accuracy };
    this.smoothedBuffer.push(smoothed);
    this.lastCleanPoint = smoothed;
    this.coordinates = [...this.coordinates, [smoothed.lon, smoothed.lat]];

    return this.liveCleanPath();
  }

  /** Live path — EMA-smoothed buffer, no RDP (applied only on flush). */
  private liveCleanPath(): GeoCoord[] {
    return this.coordinates;
  }

  /**
   * Finalize the route: apply RDP simplification + turn smoothing to the
   * accumulated EMA-smoothed buffer. Call once at run end.
   */
  flush(): GeoCoord[] {
    if (this.smoothedBuffer.length < 2) {
      return this.smoothedBuffer.map((p) => [p.lon, p.lat]);
    }
    const simplified = rdpSimplify(this.smoothedBuffer, this.opts.rdpEpsilonM);
    const turns = detectTurns(simplified, this.opts.turnAngleDeg);
    const final = turnSmooth(simplified, turns, this.opts.turnSmoothRadiusM);
    return final.map((p) => [p.lon, p.lat]);
  }

  /** Reacquire after missing GPS without smoothing across the unobserved gap. */
  breakSegment(): void {
    this.emaLat = null;
    this.emaLon = null;
    this.lastCleanPoint = null;
  }

  /** Reset all accumulated state. Call before starting a new run. */
  reset(): void {
    this.emaLat = null;
    this.emaLon = null;
    this.smoothedBuffer = [];
    this.coordinates = [];
    this.lastCleanPoint = null;
    this._droppedCount = 0;
  }
}
