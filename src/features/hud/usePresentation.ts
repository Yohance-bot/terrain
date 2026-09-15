import { useIsFocused } from '@react-navigation/native';
import { useEffect, useState } from 'react';
import { AccessibilityInfo, AppState } from 'react-native';
import { getMeta } from '@/lib/db';
import { getNotificationsEnabled, getUnits } from '@/lib/preferences';

import { useHudPreferences } from './preferences';

export { useHudPreferences, type RouteDisplay, type PlayerMarker } from './preferences';

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
