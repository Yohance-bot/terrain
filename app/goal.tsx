import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Alert, ScrollView, Pressable, StyleSheet, Text, View } from 'react-native';

import { GoalIcon, MinusIcon, PlusIcon } from '@/components/icons';
import { Button, ErrorState, IconTile, Loading, Segmented } from '@/components/ui';
import { useHudPreferences } from '@/features/hud/usePresentation';
import { distanceNumber, formatHours, metresPerUnit, unitLabel, type Units } from '@/lib/format';
import { clearWeeklyGoal, fetchAthleteStats, fetchWeeklyGoal, saveWeeklyGoal } from '@/services/api/client';
import type { AthleteStats, GoalMetric } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';

/** The goal is stored in metres, seconds or runs; it is edited in the athlete's units. */
function steps(metric: GoalMetric, units: Units) {
  if (metric === 'distance') return { step: 1, min: 1, picks: units === 'mi' ? [5, 10, 15, 25] : [10, 20, 30, 40], unit: unitLabel(units) };
  if (metric === 'time') return { step: 0.5, min: 0.5, picks: [2, 3, 4, 5], unit: 'h' };
  return { step: 1, min: 1, picks: [2, 3, 4, 5], unit: 'runs' };
}

function toStored(metric: GoalMetric, value: number, units: Units) {
  return metric === 'distance' ? value * metresPerUnit(units) : metric === 'time' ? value * 3600 : value;
}

function fromStored(metric: GoalMetric, stored: number, units: Units) {
  return metric === 'distance' ? Math.round(stored / metresPerUnit(units)) : metric === 'time' ? Math.round((stored / 3600) * 2) / 2 : Math.round(stored);
}

export default function GoalSheet() {
  const units = useHudPreferences((s) => s.units);
  const [metric, setMetric] = useState<GoalMetric>('distance');
  const [value, setValue] = useState(20);
  const [hasGoal, setHasGoal] = useState(false);
  const [average, setAverage] = useState<AthleteStats['last_four_weeks'] | null>(null);
  const [saving, setSaving] = useState(false);

  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const load = useCallback(() => {
    setLoading(true);
    setFailed(false);
    void fetchWeeklyGoal()
      .then((goal) => {
        if (!goal) return;
        setHasGoal(true);
        setMetric(goal.metric);
        setValue(fromStored(goal.metric, goal.target, units));
      })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
    void fetchAthleteStats(4)
      .then((stats) => setAverage(stats.last_four_weeks))
      .catch(() => undefined);
  }, [units]);
  useEffect(load, [load]);

  const config = steps(metric, units);
  const change = (next: GoalMetric) => {
    setMetric(next);
    setValue(steps(next, units).picks[1]!);
  };

  const averageText = !average
    ? null
    : metric === 'distance'
      ? `${distanceNumber(average.distance_m_per_week, units)} ${unitLabel(units)}`
      : metric === 'time'
        ? formatHours(average.moving_s_per_week)
        : `${average.runs_per_week.toFixed(1)} runs`;

  const save = async () => {
    setSaving(true);
    try {
      await saveWeeklyGoal(metric, toStored(metric, value, units));
      router.back();
    } catch {
      Alert.alert('Could not save your goal', 'Check your connection and try again.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    try {
      await clearWeeklyGoal();
      router.back();
    } catch {
      Alert.alert('Could not remove your goal');
    }
  };

  if (loading || failed) return <View style={styles.sheet}>{loading ? <Loading /> : <ErrorState onRetry={load} />}<Button variant="text" label="Close" onPress={() => router.back()} /></View>;

  return (
    <ScrollView contentContainerStyle={styles.sheet}>
      <View style={styles.head}>
        <IconTile><GoalIcon size={22} /></IconTile>
        <View>
          <Text style={styles.title}>Weekly goal</Text>
          <Text style={typeScale.meta}>Resets every Monday</Text>
        </View>
      </View>

      <Segmented
        value={metric}
        onChange={change}
        options={[
          { value: 'distance', label: 'Distance' },
          { value: 'time', label: 'Time' },
          { value: 'runs', label: 'Runs' },
        ]}
      />

      <View style={styles.stepper}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Less"
          style={styles.step}
          onPress={() => setValue((current) => Math.max(config.min, Number((current - config.step).toFixed(1))))}
        >
          <MinusIcon size={22} color={ui.ink} />
        </Pressable>
        <View style={styles.valueLine}>
          <Text style={styles.value}>{value}</Text>
          <Text style={styles.unit}>{config.unit}</Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="More"
          style={styles.step}
          onPress={() => setValue((current) => Number((current + config.step).toFixed(1)))}
        >
          <PlusIcon size={22} color={ui.ink} />
        </Pressable>
      </View>
      {averageText ? <Text style={[typeScale.meta, styles.center]}>Your last 4 weeks averaged {averageText}</Text> : null}

      <View style={styles.picks}>
        {config.picks.map((pick) => (
          <Pressable
            key={pick}
            accessibilityRole="button"
            onPress={() => setValue(pick)}
            style={[styles.pick, pick === value && styles.pickSelected]}
          >
            <Text style={[styles.pickText, pick === value && styles.pickTextSelected]}>{pick}</Text>
          </Pressable>
        ))}
      </View>

      <Button label="Save goal" onPress={() => void save()} busy={saving} />
      {hasGoal ? <Button variant="text" label="Remove goal" disabled={saving} onPress={() => void remove()} /> : null}
      <Button variant="text" label="Cancel" onPress={() => router.back()} disabled={saving} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  sheet: { flexGrow: 1, paddingBottom: 32, backgroundColor: ui.surface, paddingHorizontal: 20, paddingTop: 28, gap: 20 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  title: { fontFamily: fonts.bold, fontSize: 22, color: ui.ink },
  stepper: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingTop: 8 },
  step: { width: 56, height: 56, borderRadius: 28, borderWidth: 1.5, borderColor: ui.line, alignItems: 'center', justifyContent: 'center' },
  valueLine: { flexDirection: 'row', alignItems: 'baseline', gap: 6 },
  value: { fontFamily: fonts.semibold, fontSize: 64, letterSpacing: -1.5, color: ui.ink },
  unit: { fontFamily: fonts.medium, fontSize: 22, color: ui.ink2 },
  center: { textAlign: 'center', marginTop: -8 },
  picks: { flexDirection: 'row', gap: 8 },
  pick: { flex: 1, height: 40, borderRadius: 20, borderWidth: 1, borderColor: ui.line, alignItems: 'center', justifyContent: 'center' },
  pickSelected: { borderColor: ui.accent, borderWidth: 1.5, backgroundColor: ui.accentSoft },
  pickText: { fontFamily: fonts.medium, fontSize: 15, color: ui.ink },
  pickTextSelected: { fontFamily: fonts.semibold, color: ui.accentPressed },
});
