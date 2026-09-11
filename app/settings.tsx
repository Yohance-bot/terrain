import Constants from 'expo-constants';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { getNotificationsEnabled, getUnits, setNotificationsEnabled, setUnits, type UnitPreference } from '@/lib/preferences';
import { useHudPreferences } from '@/features/hud/usePresentation';
import { colors, fontSize, fontWeight, radius, spacing } from '@/theme';

export default function SettingsScreen() {
  const [units, setUnitsState] = useState<UnitPreference>('km');
  const [notifications, setNotifications] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const economy = useHudPreferences(s => s.economy);
  const routeDisplay = useHudPreferences(s => s.routeDisplay);
  const playerMarker = useHudPreferences(s => s.playerMarker);
  const weather = useHudPreferences(s => s.weather);
  useFocusEffect(useCallback(() => {
    void Promise.all([getUnits(), getNotificationsEnabled()]).then(([u, n]) => { setUnitsState(u); setNotifications(n); }).catch(() => setNotice('Could not load preferences.'));
  }, []));
  const choose = (u: UnitPreference) => { setUnitsState(u); void setUnits(u); useHudPreferences.setState({ units: u }); };
  return <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
    <View style={styles.header}><Pressable onPress={() => router.back()}><Text style={styles.back}>‹ Profile</Text></Pressable><Text style={styles.title}>Settings</Text><View /></View>
    <ScrollView>
      <Text style={styles.label}>UNITS</Text>
      <View style={styles.segment}>{(['km', 'mi'] as const).map(u => <Pressable key={u} style={[styles.option, units === u && styles.selected]} onPress={() => choose(u)}><Text style={[styles.optionText, units === u && styles.selectedText]}>{u === 'km' ? 'Kilometres' : 'Miles'}</Text></Pressable>)}</View>
      <Text style={[styles.label, { marginTop: spacing.xl }]}>RUN TRAIL</Text>
      <View style={styles.segment}>{(['streets', 'gps'] as const).map(mode => <Pressable key={mode} accessibilityRole="radio" accessibilityState={{ checked: routeDisplay === mode }} style={[styles.option, routeDisplay === mode && styles.selected]} onPress={() => useHudPreferences.getState().setRouteDisplay(mode)}><Text style={[styles.optionText, routeDisplay === mode && styles.selectedText]}>{mode === 'streets' ? 'Light up streets' : 'GPS trail'}</Text></Pressable>)}</View>
      <Text style={styles.subtext}>{routeDisplay === 'streets' ? 'Color the part of each street you run along. Off-road or uncertain sections appear as a dotted GPS trail.' : 'Show your recorded path, including parks, shortcuts and off-road sections.'}</Text>
      <Text style={[styles.label, { marginTop: spacing.xl }]}>YOU ON THE MAP</Text>
      <View style={styles.segment}>{(['avatar', 'classic'] as const).map(mode => <Pressable key={mode} accessibilityRole="radio" accessibilityState={{ checked: playerMarker === mode }} style={[styles.option, playerMarker === mode && styles.selected]} onPress={() => useHudPreferences.getState().setPlayerMarker(mode)}><Text style={[styles.optionText, playerMarker === mode && styles.selectedText]}>{mode === 'avatar' ? '3D runner' : 'Classic marker'}</Text></Pressable>)}</View>
      <Text style={styles.subtext}>{playerMarker === 'avatar' ? 'A small 3D character standing on the map, with a hologram at its feet.' : 'The plain dot. Lighter on the battery, and never in front of anything.'}</Text>
      <View style={styles.row}><View style={styles.copy}><Text style={styles.rowText}>Run cues & haptics</Text><Text style={styles.subtext}>Split and territory feedback</Text></View><Switch value={notifications} onValueChange={v => { setNotifications(v); void setNotificationsEnabled(v); useHudPreferences.setState({ haptics: v }); }} /></View>
      <View style={styles.row}><View style={styles.copy}><Text style={styles.rowText}>Battery saver</Text><Text style={styles.subtext}>Less glow, slower map updates, calm camera</Text></View><Switch value={economy} onValueChange={useHudPreferences.getState().setEconomy} /></View>
      <View style={styles.row}><View style={styles.copy}><Text style={styles.rowText}>Weather lighting</Text><Text style={styles.subtext}>Uses approximate location with Open-Meteo every 15 minutes. Time-based lighting works offline.</Text></View><Switch value={weather} onValueChange={useHudPreferences.getState().setWeather} /></View>
      {notice && <Text style={styles.subtext}>{notice}</Text>}
    </ScrollView>
    <Text style={styles.footer}>TerraRun {Constants.expoConfig?.version ?? '1.0.0'}{'\n'}© OpenStreetMap contributors · Weather: Open-Meteo</Text>
  </SafeAreaView>;
}
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background, padding: spacing.lg }, header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xl }, back: { color: colors.primary, fontWeight: fontWeight.semibold }, title: { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: colors.text },
  label: { fontSize: 11, fontWeight: fontWeight.bold, color: colors.textMuted, letterSpacing: 1, marginBottom: spacing.sm }, segment: { flexDirection: 'row', borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, overflow: 'hidden' }, option: { flex: 1, padding: spacing.md, alignItems: 'center' }, selected: { backgroundColor: colors.primary }, optionText: { color: colors.text }, selectedText: { color: colors.surface, fontWeight: fontWeight.bold },
  row: { marginTop: spacing.lg, paddingVertical: spacing.md, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', borderBottomWidth: 1, borderColor: colors.border }, copy: { flex: 1, paddingRight: 16 }, rowText: { fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: colors.text }, subtext: { fontSize: fontSize.xs, color: colors.textMuted, marginTop: 5, lineHeight: 18 },
  footer: { textAlign: 'center', color: colors.textMuted, fontSize: 10, lineHeight: 18, paddingTop: 16 },
});
