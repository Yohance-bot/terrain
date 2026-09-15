import { create } from 'zustand';
import { setMeta } from '@/lib/db';
import type { UnitPreference } from '@/lib/preferences';

export type RouteDisplay = 'streets' | 'gps';
/** How the player is drawn on the map: the 3D character, or the plain marker
 *  that predates it. The marker stays a first-class choice — it is quieter,
 *  cheaper, and some people just want a dot. */
export type PlayerMarker = 'avatar' | 'classic';

/**
 * The character is opt-in, because on iOS it currently takes the app down.
 *
 * Filament is killed on its first rendered frame — see `docs/18_AVATAR_CRASH.md`
 * — and since the avatar is mounted by the map on the opening screen, that reads
 * as "the app crashes when I open it". The marker is drawn from the same fix and
 * costs nothing but the character, so it is what an unset preference resolves to
 * until the first frame is survivable. Flip this back to `avatar` then.
 */
export const DEFAULT_PLAYER_MARKER: PlayerMarker = 'classic';

export const useHudPreferences = create<{
  routeDisplay: RouteDisplay; setRouteDisplay: (value: RouteDisplay) => void;
  playerMarker: PlayerMarker; setPlayerMarker: (value: PlayerMarker) => void;
  economy: boolean; haptics: boolean; weather: boolean; units: UnitPreference;
  setEconomy: (value: boolean) => void; setWeather: (value: boolean) => void;
}>((set) => ({
  routeDisplay: 'streets',
  setRouteDisplay: routeDisplay => { set({ routeDisplay }); void setMeta('hud.route-display.v1', routeDisplay).catch(() => undefined); },
  playerMarker: DEFAULT_PLAYER_MARKER,
  setPlayerMarker: playerMarker => { set({ playerMarker }); void setMeta('hud.player-marker.v1', playerMarker).catch(() => undefined); },
  economy: false, haptics: true, weather: true, units: 'km',
  setEconomy: economy => { set({ economy }); void setMeta('hud.economy.v1', String(economy)).catch(() => undefined); },
  setWeather: weather => { set({ weather }); void setMeta('hud.weather.v1', String(weather)).catch(() => undefined); },
}));

