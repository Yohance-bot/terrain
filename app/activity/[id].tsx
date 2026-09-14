import { router, useLocalSearchParams } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useState } from 'react';
import { Alert, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { LineChart } from '@/components/charts';
import { RecordIcon } from '@/components/icons';
import { Card, ErrorState, Loading, NavHeader, Row, Screen, SectionLabel, StatRow } from '@/components/ui';
import { useHudPreferences } from '@/features/hud/usePresentation';
import {
  EFFORT_LABELS,
  distanceNumber,
  formatClock,
  formatElevation,
  formatPace,
  formatPaceValue,
  metresPerUnit,
  paceSeconds,
  runTitle,
  unitLabel,
  weatherLabel,
} from '@/lib/format';
import { annotateRun, fetchActivity, fetchShoes } from '@/services/api/client';
import type { RunActivity } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';

const ORDINAL = ['', 'Fastest', '2nd fastest', '3rd fastest'];

export default function ActivityScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const units = useHudPreferences((s) => s.units);
  const [activity, setActivity] = useState<RunActivity | null>(null);
  const [failed, setFailed] = useState(false);
  const [title, setTitle] = useState('');
  const [note, setNote] = useState('');

  const load = useCallback(async () => {
    try {
      const next = await fetchActivity(id);
      setActivity(next);
      setFailed(false);
      setTitle(next.summary.title ?? '');
      setNote(next.summary.note ?? '');
    } catch {
      setFailed(true);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (change: { title?: string | null; note?: string | null; shoe_id?: string | null }) => {
    try {
      const summary = await annotateRun(id, change);
      setActivity((current) => (current ? { ...current, summary } : current));
    } catch {
      Alert.alert('Could not save', 'Check your connection and try again.');
    }
  };

  const chooseShoes = async () => {
    try {
      const shoes = (await fetchShoes()).filter((shoe) => !shoe.retired);
      if (shoes.length === 0) {
        Alert.alert('No shoes yet', 'Add a pair and every run can keep count of their distance.', [
          { text: 'Not now', style: 'cancel' },
          { text: 'Add shoes', onPress: () => router.push('/shoes') },
        ]);
        return;
      }
      Alert.alert('Shoes for this run', undefined, [
        ...shoes.map((shoe) => ({ text: shoe.name, onPress: () => void save({ shoe_id: shoe.id }) })),
        { text: 'None', onPress: () => void save({ shoe_id: null }) },
        { text: 'Cancel', style: 'cancel' as const },
      ]);
    } catch {
      Alert.alert('Could not load your shoes');
    }
  };

  if (failed) {
    return (
      <Screen>
        <NavHeader onBack={() => router.back()} />
        <ErrorState message="This run may still be syncing. Check your connection and retry." onRetry={() => void load()} />
      </Screen>
    );
  }
  if (!activity) {
    return (
      <Screen>
        <NavHeader onBack={() => router.back()} />
        <Loading />
      </Screen>
    );
  }

  const run = activity.summary;
  const started = new Date(run.started_at);
  const perUnit = metresPerUnit(units);
  const unit = unitLabel(units);
  const weather = weatherLabel(run.weather_code);
  const conditions = [run.temperature_c !== null ? `${Math.round(run.temperature_c)}°` : null, weather].filter(Boolean).join(' ');
  const fastestSplit = activity.splits
    .filter((split) => split.distance_m >= 1000)
    .reduce<number | null>((best, split) => (best === null || split.moving_s < best ? split.moving_s : best), null);
  const slowestSplit = Math.max(...activity.splits.map((split) => split.moving_s / (split.distance_m / 1000)), 1);

  return (
    <Screen>
      <StatusBar style="dark" />
      <NavHeader title={run.title ?? runTitle(started)} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={styles.head}>
          <Text style={typeScale.meta}>
            {started.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })} at{' '}
            {started.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}
            {conditions ? ` · ${conditions}` : ''}
          </Text>
          <TextInput
            value={title}
            onChangeText={setTitle}
            onEndEditing={() => {
              if ((run.title ?? '') !== title.trim()) void save({ title: title.trim() || null });
            }}
            placeholder={runTitle(started)}
            placeholderTextColor={ui.ink}
            maxLength={80}
            returnKeyType="done"
            style={styles.title}
            accessibilityLabel="Run title"
          />
          <View style={styles.hero}>
            <Text style={styles.heroValue}>{distanceNumber(run.distance_m, units)}</Text>
            <Text style={styles.heroUnit}>{unit}</Text>
          </View>
        </View>

        <Card style={styles.pad}>
          <StatRow
            items={[
              { value: formatPaceValue(paceSeconds(run.distance_m, run.moving_s, units)), label: `/${unit}` },
              { value: formatClock(run.moving_s), label: 'moving' },
              { value: formatElevation(run.elevation_gain_m, units), label: 'climbed' },
              { value: activity.calories === null ? '–' : String(activity.calories), label: 'kcal' },
            ]}
          />
        </Card>

        <Card style={styles.spaced}>
          <Row title="Elapsed time" value={formatClock(run.elapsed_s)} />
          <Row title="Descent" value={formatElevation(activity.elevation_loss_m, units)} />
          <Row title="Territories captured" value={String(run.captures)} />
          <Row title="Shoes" value={run.shoe?.name ?? 'None'} onPress={() => void chooseShoes()} />
          {activity.calories === null ? (
            <Row title="Calories" subtitle="Add your weight in Settings to estimate them" onPress={() => router.push('/settings')} />
          ) : null}
          <Row title="Route and territory" onPress={() => router.push(`/run/${run.run_id}`)} last />
        </Card>

        <SectionLabel>Notes</SectionLabel>
        <Card style={styles.pad}>
          <TextInput
            value={note}
            onChangeText={setNote}
            onEndEditing={() => {
              if ((run.note ?? '') !== note.trim()) void save({ note: note.trim() || null });
            }}
            placeholder="How did it feel?"
            placeholderTextColor={ui.ink3}
            multiline
            maxLength={1000}
            style={styles.note}
            accessibilityLabel="Notes"
          />
        </Card>

        {activity.splits.length > 0 && (
          <>
            <SectionLabel right={<Text style={typeScale.small}>per km</Text>}>Splits</SectionLabel>
            <Card style={styles.pad}>
              <View style={styles.splitHead}>
                <Text style={[typeScale.small, styles.splitIndex]}>KM</Text>
                <Text style={[typeScale.small, styles.splitBarCell]}>PACE</Text>
                <Text style={[typeScale.small, styles.splitElev]}>ELEV</Text>
              </View>
              {activity.splits.map((split) => {
                const pace = split.moving_s / (split.distance_m / 1000);
                const fastest = split.distance_m >= 1000 && split.moving_s === fastestSplit;
                return (
                  <View key={split.index} style={styles.split}>
                    <Text style={[styles.splitText, styles.splitIndex]}>
                      {split.distance_m >= 1000 ? split.index : (split.distance_m / 1000).toFixed(2)}
                    </Text>
                    <View style={styles.splitBarCell}>
                      <View style={[styles.splitBar, { width: `${Math.max(12, (1 - (pace - slowestSplit * 0.55) / (slowestSplit * 0.45)) * 100)}%` }, fastest && styles.splitBarFastest]} />
                      <Text style={[styles.splitText, fastest && { color: ui.accent }]}>{formatPaceValue(pace)}</Text>
                    </View>
                    <Text style={[styles.splitText, styles.splitElev]}>
                      {split.elevation_delta_m === null ? '–' : `${split.elevation_delta_m > 0 ? '+' : ''}${Math.round(split.elevation_delta_m)}`}
                    </Text>
                  </View>
                );
              })}
            </Card>
          </>
        )}

        {activity.pace_series.length > 1 && (
          <>
            <SectionLabel>Pace</SectionLabel>
            <Card style={styles.pad}>
              <LineChart
                invert
                points={activity.pace_series.map(([distance, pace]) => [distance / perUnit, pace * (perUnit / 1000)])}
                yLabel={(value) => formatPaceValue(value)}
                xLabel={(value) => (value === 0 ? '0' : `${value.toFixed(1)} ${unit}`)}
              />
              <Text style={typeScale.small}>Average {formatPace(paceSeconds(run.distance_m, run.moving_s, units), units)}</Text>
            </Card>
          </>
        )}

        {activity.elevation_series.length > 1 && (
          <>
            <SectionLabel>Elevation</SectionLabel>
            <Card style={styles.pad}>
              <LineChart
                area
                points={activity.elevation_series.map(([distance, altitude]) => [distance / perUnit, altitude])}
                yLabel={(value) => formatElevation(value, units)}
                xLabel={(value) => (value === 0 ? '0' : `${value.toFixed(1)} ${unit}`)}
              />
            </Card>
          </>
        )}

        {activity.best_efforts.length > 0 && (
          <>
            <SectionLabel>Best efforts</SectionLabel>
            <Card>
              {activity.best_efforts.map((effort, index) => (
                <Row
                  key={effort.distance_m}
                  title={EFFORT_LABELS[effort.distance_m] ?? `${effort.distance_m} m`}
                  subtitle={effort.personal_record ? 'Personal record when you ran it' : effort.rank && ORDINAL[effort.rank] ? `Your ${ORDINAL[effort.rank]!.toLowerCase()}` : undefined}
                  value={formatClock(effort.elapsed_s)}
                  trailing={effort.personal_record || effort.rank === 1 ? <RecordIcon size={18} color={ui.accent} strokeWidth={2} /> : <View style={styles.trailingSpace} />}
                  last={index === activity.best_efforts.length - 1}
                />
              ))}
            </Card>
          </>
        )}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 48 },
  head: { paddingHorizontal: 20, paddingBottom: 16, gap: 4 },
  title: { fontFamily: fonts.bold, fontSize: 26, color: ui.ink, paddingVertical: 2 },
  hero: { flexDirection: 'row', alignItems: 'baseline', gap: 6 },
  heroValue: { fontFamily: fonts.semibold, fontSize: 56, letterSpacing: -1.5, color: ui.ink },
  heroUnit: { fontFamily: fonts.medium, fontSize: 22, color: ui.ink2 },
  pad: { padding: 16, gap: 10 },
  spaced: { marginTop: 14 },
  note: { fontFamily: fonts.regular, fontSize: 16, color: ui.ink, minHeight: 64, textAlignVertical: 'top' },
  splitHead: { flexDirection: 'row', alignItems: 'center' },
  split: { flexDirection: 'row', alignItems: 'center', height: 30 },
  splitIndex: { width: 40 },
  splitBarCell: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8 },
  splitBar: { height: 8, borderRadius: 4, backgroundColor: ui.chartPast, maxWidth: '70%' },
  splitBarFastest: { backgroundColor: ui.chartCurrent },
  splitElev: { width: 44, textAlign: 'right' },
  splitText: { fontFamily: fonts.medium, fontSize: 14, color: ui.ink, fontVariant: ['tabular-nums'] },
  trailingSpace: { width: 18 },
});
