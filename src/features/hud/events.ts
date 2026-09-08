import type { RunFix } from './telemetry';
export type Waypoint = { id: string; name: string; coordinate: [number, number]; radiusM: number };
export type HudCue = {
  id: string; kind: 'checkpoint' | 'closure' | 'claim'; title: string; detail: string;
  coordinate: [number, number]; createdAt: number;
  polygon?: GeoJSON.Feature<GeoJSON.Polygon>;
  territoryIds?: string[];
};

/** Per-run checkpoint ledger. Baseline on resume so old splits never replay. */
export class CheckpointLedger {
  private runId: string | null = null;
  private split = 0;
  private unitM = 1000;
  private visited = new Set<string>();
  update(runId: string, distanceM: number, fix: RunFix, active: boolean, unitM: number, waypoints: Waypoint[] = []): HudCue | null {
    const next = Math.floor(distanceM / unitM);
    if (runId !== this.runId) { this.runId = runId; this.split = next; this.visited.clear(); }
    if (unitM !== this.unitM) { this.unitM = unitM; this.split = next; }
    const crossed = next > this.split;
    this.split = Math.max(this.split, next);
    let reached: Waypoint | undefined;
    for (const waypoint of waypoints) {
      const dx = (fix.coordinate[0] - waypoint.coordinate[0]) * 111_320 * Math.cos(fix.coordinate[1] * Math.PI / 180);
      const dy = (fix.coordinate[1] - waypoint.coordinate[1]) * 111_320;
      if (Math.hypot(dx, dy) <= waypoint.radiusM && !this.visited.has(waypoint.id)) {
        this.visited.add(waypoint.id); reached ??= waypoint;
      }
    }
    if (!active || (!crossed && !reached)) return null;
    return { id: `${runId}:checkpoint:${reached?.id ?? next}`, kind: 'checkpoint', title: reached?.name ?? `${next} ${unitM === 1000 ? 'KM' : 'MI'} SPLIT`, detail: reached ? 'Checkpoint reached' : 'Keep your rhythm', coordinate: fix.coordinate, createdAt: Date.now() };
  }
}
