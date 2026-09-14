import { router, useFocusEffect } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ColumnChart, Meter, StreakCells } from '@/components/charts';
import { GoalIcon, LogIcon, SettingsIcon, ShoeIcon, StreakIcon } from '@/components/icons';
import { RunRow } from '@/components/RunRow';
import { TabBar } from '@/components/TabBar';
import {
  Avatar,
  Button,
  Card,
  EmptyState,
  ErrorState,
  IconTile,
  Loading,
  Row,
  RoundButton,
  Screen,
  ScreenTitle,
  SectionLabel,
  Segmented,
  StatRow,
} from '@/components/ui';
import { useHudPreferences } from '@/features/hud/usePresentation';
import {
  EFFORT_LABELS,
  distanceNumber,
  formatClock,
  formatDistance,
  formatElevation,
  formatHours,
  metresPerUnit,
  monthShort,
  shortDate,
  unitLabel,
  type Units,
} from '@/lib/format';
import { fetchAccount, fetchAthleteStats, fetchRunsPage } from '@/services/api/client';
import type { AccountSummary, AthleteStats, AthleteTotals, GoalProgress, RunSummary } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';

type Period = 'week' | 'year' | 'all';

function localDate(iso: string) {
  const date = new Date(iso);
  return `${monthShort(date.getMonth())} ${date.getDate()}, ${date.getFullYear()}`;
}

function totalsFor(stats: AthleteStats, period: Period): AthleteTotals {
  return period === 'week' ? stats.this_week : period === 'year' ? stats.year_to_date : stats.all_time;
}

function goalText(goal: GoalProgress, units: Units) {
  if (goal.metric === 'distance') {
    return { value: distanceNumber(goal.value, units), target: `/ ${distanceNumber(goal.target, units)} ${unitLabel(units)}`, left: goal.value >= goal.target ? 'Done for the week' : `${formatDistance(goal.target - goal.value, units)} to go` };
  }
  if (goal.metric === 'time') {
    return { value: formatHours(goal.value), target: `/ ${formatHours(goal.target)}`, left: goal.value >= goal.target ? 'Done for the week' : `${formatHours(goal.target - goal.value)} to go` };
  }
  const remaining = Math.max(0, Math.ceil(goal.target - goal.value));
  return { value: String(goal.value), target: `/ ${goal.target} runs`, left: remaining === 0 ? 'Done for the week' : `${remaining} more ${remaining === 1 ? 'run' : 'runs'}` };
}

export default function ProfileScreen() {
  const units = useHudPreferences((s) => s.units);
  const [account, setAccount] = useState<AccountSummary | null | undefined>(undefined);
  const [stats, setStats] = useState<AthleteStats | null>(null);
  const [recent, setRecent] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [period, setPeriod] = useState<Period>('year');
  const [chart, setChart] = useState<'weeks' | 'months'>('weeks');

  const load = useCallback(async () => {
    try {
      const next = await fetchAccount();
      setAccount(next ?? null);
      if (!next) return;
      const [nextStats, page] = await Promise.all([fetchAthleteStats(12), fetchRunsPage({ limit: 3 })]);
      setStats(nextStats);
      setRecent(page.runs);
      setError(null);
    } catch {
      setAccount((current) => (current === undefined ? null : current));
      setError('Could not load your training. Pull down to try again.');
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const settingsButton = (
    <RoundButton label="Settings" onPress={() => router.push('/settings')}>
      <SettingsIcon size={20} color={ui.icon} strokeWidth={2} />
    </RoundButton>
  );

  if (account === undefined) {
    return (
      <Screen>
        <StatusBar style="dark" />
        <ScreenTitle title="Profile" right={settingsButton} />
        <View style={styles.fill}><Loading /></View>
        <TabBar active="profile" />
      </Screen>
    );
  }

  if (account === null && error) {
    return <Screen><ScreenTitle title="Profile" right={settingsButton} /><View style={styles.fill}><ErrorState message={error} onRetry={() => void load()} /></View><TabBar active="profile" /></Screen>;
  }

  if (account === null) {
    return (
      <Screen>
        <StatusBar style="dark" />
        <ScreenTitle title="Profile" right={settingsButton} />
        <View style={styles.fill}>
          <EmptyState
            title="Sign in to see your training"
            body={error ?? 'Your runs, streak and records live with your account.'}
            action={<Button label="Sign in" onPress={() => router.push('/sign-in')} style={styles.signIn} />}
          />
        </View>
        <TabBar active="profile" />
      </Screen>
    );
  }

  const totals = stats ? totalsFor(stats, period) : null;
  const todayIndex = (new Date().getDay() + 6) % 7;
  const perUnit = metresPerUnit(units);

  return (
    <Screen>
      <StatusBar style="dark" />
      <ScrollView
        style={styles.fill}
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void refresh()} tintColor={ui.accent} />}
      >
        <ScreenTitle title="Profile" right={settingsButton} />

        <View style={styles.identity}>
          <Avatar name={account.display_name} size={64} tone="accent" />
          <View style={styles.identityText}>
            <Text style={styles.name} numberOfLines={1}>{account.display_name}</Text>
            <Text style={typeScale.meta}>@{account.handle ?? '—'} · joined {localDate(account.created_at)}</Text>
          </View>
        </View>

        {error ? <Text style={[typeScale.meta, styles.error]}>{error}</Text> : null}
        {!stats ? (
          error ? <ErrorState message={error} onRetry={() => void load()} /> : <Loading />
        ) : (
          <>
            <Card style={styles.pad}>
              <Segmented
                compact
                value={period}
                onChange={setPeriod}
                options={[
                  { value: 'week', label: 'This week' },
                  { value: 'year', label: 'This year' },
                  { value: 'all', label: 'All time' },
                ]}
              />
              {totals && (
                <StatRow
                  items={[
                    { value: distanceNumber(totals.distance_m, units), label: unitLabel(units) },
                    { value: String(totals.runs), label: totals.runs === 1 ? 'run' : 'runs' },
                    { value: formatHours(totals.moving_s), label: 'moving' },
                    { value: formatElevation(totals.elevation_gain_m, units), label: 'climbed' },
                  ]}
                />
              )}
            </Card>

            <Card style={[styles.pad, styles.gap]}>
              <View style={styles.lead}>
                <IconTile><StreakIcon size={22} /></IconTile>
                <View style={styles.leadText}>
                  <Text style={styles.leadTitle}>
                    {stats.streak.current_weeks} week{stats.streak.current_weeks === 1 ? '' : 's'} streak
                  </Text>
                  <Text style={typeScale.meta}>
                    {stats.streak.current_weeks === 0
                      ? 'Run this week to start one'
                      : !stats.streak.ran_this_week
                        ? `Run by Sunday to keep it · best ${stats.streak.best_weeks}`
                        : `Every week since ${stats.streak.current_since ? shortDate(stats.streak.current_since) : '—'} · best ${stats.streak.best_weeks}`}
                  </Text>
                </View>
              </View>
              <StreakCells weeks={stats.weeks.map((week) => week.runs > 0)} streakWeeks={Math.min(12, stats.streak.current_weeks)} />
              <View style={styles.between}>
                <Text style={typeScale.small}>12 weeks ago</Text>
                <Text style={typeScale.small}>This week</Text>
              </View>
            </Card>

            <Card style={[styles.pad, styles.gap]}>
              <View style={styles.lead}>
                <IconTile><GoalIcon size={22} /></IconTile>
                <Text style={[typeScale.rowTitle, styles.leadText]}>Weekly goal</Text>
                <Button variant="text" label={stats.goal ? 'Edit' : 'Set'} onPress={() => router.push('/goal')} />
              </View>
              {stats.goal ? (
                (() => {
                  const text = goalText(stats.goal, units);
                  return (
                    <>
                      <View style={styles.between}>
                        <View style={styles.baseline}>
                          <Text style={typeScale.hero}>{text.value}</Text>
                          <Text style={styles.target}>{text.target}</Text>
                        </View>
                        <Text style={[typeScale.meta, { fontFamily: fonts.semibold }]}>{text.left}</Text>
                      </View>
                      <Meter value={stats.goal.value} max={stats.goal.target} />
                    </>
                  );
                })()
              ) : (
                <Text style={typeScale.meta}>Pick a distance, time or number of runs for each week.</Text>
              )}
              <View style={styles.days}>
                {stats.week_days_m.map((metres, index) => (
                  <View key={index} style={styles.dayColumn}>
                    <View style={[styles.dayDot, metres > 0 ? styles.dayRan : styles.dayRest, index === todayIndex && metres === 0 && styles.dayToday]}>
                      {metres > 0 ? <Text style={styles.dayValue}>{(metres / perUnit).toFixed(1)}</Text> : null}
                    </View>
                    <Text style={[typeScale.small, index === todayIndex && { color: ui.ink }]}>{'MTWTFSS'[index]}</Text>
                  </View>
                ))}
              </View>
            </Card>

            <Card style={[styles.pad, styles.gap]}>
              <View style={styles.between}>
                <View>
                  <Text style={typeScale.rowTitle}>Distance</Text>
                  <Text style={typeScale.meta}>{chart === 'weeks' ? 'Last 12 weeks' : 'Last 12 months'}, {unitLabel(units)}</Text>
                </View>
                <View style={styles.chartToggle}>
                  <Segmented compact value={chart} onChange={setChart} options={[{ value: 'weeks', label: 'Weeks' }, { value: 'months', label: 'Months' }]} />
                </View>
              </View>
              <ColumnChart
                valueLabel={(value) => value.toFixed(1)}
                columns={
                  chart === 'weeks'
                    ? stats.weeks.map((week, index, all) => ({
                        value: week.distance_m / perUnit,
                        label: index === all.length - 1 ? 'This week' : index % 4 === 0 ? shortDate(week.week_start) : undefined,
                      }))
                    : stats.months.map((month, index, all) => ({
                        value: month.distance_m / perUnit,
                        label: index === all.length - 1 ? 'This month' : index % 3 === 0 ? monthShort(Number(month.month.slice(5)) - 1) : undefined,
                      }))
                }
              />
              <View style={styles.hairline} />
              <Text style={typeScale.sectionLabel}>LAST 4 WEEKS, PER WEEK</Text>
              <StatRow
                items={[
                  { value: stats.last_four_weeks.runs_per_week.toFixed(1), label: 'runs' },
                  { value: distanceNumber(stats.last_four_weeks.distance_m_per_week, units), label: unitLabel(units) },
                  { value: formatHours(stats.last_four_weeks.moving_s_per_week), label: 'moving' },
                ]}
              />
            </Card>

            <SectionLabel>Records</SectionLabel>
            <Card>
              {stats.best_efforts.length === 0 && !stats.longest_run ? (
                <EmptyState title="No records yet" body="Your fastest 1K, 5K and more appear here after a run." />
              ) : (
                <>
                  {stats.longest_run && (
                    <Row
                      title="Longest run"
                      subtitle={localDate(stats.longest_run.started_at)}
                      value={formatDistance(stats.longest_run.distance_m, units)}
                      onPress={() => router.push(`/activity/${stats.longest_run!.run_id}`)}
                    />
                  )}
                  {stats.biggest_climb && (
                    <Row
                      title="Biggest climb"
                      subtitle={localDate(stats.biggest_climb.started_at)}
                      value={formatElevation(stats.biggest_climb.elevation_gain_m, units)}
                      onPress={() => router.push(`/activity/${stats.biggest_climb!.run_id}`)}
                    />
                  )}
                  {stats.best_efforts.map((effort, index) => (
                    <Row
                      key={effort.distance_m}
                      title={EFFORT_LABELS[effort.distance_m] ?? `${effort.distance_m} m`}
                      subtitle={localDate(effort.started_at)}
                      value={formatClock(effort.elapsed_s)}
                      onPress={() => router.push(`/activity/${effort.run_id}`)}
                      last={index === stats.best_efforts.length - 1}
                    />
                  ))}
                </>
              )}
            </Card>

            <SectionLabel right={<Button variant="text" label="See all" onPress={() => router.push('/training-log')} />}>
              Training log
            </SectionLabel>
            <Card>
              {recent.length === 0 ? (
                <EmptyState title="No runs yet" body="Tap Start on the map. Every run lands here." />
              ) : (
                recent.map((run, index) => (
                  <RunRow key={run.run_id} run={run} units={units} last={index === recent.length - 1} onPress={() => router.push(`/activity/${run.run_id}`)} />
                ))
              )}
            </Card>

            <SectionLabel>More</SectionLabel>
            <Card>
              <Row title="Training log" leading={<LogIcon size={22} />} onPress={() => router.push('/training-log')} />
              <Row title="Shoes" leading={<ShoeIcon size={22} />} onPress={() => router.push('/shoes')} />
              <Row title="Territories held" value={String(stats.territories_held)} />
              <Row title="Territories captured" value={String(stats.territories_captured)} last />
            </Card>
          </>
        )}
      </ScrollView>
      <TabBar active="profile" />
    </Screen>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  content: { paddingBottom: 32 },
  identity: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, paddingBottom: 18 },
  identityText: { flex: 1, gap: 2 },
  name: { fontFamily: fonts.bold, fontSize: 22, color: ui.ink },
  error: { paddingHorizontal: 20, paddingBottom: 12, color: ui.danger },
  pad: { padding: 16, gap: 14, marginBottom: 14 },
  gap: { gap: 12 },
  lead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  leadText: { flex: 1 },
  leadTitle: { fontFamily: fonts.bold, fontSize: 22, color: ui.ink },
  between: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  baseline: { flexDirection: 'row', alignItems: 'baseline', gap: 4 },
  target: { fontFamily: fonts.medium, fontSize: 17, color: ui.ink2 },
  days: { flexDirection: 'row', justifyContent: 'space-between' },
  dayColumn: { alignItems: 'center', gap: 4 },
  dayDot: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  dayRan: { backgroundColor: ui.accent },
  dayRest: { borderWidth: 1.5, borderColor: ui.line },
  dayToday: { borderWidth: 2, borderColor: ui.ink },
  dayValue: { fontFamily: fonts.semibold, fontSize: 11, color: ui.surface },
  chartToggle: { width: 150 },
  hairline: { height: StyleSheet.hairlineWidth, backgroundColor: ui.line },
  signIn: { alignSelf: 'stretch', marginTop: 8 },
});
