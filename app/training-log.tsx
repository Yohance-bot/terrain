import { router, useFocusEffect } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useMemo, useRef, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { MonthHeatmap } from '@/components/charts';
import { ChevronLeftIcon, ChevronRightIcon } from '@/components/icons';
import { RunRow } from '@/components/RunRow';
import { Card, EmptyState, ErrorState, Loading, NavHeader, RoundButton, Screen, SectionLabel } from '@/components/ui';
import { useHudPreferences } from '@/features/hud/usePresentation';
import { formatDistance, formatHours, monthName, monthShort } from '@/lib/format';
import { fetchRunsPage } from '@/services/api/client';
import type { RunSummary } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';

function mondayOf(date: Date) {
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  return monday;
}

export default function TrainingLogScreen() {
  const units = useHudPreferences((s) => s.units);
  const today = new Date();
  const requestId = useRef(0);
  const [cursor, setCursor] = useState({ year: today.getFullYear(), month: today.getMonth() });
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const isCurrentMonth = cursor.year === today.getFullYear() && cursor.month === today.getMonth();

  const load = useCallback(async () => {
    const request = ++requestId.current;
    try {
      const month = `${cursor.year}-${String(cursor.month + 1).padStart(2, '0')}`;
      // Month-filtered responses contain the entire month (not a paginated slice).
      const page = await fetchRunsPage({ month });
      if (request !== requestId.current) return;
      setRuns(page.runs);
      setError(null);
    } catch {
      if (request !== requestId.current) return;
      setError('Could not load this month. Pull down to try again.');
      setRuns((current) => current ?? []);
    }
  }, [cursor]);

  useFocusEffect(
    useCallback(() => {
      void load();
      return () => { requestId.current += 1; };
    }, [load]),
  );

  const shift = (delta: number) => {
    requestId.current += 1;
    setError(null);
    setRuns(null);
    setCursor(({ year, month }) => {
      const index = year * 12 + month + delta;
      return { year: Math.floor(index / 12), month: index % 12 };
    });
  };

  const { distances, weeks, totals } = useMemo(() => {
    const byDay = new Map<number, number>();
    const byWeek = new Map<number, { start: Date; runs: RunSummary[] }>();
    let distance = 0;
    let moving = 0;
    for (const run of runs ?? []) {
      const started = new Date(run.started_at);
      byDay.set(started.getDate(), (byDay.get(started.getDate()) ?? 0) + run.distance_m);
      const start = mondayOf(started);
      const group = byWeek.get(start.getTime()) ?? { start, runs: [] };
      group.runs.push(run);
      byWeek.set(start.getTime(), group);
      distance += run.distance_m;
      moving += run.moving_s;
    }
    return {
      distances: byDay,
      weeks: [...byWeek.values()].sort((a, b) => b.start.getTime() - a.start.getTime()),
      totals: { distance, moving, count: runs?.length ?? 0 },
    };
  }, [runs]);

  return (
    <Screen>
      <StatusBar style="dark" />
      <NavHeader title="Training log" onBack={() => router.back()} />
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            tintColor={ui.accent}
            onRefresh={() => {
              setRefreshing(true);
              void load().finally(() => setRefreshing(false));
            }}
          />
        }
      >
        <View style={styles.monthHead}>
          <View>
            <Text style={styles.month}>{monthName(cursor.month)} {cursor.year !== today.getFullYear() ? cursor.year : ''}</Text>
            <Text style={[typeScale.meta, styles.tabular]}>
              {formatDistance(totals.distance, units)} · {totals.count} {totals.count === 1 ? 'run' : 'runs'} · {formatHours(totals.moving)}
            </Text>
          </View>
          <View style={styles.arrows}>
            <RoundButton label="Previous month" onPress={() => shift(-1)}>
              <ChevronLeftIcon size={18} color={ui.icon} />
            </RoundButton>
            <View style={isCurrentMonth && styles.disabled} pointerEvents={isCurrentMonth ? 'none' : 'auto'}>
              <RoundButton label="Next month" onPress={() => shift(1)}>
                <ChevronRightIcon size={18} color={ui.icon} />
              </RoundButton>
            </View>
          </View>
        </View>

        <Card style={styles.calendar}>
          <MonthHeatmap year={cursor.year} month={cursor.month} distances={distances} today={today} />
          <View style={styles.legend}>
            <Text style={typeScale.small}>Shorter</Text>
            <View style={[styles.swatch, { backgroundColor: ui.chartPast }]} />
            <View style={[styles.swatch, { backgroundColor: ui.chartCurrent }]} />
            <View style={[styles.swatch, { backgroundColor: ui.accent }]} />
            <Text style={typeScale.small}>Longer</Text>
          </View>
        </Card>

        {error ? <ErrorState message={error} onRetry={() => void load()} /> : runs === null ? (
          <Loading />
        ) : weeks.length === 0 ? (
          <EmptyState title={`No runs in ${monthName(cursor.month)}`} body={isCurrentMonth ? 'Tap Start on the map to log one.' : undefined} />
        ) : (
          weeks.map(({ start, runs: weekRuns }) => {
            const end = new Date(start);
            end.setDate(end.getDate() + 6);
            const weekDistance = weekRuns.reduce((sum, run) => sum + run.distance_m, 0);
            return (
              <View key={start.getTime()}>
                <SectionLabel right={<Text style={styles.weekTotal}>{formatDistance(weekDistance, units)} · {weekRuns.length} {weekRuns.length === 1 ? 'run' : 'runs'}</Text>}>
                  {`${monthShort(start.getMonth())} ${start.getDate()} – ${monthShort(end.getMonth())} ${end.getDate()}`}
                </SectionLabel>
                <Card>
                  {weekRuns.map((run, index) => (
                    <RunRow
                      key={run.run_id}
                      run={run}
                      units={units}
                      showNote
                      last={index === weekRuns.length - 1}
                      onPress={() => router.push(`/activity/${run.run_id}`)}
                    />
                  ))}
                </Card>
              </View>
            );
          })
        )}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 40 },
  monthHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, paddingBottom: 14 },
  month: { fontFamily: fonts.bold, fontSize: 26, color: ui.ink },
  tabular: { fontVariant: ['tabular-nums'] },
  arrows: { flexDirection: 'row', gap: 8 },
  disabled: { opacity: 0.35 },
  calendar: { padding: 14, gap: 10 },
  legend: { flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 6 },
  swatch: { width: 12, height: 12, borderRadius: 3 },
  weekTotal: { fontFamily: fonts.semibold, fontSize: 13, color: ui.ink2 },
  error: { paddingHorizontal: 20, paddingTop: 12, color: ui.danger },
});
