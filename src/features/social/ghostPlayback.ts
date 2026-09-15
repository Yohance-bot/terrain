/**
 * Replaying a recorded ghost against a live run.
 *
 * The whole ghost — every position and its offset from the start — is fetched
 * once and replayed on the device. Nothing here talks to the network: a runner
 * comparing themselves to a ghost should not be at the mercy of signal, and the
 * comparison must keep working when the phone is in a pocket.
 */

/** [lon, lat, milliseconds from the start of the recorded run]. */
export type GhostPoint = [number, number, number];

export type GhostState = {
  /** Where the ghost is right now, interpolated between recorded fixes. */
  coordinate: [number, number];
  /** 0–1 along the recorded route by time. */
  progress: number;
  /** Metres the ghost has covered so far. */
  distanceM: number;
  finished: boolean;
  heading?: number;
};

function bearing(from: GhostPoint, to: GhostPoint): number {
  const dy = to[1] - from[1], dx = (to[0] - from[0]) * Math.cos(from[1] * Math.PI / 180);
  return (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
}

const EARTH_RADIUS_M = 6_371_000;

export function metresBetween(a: [number, number], b: [number, number]): number {
  const [lon1, lat1] = a;
  const [lon2, lat2] = b;
  const phi1 = (lat1 * Math.PI) / 180;
  const phi2 = (lat2 * Math.PI) / 180;
  const dPhi = ((lat2 - lat1) * Math.PI) / 180;
  const dLambda = ((lon2 - lon1) * Math.PI) / 180;
  const h =
    Math.sin(dPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLambda / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

/** Cumulative distance at each recorded point, computed once per ghost. */
export function cumulativeDistances(path: GhostPoint[]): number[] {
  const totals = [0];
  for (let index = 1; index < path.length; index += 1) {
    const previous = path[index - 1]!;
    const current = path[index]!;
    totals.push(
      totals[index - 1]! + metresBetween([previous[0], previous[1]], [current[0], current[1]])
    );
  }
  return totals;
}

/**
 * Where the ghost is after `elapsedMs` of the attempt.
 *
 * Recorded fixes are seconds apart, so the position is interpolated between
 * them; a marker that jumped once a second would read as a stutter rather than
 * as a runner.
 */
export function ghostAt(
  path: GhostPoint[],
  elapsedMs: number,
  totals?: number[]
): GhostState | null {
  if (path.length === 0) return null;
  const distances = totals ?? cumulativeDistances(path);
  const last = path[path.length - 1]!;
  const duration = last[2];

  if (elapsedMs <= 0 || path.length === 1) {
    const first = path[0]!;
    return { coordinate: [first[0], first[1]], progress: 0, distanceM: 0, finished: false, heading: bearing(first, path[1] ?? first) };
  }
  if (elapsedMs >= duration) {
    return {
      coordinate: [last[0], last[1]],
      progress: 1,
      distanceM: distances[distances.length - 1]!,
      finished: true,
      heading: bearing(path[Math.max(0, path.length - 2)]!, last),
    };
  }

  // Recorded fixes are ordered by time, so a binary search stays cheap even on
  // a long route replayed every animation frame.
  let low = 0;
  let high = path.length - 1;
  while (high - low > 1) {
    const middle = (low + high) >> 1;
    if (path[middle]![2] <= elapsedMs) low = middle;
    else high = middle;
  }

  const from = path[low]!;
  const to = path[high]!;
  const span = to[2] - from[2];
  const ratio = span > 0 ? (elapsedMs - from[2]) / span : 0;
  return {
    coordinate: [from[0] + (to[0] - from[0]) * ratio, from[1] + (to[1] - from[1]) * ratio],
    progress: elapsedMs / duration,
    distanceM: distances[low]! + (distances[high]! - distances[low]!) * ratio,
    finished: false,
    heading: bearing(from, to),
  };
}

/**
 * How far ahead of the ghost the runner is, in metres of route covered.
 * Positive means the runner is winning.
 */
export function leadMetres(runnerDistanceM: number, ghost: GhostState | null): number {
  if (!ghost) return 0;
  return runnerDistanceM - ghost.distanceM;
}

/** A ghost is beaten by finishing the same distance in less time. */
export function beatsGhost(elapsedS: number, ghostDurationS: number): boolean {
  return elapsedS < ghostDurationS;
}

export function formatLead(metres: number): string {
  const rounded = Math.round(metres);
  if (Math.abs(rounded) < 5) return 'Level';
  const magnitude = Math.abs(rounded) >= 1000
    ? `${(Math.abs(rounded) / 1000).toFixed(2)} km`
    : `${Math.abs(rounded)} m`;
  return rounded > 0 ? `${magnitude} ahead` : `${magnitude} behind`;
}
