import { create } from 'zustand';
import { setMeta } from '@/lib/db';
import type { UnitPreference } from '@/lib/preferences';

export type RouteDisplay = 'streets' | 'gps';
/** How the player is drawn on the map: the 3D character, or the plain marker
 *  that predates it. The marker stays a first-class choice — it is quieter,
 *  cheaper, and some people just want a dot. */
export type PlayerMarker = 'avatar' | 'classic';

export const useHudPreferences = create<{
  routeDisplay: RouteDisplay; setRouteDisplay: (value: RouteDisplay) => void;
  playerMarker: PlayerMarker; setPlayerMarker: (value: PlayerMarker) => void;
  economy: boolean; haptics: boolean; weather: boolean; units: UnitPreference;
  setEconomy: (value: boolean) => void; setWeather: (value: boolean) => void;
}>((set) => ({
  routeDisplay: 'streets',
  setRouteDisplay: routeDisplay => { set({ routeDisplay }); void setMeta('hud.route-display.v1', routeDisplay).catch(() => undefined); },
  playerMarker: 'avatar',
  setPlayerMarker: playerMarker => { set({ playerMarker }); void setMeta('hud.player-marker.v1', playerMarker).catch(() => undefined); },
  economy: false, haptics: true, weather: true, units: 'km',
  setEconomy: economy => { set({ economy }); void setMeta('hud.economy.v1', String(economy)).catch(() => undefined); },
  setWeather: weather => { set({ weather }); void setMeta('hud.weather.v1', String(weather)).catch(() => undefined); },
}));

