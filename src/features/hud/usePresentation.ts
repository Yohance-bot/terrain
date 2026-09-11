import { useIsFocused } from '@react-navigation/native';
import { useEffect, useState } from 'react';
import { AccessibilityInfo, AppState } from 'react-native';
import { create } from 'zustand';
import { getMeta, setMeta } from '@/lib/db';
import { getNotificationsEnabled, getUnits, type UnitPreference } from '@/lib/preferences';

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

export function usePresentation() {
  const focused = useIsFocused();
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const [reducedMotion, setReducedMotion] = useState(true);
  const economy = useHudPreferences(s => s.economy);
  useEffect(() => {
    const app = AppState.addEventListener('change', state => setForeground(state === 'active'));
    let mounted = true;
    void AccessibilityInfo.isReduceMotionEnabled().then(v => { if (mounted) setReducedMotion(v); }).catch(() => undefined);
    const motion = AccessibilityInfo.addEventListener('reduceMotionChanged', setReducedMotion);
    return () => { mounted = false; app.remove(); motion.remove(); };
  }, []);
  useEffect(() => {
    if (!focused) return;
    let mounted = true;
    void Promise.all([getMeta('hud.economy.v1'), getNotificationsEnabled(), getUnits(), getMeta('hud.weather.v1'), getMeta('hud.route-display.v1'), getMeta('hud.player-marker.v1')])
      .then(([e, haptics, units, w, routeDisplay, playerMarker]) => { if (mounted) useHudPreferences.setState({ economy: e === 'true', haptics, units, weather: w !== 'false', routeDisplay: routeDisplay === 'gps' ? 'gps' : 'streets', playerMarker: playerMarker === 'classic' ? 'classic' : 'avatar' }); })
      .catch(() => undefined);
    return () => { mounted = false; };
  }, [focused]);
  return { active: focused && foreground, reducedMotion, economy };
}
