import * as Haptics from 'expo-haptics';
import { memo, useEffect, useRef, useState } from 'react';
import { Animated, Easing, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useRunCues } from './useRunCues';
import { useHudPreferences } from './usePresentation';

/** Event-only native-driver animations: no per-frame React or GeoJSON updates. */
export const CueOverlay = memo(function CueOverlay({ active, reducedMotion, economy }: { active: boolean; reducedMotion: boolean; economy: boolean }) {
  const cue = useRunCues(s => s.cue);
  const haptics = useHudPreferences(s => s.haptics);
  const progress = useRef(new Animated.Value(0)).current;
  const [visible, setVisible] = useState(false);
  const played = useRef<string | null>(null);
  const insets = useSafeAreaInsets();
  useEffect(() => {
    if (!active || !cue || Date.now() - cue.createdAt > 3500) { setVisible(false); return; }
    if (played.current === cue.id) return;
    played.current = cue.id;
    setVisible(true); progress.setValue(0);
    if (haptics) {
      void (cue.kind === 'checkpoint'
        ? Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
        : Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)).catch(() => undefined);
    }
    const duration = cue.kind === 'checkpoint' ? 1800 : 3200;
    const animation = Animated.timing(progress, { toValue: 1, duration, easing: Easing.out(Easing.cubic), useNativeDriver: true });
    animation.start(({ finished }) => { if (finished) setVisible(false); });
    return () => { animation.stop(); setVisible(false); };
  }, [cue, active, reducedMotion, haptics, progress]);
  if (!visible || !cue) return null;
  const claim = cue.kind !== 'checkpoint';
  const color = claim ? '#FFE09B' : '#80FFDD';
  const opacity = progress.interpolate({ inputRange: [0, 0.08, 0.78, 1], outputRange: [0, 1, 1, 0] });
  return <View pointerEvents="none" style={StyleSheet.absoluteFill}>
    <Animated.View style={[styles.banner, { top: insets.top + 142, opacity, borderColor: color }]} accessible accessibilityLiveRegion="polite">
      <Text style={[styles.title, { color }]}>{cue.title}</Text><Text style={styles.detail}>{cue.detail}</Text>
    </Animated.View>
    {!reducedMotion && <View style={styles.origin}>
      <Animated.View style={[styles.ring, { borderColor: color, opacity: progress.interpolate({ inputRange: [0, 0.8, 1], outputRange: [0.8, 0, 0] }), transform: [{ scale: progress.interpolate({ inputRange: [0, 1], outputRange: [0.2, claim ? 5 : 2.2] }) }] }]} />
      {claim && !economy && Array.from({ length: 12 }, (_, i) => {
        const angle = i * Math.PI / 6;
        return <Animated.View key={i} style={[styles.spark, { backgroundColor: i % 2 ? '#FFFFFF' : color, opacity, transform: [
          { translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [0, Math.cos(angle) * 155] }) },
          { translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [0, Math.sin(angle) * 155] }) },
          { scale: progress.interpolate({ inputRange: [0, 0.2, 1], outputRange: [0.4, 1.4, 0] }) },
        ] }]} />;
      })}
    </View>}
  </View>;
});
const styles = StyleSheet.create({
  banner: { position: 'absolute', alignSelf: 'center', maxWidth: '90%', backgroundColor: '#0A1929F2', borderWidth: 1, borderRadius: 20, paddingHorizontal: 24, paddingVertical: 14, alignItems: 'center' },
  title: { fontSize: 20, fontWeight: '800', letterSpacing: 1 }, detail: { color: '#DAE6EF', fontSize: 12, marginTop: 4, textAlign: 'center' },
  origin: { position: 'absolute', top: '52%', left: '50%' }, ring: { position: 'absolute', left: -45, top: -45, width: 90, height: 90, borderRadius: 45, borderWidth: 2 },
  spark: { position: 'absolute', width: 5, height: 9, borderRadius: 3 },
});
