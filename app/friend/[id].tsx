import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useState } from 'react';
import { Alert, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ColumnChart, StreakCells } from '@/components/charts';
import { DuelIcon, StreakIcon } from '@/components/icons';
import { RunRow } from '@/components/RunRow';
import { Avatar, Button, Card, EmptyState, ErrorState, IconTile, Loading, NavHeader, Row, Screen, SectionLabel, Segmented, StatRow, Toggle } from '@/components/ui';
import { useHudPreferences } from '@/features/hud/usePresentation';
import { EFFORT_LABELS, distanceNumber, formatClock, formatDistance, formatElevation, formatHours, metresPerUnit, monthShort, shortDate, unitLabel } from '@/lib/format';
import { blockAccount, fetchFriendProfile, fetchSharing, removeFriend, updateSharing } from '@/services/api/client';
import type { FriendProfile, SharingEntry } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';

type Period = 'week' | 'year' | 'all';

export default function FriendProfileScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const units = useHudPreferences((s) => s.units);
  const [profile, setProfile] = useState<FriendProfile | null>(null);
  const [sharing, setSharing] = useState<SharingEntry | null>(null);
  const [failed, setFailed] = useState(false);
  const [period, setPeriod] = useState<Period>('year');

  const load = useCallback(() => {
    void fetchFriendProfile(id)
      .then((next) => {
        setProfile(next);
        setFailed(false);
      })
      .catch(() => setFailed(true));
    void fetchSharing()
      .then((overview) => setSharing(overview.sharing_with.find((entry) => entry.account.id === id) ?? null))
      .catch(() => undefined);
  }, [id]);
  useFocusEffect(load);

  const toggle = (change: { share_location?: boolean; notify_on_run_start?: boolean }) => {
    setSharing((current) => (current ? { ...current, ...change } : current));
    void updateSharing(id, change).catch(() => {
      Alert.alert('Could not change sharing');
      load();
    });
  };

  const manage = () => {
    if (!profile) return;
    const name = profile.account.display_name;
    Alert.alert(name, undefined, [
      {
        text: 'Remove friend',
        style: 'destructive',
        onPress: () => void removeFriend(id).then(() => router.back()).catch(() => Alert.alert('Could not remove')),
      },
      {
        text: 'Block',
        style: 'destructive',
        onPress: () => void blockAccount(id).then(() => router.back()).catch(() => Alert.alert('Could not block')),
      },
      { text: 'Cancel', style: 'cancel' },
    ]);
  };

  const more = (
    <Text accessibilityRole="button" accessibilityLabel="More" onPress={manage} style={styles.more}>•••</Text>
  );

  if (failed) {
    return (
      <Screen>
        <NavHeader onBack={() => router.back()} />
        <ErrorState message="Check your connection. This profile is available only while you are friends." onRetry={load} />
      </Screen>
    );
  }
  if (!profile) {
    return (
      <Screen>
        <NavHeader onBack={() => router.back()} />
        <Loading />
      </Screen>
    );
  }

  const totals = period === 'week' ? profile.this_week : period === 'year' ? profile.year_to_date : profile.all_time;
  const since = new Date(profile.friends_since);
  const perUnit = metresPerUnit(units);

  return (
    <Screen>
      <StatusBar style="dark" />
      <NavHeader onBack={() => router.back()} right={more} />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.identity}>
          <Avatar name={profile.account.display_name} size={64} />
          <View style={styles.identityText}>
            <Text style={styles.name} numberOfLines={1}>{profile.account.display_name}</Text>
            <Text style={typeScale.meta}>@{profile.account.handle} · friends since {monthShort(since.getMonth())} {since.getFullYear()}</Text>
          </View>
        </View>

        <View style={styles.actions}>
          <Button
            label="Challenge"
            icon={<DuelIcon size={20} color={ui.surface} strokeWidth={2} />}
            onPress={() => router.push(`/challenges?opponent=${id}`)}
            style={styles.action}
          />
        </View>

        {sharing && (
          <Card style={styles.spaced}>
            <Row
              title="Share my live location"
              subtitle={sharing.location_expires_at ? 'On for a race, ending when the race does' : 'Off by default. Turn it off any time.'}
              trailing={<Toggle label="Share my live location" value={sharing.share_location} onChange={(value) => toggle({ share_location: value })} />}
            />
            <Row
              title="Tell them when I start a run"
              subtitle="Separate from location"
              trailing={<Toggle label="Tell them when I start a run" value={sharing.notify_on_run_start} onChange={(value) => toggle({ notify_on_run_start: value })} />}
              last
            />
          </Card>
        )}

        <Card style={styles.pad}>
          <Segmented
            compact
            value={period}
            onChange={setPeriod}
            options={[{ value: 'week', label: 'This week' }, { value: 'year', label: 'This year' }, { value: 'all', label: 'All time' }]}
          />
          <StatRow
            items={[
              { value: distanceNumber(totals.distance_m, units), label: unitLabel(units) },
              { value: String(totals.runs), label: totals.runs === 1 ? 'run' : 'runs' },
              { value: formatHours(totals.moving_s), label: 'moving' },
              { value: formatElevation(totals.elevation_gain_m, units), label: 'climbed' },
            ]}
          />
        </Card>

        <Card style={[styles.pad, styles.spaced]}>
          <View style={styles.lead}>
            <IconTile><StreakIcon size={22} /></IconTile>
            <View style={styles.leadText}>
              <Text style={styles.leadTitle}>{profile.streak.current_weeks} week{profile.streak.current_weeks === 1 ? '' : 's'} streak</Text>
              <Text style={typeScale.meta}>
                {profile.streak.current_since ? `Every week since ${shortDate(profile.streak.current_since)} · best ${profile.streak.best_weeks}` : `Best ${profile.streak.best_weeks} weeks`}
              </Text>
            </View>
          </View>
          <StreakCells weeks={profile.weeks.map((week) => week.runs > 0)} streakWeeks={Math.min(12, profile.streak.current_weeks)} />
        </Card>

        <Card style={[styles.pad, styles.spaced]}>
          <View>
            <Text style={typeScale.rowTitle}>Distance</Text>
            <Text style={typeScale.meta}>Last 12 weeks, {unitLabel(units)}</Text>
          </View>
          <ColumnChart
            valueLabel={(value) => value.toFixed(1)}
            columns={profile.weeks.map((week, index, all) => ({
              value: week.distance_m / perUnit,
              label: index === all.length - 1 ? 'This week' : index % 4 === 0 ? shortDate(week.week_start) : undefined,
            }))}
          />
        </Card>

        <SectionLabel>Records</SectionLabel>
        <Card>
          {profile.best_efforts.length === 0 && !profile.longest_run ? (
            <EmptyState title="No records yet" />
          ) : (
            <>
              {profile.longest_run && <Row title="Longest run" value={formatDistance(profile.longest_run.distance_m, units)} />}
              <Row title="Territories held" value={String(profile.territories_held)} last={profile.best_efforts.length === 0} />
              {profile.best_efforts.map((effort, index) => (
                <Row
                  key={effort.distance_m}
                  title={EFFORT_LABELS[effort.distance_m] ?? `${effort.distance_m} m`}
                  value={formatClock(effort.elapsed_s)}
                  last={index === profile.best_efforts.length - 1}
                />
              ))}
            </>
          )}
        </Card>

        <SectionLabel>Recent runs</SectionLabel>
        <Card>
          {profile.recent_runs.length === 0 ? (
            <EmptyState title="No runs yet" />
          ) : (
            profile.recent_runs.map((run, index) => <RunRow key={run.run_id} run={run} units={units} last={index === profile.recent_runs.length - 1} />)
          )}
        </Card>
        <Text style={[typeScale.small, styles.privacy]}>Routes stay private. Friends see distance, pace and time.</Text>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 48 },
  more: { fontFamily: fonts.bold, fontSize: 16, color: ui.ink, letterSpacing: 1, padding: 8 },
  identity: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, paddingBottom: 16 },
  identityText: { flex: 1, gap: 2 },
  name: { fontFamily: fonts.bold, fontSize: 22, color: ui.ink },
  actions: { flexDirection: 'row', gap: 10, paddingHorizontal: 16, paddingBottom: 14 },
  action: { flex: 1 },
  pad: { padding: 16, gap: 14 },
  spaced: { marginBottom: 14 },
  lead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  leadText: { flex: 1 },
  leadTitle: { fontFamily: fonts.bold, fontSize: 22, color: ui.ink },
  privacy: { textAlign: 'center', paddingTop: 16, paddingHorizontal: 24 },
});
