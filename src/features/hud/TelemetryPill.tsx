import { memo, useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useRecorder } from '@/features/recorder/useRecorder';
import { formatDuration } from '@/lib/geo';
import { formatPace, rollingPace } from './telemetry';
import { useHudPreferences } from './usePresentation';

export const TelemetryPill = memo(function TelemetryPill({ active }: { active: boolean }) {
  const startedAt = useRecorder(s => s.startedAt);
  const distance = useRecorder(s => s.liveDistanceM);
  const points = useRecorder(s => s.paceWindow);
  const fix = useRecorder(s => s.liveFix);
  const simulation = useRecorder(s => s.isSimulation);
  const units = useHudPreferences(s => s.units);
  const [now, setNow] = useState(Date.now());
  const insets = useSafeAreaInsets();
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  const unitM = units === 'mi' ? 1609.344 : 1000;
  const stale = !fix || now - fix.ts > 10_000;
  const pace = formatPace(rollingPace(points, now, unitM));
  const duration = formatDuration(startedAt ? Math.max(0, now - startedAt.getTime()) / 1000 : 0);
  return <View pointerEvents="none" style={[styles.wrap, { top: insets.top + 12 }]}>
    <View style={styles.pill} accessible accessibilityLabel={`Pace ${pace} per ${units}, time ${duration}, distance ${(distance / unitM).toFixed(2)} ${units}${stale ? ', waiting for GPS' : ''}`}>
      <View style={styles.metric}><Text style={[styles.value, styles.pace]}>{pace}</Text><Text style={styles.label}>PACE /{units.toUpperCase()}</Text></View>
      <View style={styles.divider} />
      <View style={styles.metric}><Text style={styles.value}>{duration}</Text><Text style={styles.label}>RUN TIME</Text></View>
      <View style={styles.divider} />
      <View style={styles.metric}><Text style={styles.value}>{(distance / unitM).toFixed(2)}</Text><Text style={styles.label}>DISTANCE {units.toUpperCase()}</Text></View>
    </View>
    <Text style={styles.status}>{simulation ? '● SIMULATION' : stale ? '○ WAITING FOR GPS' : '● LIVE RUN'}</Text>
  </View>;
});
const styles = StyleSheet.create({
  wrap: { position: 'absolute', left: 16, right: 16, alignItems: 'center' },
  pill: { width: '100%', maxWidth: 520, flexDirection: 'row', alignItems: 'center', backgroundColor: '#0A1929F5', borderWidth: 1, borderColor: '#64F5D655', borderRadius: 28, paddingVertical: 18, paddingHorizontal: 8, elevation: 6, shadowColor: '#000', shadowRadius: 12, shadowOpacity: 0.2 },
  metric: { flex: 1, alignItems: 'center' }, value: { color: '#F5FAFF', fontSize: 26, fontWeight: '700', fontVariant: ['tabular-nums'] },
  pace: { color: '#80FFDD' }, label: { color: '#B7CBD8', fontSize: 9, fontWeight: '700', letterSpacing: 1, marginTop: 5 }, divider: { width: 1, height: 30, backgroundColor: '#385063' },
  status: { color: '#DCFFF4', backgroundColor: '#0A1929EB', borderRadius: 10, overflow: 'hidden', fontSize: 10, fontWeight: '700', letterSpacing: 1.5, paddingHorizontal: 12, paddingVertical: 5, marginTop: 6 },
});
