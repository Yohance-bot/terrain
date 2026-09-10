import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  answerChallenge,
  answerRace,
  createChallenge,
  fetchChallenges,
  fetchFriends,
  fetchRaces,
  fetchStakeableAreas,
} from '@/services/api/client';
import type {
  ChallengeMetric,
  ChallengeRecord,
  Friend,
  RaceRecord,
  StakeableArea,
} from '@/services/api/types';
import { colors, fontSize, fontWeight, radius, spacing } from '@/theme';

/**
 * Challenges and races.
 *
 * Only conditions the run pipeline already measures are offered. There is no
 * step count here because nothing in the app counts steps, and a challenge that
 * cannot be settled from evidence should not be possible to send.
 */
const METRICS: { key: ChallengeMetric; label: string; unit: string; raceable: boolean }[] = [
  { key: 'distance', label: 'Distance', unit: 'km', raceable: true },
  { key: 'runs', label: 'Number of runs', unit: 'runs', raceable: true },
  { key: 'moving_time', label: 'Time on your feet', unit: 'min', raceable: true },
  { key: 'captured_area', label: 'Area captured', unit: 'm²', raceable: false },
  { key: 'territories', label: 'Territories taken', unit: '', raceable: false },
];

const WINDOWS = [1, 3, 7, 14];

function message(error: unknown): string {
  if (!(error instanceof Error)) return 'Try again';
  const detail = error.message.match(/"detail":"([^"]+)"/);
  return detail?.[1] ?? error.message;
}

function formatValue(metric: ChallengeMetric, value: number | null): string {
  if (value === null) return '—';
  if (metric === 'distance') return `${(value / 1000).toFixed(2)} km`;
  if (metric === 'moving_time') return `${Math.round(value / 60)} min`;
  if (metric === 'captured_area')
    return value >= 10_000 ? `${(value / 10_000).toFixed(2)} ha` : `${Math.round(value)} m²`;
  return String(Math.round(value));
}

function remaining(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return 'ended';
  const hours = Math.floor(ms / 3_600_000);
  if (hours >= 24) return `${Math.floor(hours / 24)}d left`;
  if (hours >= 1) return `${hours}h left`;
  return `${Math.max(1, Math.floor(ms / 60_000))}m left`;
}

function Button({
  label,
  onPress,
  tone = 'neutral',
}: {
  label: string;
  onPress: () => void;
  tone?: 'primary' | 'neutral';
}) {
  return (
    <Pressable
      style={[styles.button, tone === 'primary' && styles.buttonPrimary]}
      onPress={onPress}>
      <Text style={[styles.buttonText, tone === 'primary' && styles.buttonTextPrimary]}>
        {label}
      </Text>
    </Pressable>
  );
}

function Chip({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable style={[styles.chip, selected && styles.chipSelected]} onPress={onPress}>
      <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{label}</Text>
    </Pressable>
  );
}

function ChallengeCard({
  challenge,
  onAnswer,
}: {
  challenge: ChallengeRecord;
  onAnswer: (answer: 'accept' | 'decline' | 'cancel') => void;
}) {
  const yours = challenge.role === 'challenger';
  const other = yours ? challenge.opponent : challenge.challenger;
  const yourValue = yours ? challenge.challenger_value : challenge.opponent_value;
  const theirValue = yours ? challenge.opponent_value : challenge.challenger_value;
  const won = challenge.winner_id !== null && challenge.winner_id !== other.id;

  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <Text style={styles.cardTitle} numberOfLines={2}>
          {challenge.goal_text}
        </Text>
        <Text style={styles.cardMeta}>
          {challenge.status === 'accepted'
            ? remaining(challenge.window_end)
            : challenge.status}
        </Text>
      </View>
      <Text style={styles.cardSubtitle}>
        {yours ? 'You challenged' : 'Challenged by'} {other.display_name} · @{other.handle}
      </Text>

      {challenge.status === 'accepted' || challenge.status === 'resolved' ? (
        <View style={styles.scoreRow}>
          <View style={styles.score}>
            <Text style={styles.scoreValue}>{formatValue(challenge.metric, yourValue)}</Text>
            <Text style={styles.scoreLabel}>You</Text>
          </View>
          <View style={styles.score}>
            <Text style={styles.scoreValue}>{formatValue(challenge.metric, theirValue)}</Text>
            <Text style={styles.scoreLabel}>{other.display_name.split(' ')[0]}</Text>
          </View>
        </View>
      ) : null}

      {challenge.stake?.staked_area_m2 ? (
        <Text style={styles.stake}>
          Stake: {Math.round(challenge.stake.staked_area_m2)} m² of captured ground
          {challenge.stake.transferred_at ? ' — transferred' : ''}
        </Text>
      ) : null}
      {challenge.stake?.require_opponent_area_m2 ? (
        <Text style={styles.stake}>
          Entry: opponent must hold {Math.round(challenge.stake.require_opponent_area_m2)} m²
        </Text>
      ) : null}

      {challenge.status === 'resolved' ? (
        <Text style={[styles.outcome, won && styles.outcomeWon]}>
          {challenge.outcome === 'nobody'
            ? 'Neither of you ran. Nothing changed hands.'
            : challenge.outcome === 'draw'
              ? 'Dead level.'
              : won
                ? 'You won.'
                : `${other.display_name} won.`}
        </Text>
      ) : null}

      <View style={styles.cardActions}>
        {challenge.status === 'pending' && !yours ? (
          <>
            <Button label="Accept" tone="primary" onPress={() => onAnswer('accept')} />
            <Button label="Decline" onPress={() => onAnswer('decline')} />
          </>
        ) : null}
        {challenge.status === 'pending' && yours ? (
          <Button label="Withdraw" onPress={() => onAnswer('cancel')} />
        ) : null}
      </View>
    </View>
  );
}

function RaceCard({
  race,
  onAnswer,
}: {
  race: RaceRecord;
  onAnswer: (answer: 'accept' | 'decline' | 'withdraw') => void;
}) {
  const other = race.role === 'challenger' ? race.opponent : race.challenger;
  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <Text style={styles.cardTitle}>{race.pin_label ?? 'Race to the pin'}</Text>
        <Text style={styles.cardMeta}>{race.status}</Text>
      </View>
      <Text style={styles.cardSubtitle}>
        {race.role === 'challenger' ? 'You challenged' : 'Challenged by'} {other.display_name}
      </Text>
      <Text style={styles.hint}>
        First within {Math.round(race.radius_m)} m of the pin wins. Watch the road, not the phone.
      </Text>
      <View style={styles.cardActions}>
        {race.status === 'pending' && race.role === 'opponent' ? (
          <>
            <Button label="Accept" tone="primary" onPress={() => onAnswer('accept')} />
            <Button label="Not now" onPress={() => onAnswer('decline')} />
          </>
        ) : null}
        {(race.status === 'pending' || race.status === 'running') &&
        !(race.status === 'pending' && race.role === 'opponent') ? (
          <Button label="End race" onPress={() => onAnswer('withdraw')} />
        ) : null}
      </View>
    </View>
  );
}

export default function ChallengesScreen() {
  const params = useLocalSearchParams<{ opponent?: string }>();
  const [challenges, setChallenges] = useState<ChallengeRecord[]>([]);
  const [races, setRaces] = useState<RaceRecord[]>([]);
  const [friends, setFriends] = useState<Friend[]>([]);
  const [areas, setAreas] = useState<StakeableArea[]>([]);
  const [busy, setBusy] = useState(true);

  const [opponentId, setOpponentId] = useState<string | null>(params.opponent ?? null);
  const [metric, setMetric] = useState<ChallengeMetric>('distance');
  const [windowDays, setWindowDays] = useState(3);
  const [fastestTo, setFastestTo] = useState(false);
  const [target, setTarget] = useState('5');
  const [goal, setGoal] = useState('');
  const [stakeAreaId, setStakeAreaId] = useState<string | null>(null);
  const [entryRequirement, setEntryRequirement] = useState('');
  const [sending, setSending] = useState(false);

  const load = useCallback(() => {
    void Promise.all([
      fetchChallenges().catch(() => []),
      fetchRaces().catch(() => []),
      fetchFriends().catch(() => ({ friends: [], incoming: [], outgoing: [], blocked: [] })),
      fetchStakeableAreas().catch(() => []),
    ])
      .then(([nextChallenges, nextRaces, friendList, nextAreas]) => {
        setChallenges(nextChallenges);
        setRaces(nextRaces);
        setFriends(friendList.friends);
        setAreas(nextAreas);
      })
      .finally(() => setBusy(false));
  }, []);
  useFocusEffect(load);

  const metricConfig = METRICS.find((entry) => entry.key === metric)!;
  const opponent = friends.find((friend) => friend.account.id === opponentId);

  const open = useMemo(
    () => challenges.filter((entry) => entry.status === 'pending' || entry.status === 'accepted'),
    [challenges]
  );
  const finished = useMemo(
    () => challenges.filter((entry) => entry.status !== 'pending' && entry.status !== 'accepted'),
    [challenges]
  );
  const openRaces = useMemo(
    () => races.filter((race) => race.status === 'pending' || race.status === 'running'),
    [races]
  );

  const defaultGoal = () => {
    const who = opponent?.account.display_name ?? 'you';
    if (fastestTo) {
      return `First to ${target} ${metricConfig.unit} beats ${who}`;
    }
    return `I'll cover more ${metricConfig.label.toLowerCase()} than ${who} in ${windowDays} day${
      windowDays === 1 ? '' : 's'
    }`;
  };

  const send = async () => {
    if (!opponentId) {
      Alert.alert('Pick someone to challenge');
      return;
    }
    setSending(true);
    try {
      // Targets are entered in readable units; the server measures in metres
      // and seconds, so convert here rather than teaching the API two scales.
      const rawTarget = Number(target);
      const targetValue = fastestTo
        ? metric === 'distance'
          ? rawTarget * 1000
          : metric === 'moving_time'
            ? rawTarget * 60
            : rawTarget
        : null;
      const requirement = Number(entryRequirement);
      await createChallenge({
        opponent_id: opponentId,
        metric,
        comparison: fastestTo ? 'fastest_to' : 'most',
        target_value: targetValue,
        window_days: windowDays,
        goal_text: goal.trim() || defaultGoal(),
        stake:
          stakeAreaId || requirement > 0
            ? {
                staked_area_id: stakeAreaId,
                require_opponent_area_m2: requirement > 0 ? requirement : null,
              }
            : null,
      });
      setGoal('');
      setStakeAreaId(null);
      setEntryRequirement('');
      load();
    } catch (error) {
      Alert.alert('Could not send that challenge', message(error));
    } finally {
      setSending(false);
    }
  };

  const answer = (id: string, choice: 'accept' | 'decline' | 'cancel') => {
    void answerChallenge(id, choice)
      .then(load)
      .catch((error) => Alert.alert('Could not update', message(error)));
  };

  const answerRaceInvite = (id: string, choice: 'accept' | 'decline' | 'withdraw') => {
    void answerRace(id, choice)
      .then(load)
      .catch((error) => Alert.alert('Could not update', message(error)));
  };

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}>
          <Text style={styles.back}>‹ Back</Text>
        </Pressable>
        <Text style={styles.title}>Challenges</Text>
        <View style={styles.headerSpacer} />
      </View>

      {busy ? (
        <ActivityIndicator style={styles.loading} color={colors.primary} />
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={false} onRefresh={load} />}>
          {openRaces.length > 0 ? (
            <>
              <Text style={styles.sectionTitle}>Races</Text>
              {openRaces.map((race) => (
                <RaceCard
                  key={race.id}
                  race={race}
                  onAnswer={(choice) => answerRaceInvite(race.id, choice)}
                />
              ))}
            </>
          ) : null}

          <Text style={styles.sectionTitle}>New challenge</Text>
          {friends.length === 0 ? (
            <Text style={styles.hint}>Add a friend before challenging anyone.</Text>
          ) : (
            <View style={styles.form}>
              <Text style={styles.fieldLabel}>Who</Text>
              <View style={styles.chips}>
                {friends.map((friend) => (
                  <Chip
                    key={friend.account.id}
                    label={friend.account.display_name}
                    selected={friend.account.id === opponentId}
                    onPress={() => setOpponentId(friend.account.id)}
                  />
                ))}
              </View>

              <Text style={styles.fieldLabel}>What counts</Text>
              <View style={styles.chips}>
                {METRICS.map((entry) => (
                  <Chip
                    key={entry.key}
                    label={entry.label}
                    selected={entry.key === metric}
                    onPress={() => {
                      setMetric(entry.key);
                      if (!entry.raceable) setFastestTo(false);
                    }}
                  />
                ))}
              </View>

              <View style={styles.toggleRow}>
                <View style={styles.toggleText}>
                  <Text style={styles.fieldLabel}>Race to a target</Text>
                  <Text style={styles.hint}>
                    {metricConfig.raceable
                      ? 'Whoever reaches it first wins, instead of who has most at the end.'
                      : `${metricConfig.label} is compared as a total.`}
                  </Text>
                </View>
                <Switch
                  value={fastestTo}
                  disabled={!metricConfig.raceable}
                  onValueChange={setFastestTo}
                />
              </View>
              {fastestTo ? (
                <View style={styles.inlineField}>
                  <TextInput
                    value={target}
                    onChangeText={setTarget}
                    keyboardType="numeric"
                    style={[styles.input, styles.targetInput]}
                  />
                  <Text style={styles.hint}>{metricConfig.unit}</Text>
                </View>
              ) : null}

              <Text style={styles.fieldLabel}>Over how long</Text>
              <View style={styles.chips}>
                {WINDOWS.map((days) => (
                  <Chip
                    key={days}
                    label={days === 1 ? '1 day' : `${days} days`}
                    selected={days === windowDays}
                    onPress={() => setWindowDays(days)}
                  />
                ))}
              </View>

              <Text style={styles.fieldLabel}>The call</Text>
              <TextInput
                value={goal}
                onChangeText={setGoal}
                placeholder={defaultGoal()}
                placeholderTextColor={colors.textMuted}
                maxLength={240}
                multiline
                style={[styles.input, styles.goalInput]}
              />

              <Text style={styles.fieldLabel}>Stake a loop closure (optional)</Text>
              {areas.length === 0 ? (
                <Text style={styles.hint}>
                  You have no closed loops yet. Close one on a run to be able to stake it.
                </Text>
              ) : (
                <View style={styles.chips}>
                  <Chip
                    label="Nothing"
                    selected={stakeAreaId === null}
                    onPress={() => setStakeAreaId(null)}
                  />
                  {areas.map((area) => (
                    <Chip
                      key={area.id}
                      label={`${Math.round(area.area_m2)} m²`}
                      selected={area.id === stakeAreaId}
                      onPress={() => setStakeAreaId(area.id)}
                    />
                  ))}
                </View>
              )}
              <Text style={styles.hint}>
                If you lose, it becomes theirs. Fixed territory cannot be staked — it is earned by
                running, and only by running.
              </Text>

              <Text style={styles.fieldLabel}>They must already hold (optional)</Text>
              <View style={styles.inlineField}>
                <TextInput
                  value={entryRequirement}
                  onChangeText={setEntryRequirement}
                  keyboardType="numeric"
                  placeholder="0"
                  placeholderTextColor={colors.textMuted}
                  style={[styles.input, styles.targetInput]}
                />
                <Text style={styles.hint}>m² of captured ground to accept</Text>
              </View>

              <Button
                label={sending ? 'Sending…' : 'Send challenge'}
                tone="primary"
                onPress={() => void send()}
              />
            </View>
          )}

          <Text style={styles.sectionTitle}>Running</Text>
          {open.length === 0 ? (
            <Text style={styles.hint}>Nothing open right now.</Text>
          ) : (
            open.map((challenge) => (
              <ChallengeCard
                key={challenge.id}
                challenge={challenge}
                onAnswer={(choice) => answer(challenge.id, choice)}
              />
            ))
          )}

          {finished.length > 0 ? (
            <>
              <Text style={styles.sectionTitle}>Finished</Text>
              {finished.map((challenge) => (
                <ChallengeCard
                  key={challenge.id}
                  challenge={challenge}
                  onAnswer={(choice) => answer(challenge.id, choice)}
                />
              ))}
            </>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  headerSpacer: { width: 56 },
  back: { color: colors.textMuted, fontSize: fontSize.md, width: 56 },
  title: { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: colors.text },
  loading: { marginTop: spacing.xl },
  content: { padding: spacing.md, paddingBottom: spacing.xxl, gap: spacing.xs },

  sectionTitle: {
    marginTop: spacing.md,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
    color: colors.text,
  },
  hint: { color: colors.textMuted, fontSize: fontSize.xs },
  fieldLabel: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.medium,
    color: colors.text,
    marginTop: spacing.sm,
  },

  form: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.xs,
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  chip: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipSelected: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: fontSize.sm, color: colors.text },
  chipTextSelected: { color: colors.background },

  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    color: colors.text,
  },
  goalInput: { minHeight: 60, textAlignVertical: 'top' },
  targetInput: { width: 90 },
  inlineField: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  toggleText: { flex: 1 },

  card: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  cardHead: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  cardTitle: {
    flex: 1,
    fontSize: fontSize.md,
    fontWeight: fontWeight.medium,
    color: colors.text,
  },
  cardMeta: { fontSize: fontSize.xs, color: colors.textMuted },
  cardSubtitle: { fontSize: fontSize.sm, color: colors.textMuted },
  cardActions: { flexDirection: 'row', gap: spacing.xs, marginTop: spacing.xs },

  scoreRow: { flexDirection: 'row', gap: spacing.lg, marginTop: spacing.xs },
  score: { alignItems: 'flex-start' },
  scoreValue: { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: colors.text },
  scoreLabel: { fontSize: fontSize.xs, color: colors.textMuted },
  stake: { fontSize: fontSize.xs, color: colors.ownedByOther },
  outcome: { fontSize: fontSize.sm, color: colors.textMuted, marginTop: spacing.xs },
  outcomeWon: { color: colors.startGreenDark, fontWeight: fontWeight.bold },

  button: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  buttonPrimary: { backgroundColor: colors.primary, borderColor: colors.primary },
  buttonText: { fontSize: fontSize.sm, color: colors.text, fontWeight: fontWeight.medium },
  buttonTextPrimary: { color: colors.background },
});
