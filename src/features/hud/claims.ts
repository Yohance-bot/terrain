import type { RunResult } from '@/services/api/types';
import type { HudCue } from './events';

/** Only an applied server result can use the claimed language. */
export function confirmedClaimCue(result: RunResult, coordinate: [number, number], now = Date.now()): HudCue | null {
  if (result.status !== 'applied') return null;
  const ids = [...new Set(result.segments.filter(s => s.is_owned_by_you && (s.ownership_changed || s.capture_method === 'loop')).map(s => s.territory_id))];
  if (!ids.length && !result.captured_area_id) return null;
  return { id: `${result.run_id}:claim`, kind: 'claim', title: 'TERRITORY CLAIMED', detail: result.captured_area_id ? `${Math.round(result.captured_area_m2 ?? 0).toLocaleString()} m² claimed` : `${ids.length} ${ids.length === 1 ? 'territory' : 'territories'} secured`, coordinate, territoryIds: ids, createdAt: now };
}
