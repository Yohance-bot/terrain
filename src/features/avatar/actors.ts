import type { FriendPosition } from '@/services/api/types';
import type { GhostState } from '@/features/social/ghostPlayback';
import { metresBetween } from '@/features/social/ghostPlayback';

export const MAX_MAP_ACTORS = 8;
export const FRIEND_POSITION_TTL_MS = 90_000;
export type MapActor = { id: string; coordinate: [number, number]; heading: number; running: boolean; expiresAt: number };
export function freshFriends(friends: FriendPosition[], now: number) {
  return friends.filter(f => Number.isFinite(f.lon) && Number.isFinite(f.lat) && Math.abs(f.lat) <= 85.051129 && Math.abs(f.lon) <= 180 && now - Date.parse(f.updated_at) < FRIEND_POSITION_TTL_MS && Date.parse(f.updated_at) <= now + 30_000);
}
/** Active ghost gets priority; distant friends retain labelled map markers. */
export function mapActors(origin: [number, number], running: boolean, friends: FriendPosition[], ghost: GhostState | null, now: number): MapActor[] {
  const actors: MapActor[] = [{ id: 'self', coordinate: origin, heading: 0, running, expiresAt: Number.MAX_SAFE_INTEGER }];
  if (ghost && metresBetween(origin, ghost.coordinate) < 1500) actors.push({ id: 'ghost', coordinate: ghost.coordinate, heading: ghost.heading ?? 0, running: !ghost.finished, expiresAt: Number.MAX_SAFE_INTEGER });
  const nearby = freshFriends(friends, now).map(f => ({ f, distance: metresBetween(origin, [f.lon, f.lat]) })).filter(f => f.distance < 1500).sort((a, b) => a.distance - b.distance || a.f.account.id.localeCompare(b.f.account.id));
  for (const { f } of nearby.slice(0, MAX_MAP_ACTORS - actors.length)) actors.push({ id: f.account.id, coordinate: [f.lon, f.lat], heading: f.heading != null && f.heading >= 0 ? f.heading : 0, running: f.is_running, expiresAt: Date.parse(f.updated_at) + FRIEND_POSITION_TTL_MS });
  return actors;
}
