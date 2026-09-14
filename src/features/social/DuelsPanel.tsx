import { useFocusEffect } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { Button, Card, EmptyState, ErrorState, Loading, SectionLabel, Toggle } from '@/components/ui';
import {
  answerChallenge,
  answerRace,
  createChallenge,
  fetchChallenges,
  fetchFriends,
  fetchRaces,
  fetchStakeableAreas,
} from '@/services/api/client';
import type { ChallengeMetric, ChallengeRecord, Friend, RaceRecord, StakeableArea } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';

/**
 * Duels: challenges between friends, and races to a dropped pin.
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

// The other side of a duel is context, not a second series: a quiet grey.
const OPPONENT = '#A7B0AA';

function message(error: unknown): string {
  if (!(error instanceof Error)) return 'Try again';
  const detail = error.message.match(/"detail":"([^"]+)"/);
  return detail?.[1] ?? error.message;
}

function formatValue(metric: ChallengeMetric, value: number | null): string {
  if (value === null) return '—';
  if (metric === 'distance') return `${(value / 1000).toFixed(2)} km`;
  if (metric === 'moving_time') return `${Math.round(value / 60)} min`;
  if (metric === 'captured_area') return value >= 10_000 ? `${(value / 10_000).toFixed(2)} ha` : `${Math.round(value)} m²`;
  return String(Math.round(value));
}

function remaining(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return 'Ended';
  const hours = Math.floor(ms / 3_600_000);
  if (hours >= 24) return `${Math.floor(hours / 24)} days left`;
  if (hours >= 1) return `${hours}h left`;
  return `${Math.max(1, Math.floor(ms / 60_000))}m left`;
}

function Pill({ label, onPress, tone = 'neutral' }: { label: string; onPress: () => void; tone?: 'primary' | 'neutral' }) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.pill, tone === 'primary' ? styles.pillPrimary : styles.pillNeutral, pressed && { opacity: 0.7 }]}
    >
      <Text style={[styles.pillText, tone === 'primary' && { color: ui.surface }]}>{label}</Text>
    </Pressable>
  );
}

function Chip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: selected }}
      onPress={onPress}
      style={[styles.chip, selected && styles.chipSelected]}
    >
      <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{label}</Text>
    </Pressable>
  );
}

function ScoreBar({ label, value, fraction, you }: { label: string; value: string; fraction: number; you?: boolean }) {
  return (
    <View style={styles.scoreRow}>
      <Text style={[styles.scoreLabel, you && { fontFamily: fonts.semibold, color: ui.ink }]} numberOfLines={1}>{label}</Text>
      <View style={styles.scoreTrack}>
        <View style={[styles.scoreFill, { width: `${Math.max(2, fraction * 100)}%`, backgroundColor: you ? ui.accent : OPPONENT }]} />
      </View>
      <Text style={[styles.scoreValue, !you && { color: ui.ink2, fontFamily: fonts.medium }]}>{value}</Text>
    </View>
  );
}

function ChallengeItem({
  challenge,
  last,
  onAnswer,
}: {
  challenge: ChallengeRecord;
  last: boolean;
  onAnswer: (answer: 'accept' | 'decline' | 'cancel') => void;
}) {
  const yours = challenge.role === 'challenger';
  const other = yours ? challenge.opponent : challenge.challenger;
  const yourValue = yours ? challenge.challenger_value : challenge.opponent_value;
  const theirValue = yours ? challenge.opponent_value : challenge.challenger_value;
  const won = challenge.winner_id !== null && challenge.winner_id !== other.id;
  const scale = Math.max(yourValue ?? 0, theirValue ?? 0, 1);
  const scored = challenge.status === 'accepted' || challenge.status === 'resolved';

  return (
    <View style={[styles.item, !last && styles.divider]}>
      <View style={styles.itemHead}>
        <View style={styles.itemText}>
          <Text style={typeScale.rowTitle} numberOfLines={2}>{challenge.goal_text}</Text>
          <Text style={typeScale.meta}>{yours ? 'You challenged' : 'From'} {other.display_name}</Text>
        </View>
        <Text style={styles.status}>
          {challenge.status === 'accepted' ? remaining(challenge.window_end) : challenge.status === 'pending' ? 'Waiting' : challenge.status === 'resolved' ? '' : challenge.status}
        </Text>
      </View>

      {scored ? (
        <View style={styles.scores}>
          <ScoreBar you label="You" value={formatValue(challenge.metric, yourValue)} fraction={(yourValue ?? 0) / scale} />
          <ScoreBar label={other.display_name.split(' ')[0] ?? other.display_name} value={formatValue(challenge.metric, theirValue)} fraction={(theirValue ?? 0) / scale} />
        </View>
      ) : null}

      {challenge.stake?.staked_area_m2 ? (
        <Text style={typeScale.meta}>
          Stake: {Math.round(challenge.stake.staked_area_m2)} m² of captured ground{challenge.stake.transferred_at ? ' — transferred' : ''}
        </Text>
      ) : null}
      {challenge.stake?.require_opponent_area_m2 ? (
        <Text style={typeScale.meta}>Entry: opponent must hold {Math.round(challenge.stake.require_opponent_area_m2)} m²</Text>
      ) : null}

      {challenge.status === 'resolved' ? (
        <Text style={[styles.outcome, won && { color: ui.accent }]}>
          {challenge.outcome === 'nobody' ? 'Neither of you ran. Nothing changed hands.' : challenge.outcome === 'draw' ? 'Dead level.' : won ? 'You won.' : `${other.display_name} won.`}
        </Text>
      ) : null}

      {challenge.status === 'pending' ? (
        <View style={styles.actions}>
          {!yours ? (
            <>
              <Pill label="Decline" onPress={() => onAnswer('decline')} />
              <Pill label="Accept" tone="primary" onPress={() => onAnswer('accept')} />
            </>
          ) : (
            <Pill label="Withdraw" onPress={() => onAnswer('cancel')} />
          )}
        </View>
      ) : null}
    </View>
  );
}

function RaceItem({ race, last, onAnswer }: { race: RaceRecord; last: boolean; onAnswer: (answer: 'accept' | 'decline' | 'withdraw') => void }) {
  const other = race.role === 'challenger' ? race.opponent : race.challenger;
  const invited = race.status === 'pending' && race.role === 'opponent';
  return (
    <View style={[styles.item, !last && styles.divider]}>
      <View style={styles.itemHead}>
        <View style={styles.itemText}>
          <Text style={typeScale.rowTitle}>{race.pin_label ?? 'Race to the pin'}</Text>
          <Text style={typeScale.meta}>
            {race.role === 'challenger' ? 'You challenged' : 'From'} {other.display_name} · first within {Math.round(race.radius_m)} m wins
          </Text>
        </View>
        <Text style={styles.status}>{race.status === 'running' ? 'Running' : 'Waiting'}</Text>
      </View>
      <View style={styles.actions}>
        {invited ? (
          <>
            <Pill label="Not now" onPress={() => onAnswer('decline')} />
            <Pill label="Accept" tone="primary" onPress={() => onAnswer('accept')} />
          </>
        ) : (
          <Pill label="End race" onPress={() => onAnswer('withdraw')} />
        )}
      </View>
    </View>
  );
}

export function DuelsPanel({ initialOpponent }: { initialOpponent?: string | null }) {
  const [challenges, setChallenges] = useState<ChallengeRecord[]>([]);
  const [races, setRaces] = useState<RaceRecord[]>([]);
  const [friends, setFriends] = useState<Friend[]>([]);
  const [areas, setAreas] = useState<StakeableArea[]>([]);
  const [busy, setBusy] = useState(true);

  const [opponentId, setOpponentId] = useState<string | null>(initialOpponent ?? null);
  const [metric, setMetric] = useState<ChallengeMetric>('distance');
  const [windowDays, setWindowDays] = useState(3);
  const [fastestTo, setFastestTo] = useState(false);
  const [target, setTarget] = useState('5');
  const [goal, setGoal] = useState('');
  const [stakeAreaId, setStakeAreaId] = useState<string | null>(null);
  const [entryRequirement, setEntryRequirement] = useState('');
  const [failed, setFailed] = useState(false);
  const [sending, setSending] = useState(false);

  const load = useCallback(() => {
    void Promise.all([
      fetchChallenges(),
      fetchRaces(),
      fetchFriends(),
      fetchStakeableAreas(),
    ])
      .then(([nextChallenges, nextRaces, friendList, nextAreas]) => {
        setChallenges(nextChallenges);
        setRaces(nextRaces);
        setFriends(friendList.friends);
        setAreas(nextAreas);
        setFailed(false);
      })
      .catch(() => setFailed(true))
      .finally(() => setBusy(false));
  }, []);
  useFocusEffect(load);

  const metricConfig = METRICS.find((entry) => entry.key === metric)!;
  const opponent = friends.find((friend) => friend.account.id === opponentId);
  const open = useMemo(() => challenges.filter((entry) => entry.status === 'pending' || entry.status === 'accepted'), [challenges]);
  const finished = useMemo(() => challenges.filter((entry) => entry.status !== 'pending' && entry.status !== 'accepted'), [challenges]);
  const openRaces = useMemo(() => races.filter((race) => race.status === 'pending' || race.status === 'running'), [races]);

  const defaultGoal = () => {
    const who = opponent?.account.display_name ?? 'you';
    if (fastestTo) return `First to ${target} ${metricConfig.unit} beats ${who}`;
    return `I'll cover more ${metricConfig.label.toLowerCase()} than ${who} in ${windowDays} day${windowDays === 1 ? '' : 's'}`;
  };

  const send = async () => {
    if (sending) return;
    if (fastestTo && (!Number.isFinite(Number(target)) || Number(target) <= 0 || (metric === 'runs' && !Number.isInteger(Number(target))))) {
      Alert.alert('Enter a valid positive target'); return;
    }
    if (entryRequirement.trim() && (!Number.isFinite(Number(entryRequirement)) || Number(entryRequirement) < 0)) {
      Alert.alert('Enter a valid territory requirement'); return;
    }
    if (!opponentId) {
      Alert.alert('Pick someone to challenge');
      return;
    }
    setSending(true);
    try {
      // Targets are entered in readable units; the server measures in metres
      // and seconds, so convert here rather than teaching the API two scales.
      const rawTarget = Number(target);
      const targetValue = fastestTo ? (metric === 'distance' ? rawTarget * 1000 : metric === 'moving_time' ? rawTarget * 60 : rawTarget) : null;
      const requirement = Number(entryRequirement);
      await createChallenge({
        opponent_id: opponentId,
        metric,
        comparison: fastestTo ? 'fastest_to' : 'most',
        target_value: targetValue,
        window_days: windowDays,
        goal_text: goal.trim() || defaultGoal(),
        stake: stakeAreaId || requirement > 0 ? { staked_area_id: stakeAreaId, require_opponent_area_m2: requirement > 0 ? requirement : null } : null,
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
    void answerChallenge(id, choice).then(load).catch((error) => Alert.alert('Could not update', message(error)));
  };
  const answerRaceInvite = (id: string, choice: 'accept' | 'decline' | 'withdraw') => {
    void answerRace(id, choice).then(load).catch((error) => Alert.alert('Could not update', message(error)));
  };

  if (busy) return <Loading />;
  if (failed) return <ErrorState onRetry={load} />;

  return (
    <View>
      {openRaces.length > 0 && (
        <>
          <SectionLabel>Races</SectionLabel>
          <Card>
            {openRaces.map((race, index) => (
              <RaceItem key={race.id} race={race} last={index === openRaces.length - 1} onAnswer={(choice) => answerRaceInvite(race.id, choice)} />
            ))}
          </Card>
        </>
      )}

      <SectionLabel>Active</SectionLabel>
      <Card>
        {open.length === 0 ? (
          <EmptyState title="No duels running" body="Challenge a friend below." />
        ) : (
          open.map((challenge, index) => (
            <ChallengeItem key={challenge.id} challenge={challenge} last={index === open.length - 1} onAnswer={(choice) => answer(challenge.id, choice)} />
          ))
        )}
      </Card>

      <SectionLabel>New duel</SectionLabel>
      <Card style={styles.form}>
        {friends.length === 0 ? (
          <Text style={typeScale.meta}>Add a friend before challenging anyone.</Text>
        ) : (
          <>
            <Text style={styles.field}>Who</Text>
            <View style={styles.chips}>
              {friends.map((friend) => (
                <Chip key={friend.account.id} label={friend.account.display_name} selected={friend.account.id === opponentId} onPress={() => setOpponentId(friend.account.id)} />
              ))}
            </View>

            <Text style={styles.field}>What counts</Text>
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

            <View style={styles.toggle}>
              <View style={styles.itemText}>
                <Text style={styles.field}>Race to a target</Text>
                <Text style={typeScale.meta}>
                  {metricConfig.raceable ? 'Whoever reaches it first wins, instead of who has most at the end.' : `${metricConfig.label} is compared as a total.`}
                </Text>
              </View>
              {metricConfig.raceable ? <Toggle label="Race to a target" value={fastestTo} onChange={setFastestTo} /> : null}
            </View>
            {fastestTo ? (
              <View style={styles.inline}>
                <TextInput value={target} onChangeText={setTarget} keyboardType="numeric" style={[styles.input, styles.short]} accessibilityLabel="Target" />
                <Text style={typeScale.meta}>{metricConfig.unit}</Text>
              </View>
            ) : null}

            <Text style={styles.field}>Over how long</Text>
            <View style={styles.chips}>
              {WINDOWS.map((days) => (
                <Chip key={days} label={days === 1 ? '1 day' : `${days} days`} selected={days === windowDays} onPress={() => setWindowDays(days)} />
              ))}
            </View>

            <Text style={styles.field}>The call</Text>
            <TextInput
              value={goal}
              onChangeText={setGoal}
              placeholder={defaultGoal()}
              placeholderTextColor={ui.ink3}
              maxLength={240}
              multiline
              style={[styles.input, styles.goal]}
              accessibilityLabel="The call"
            />

            <Text style={styles.field}>Stake a loop closure</Text>
            {areas.length === 0 ? (
              <Text style={typeScale.meta}>Close a loop on a run to be able to stake it.</Text>
            ) : (
              <View style={styles.chips}>
                <Chip label="Nothing" selected={stakeAreaId === null} onPress={() => setStakeAreaId(null)} />
                {areas.map((area) => (
                  <Chip key={area.id} label={`${Math.round(area.area_m2)} m²`} selected={area.id === stakeAreaId} onPress={() => setStakeAreaId(area.id)} />
                ))}
              </View>
            )}
            <Text style={typeScale.small}>If you lose, it becomes theirs. Fixed territory is earned by running, and only by running.</Text>

            <Text style={styles.field}>They must already hold</Text>
            <View style={styles.inline}>
              <TextInput
                value={entryRequirement}
                onChangeText={setEntryRequirement}
                keyboardType="numeric"
                placeholder="0"
                placeholderTextColor={ui.ink3}
                style={[styles.input, styles.short]}
                accessibilityLabel="Required captured ground"
              />
              <Text style={typeScale.meta}>m² of captured ground</Text>
            </View>

            <Button label="Send challenge" onPress={() => void send()} busy={sending} style={styles.send} />
          </>
        )}
      </Card>

      {finished.length > 0 && (
        <>
          <SectionLabel>Finished</SectionLabel>
          <Card>
            {finished.map((challenge, index) => (
              <ChallengeItem key={challenge.id} challenge={challenge} last={index === finished.length - 1} onAnswer={(choice) => answer(challenge.id, choice)} />
            ))}
          </Card>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  item: { padding: 16, gap: 10 },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: ui.line },
  itemHead: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 },
  itemText: { flex: 1, gap: 2 },
  status: { fontFamily: fonts.semibold, fontSize: 13, color: ui.ink2 },
  scores: { gap: 8 },
  scoreRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  scoreLabel: { width: 70, fontFamily: fonts.medium, fontSize: 13, color: ui.ink2 },
  scoreTrack: { flex: 1, height: 8, borderRadius: 4, backgroundColor: '#EEF1EC', overflow: 'hidden' },
  scoreFill: { height: 8, borderRadius: 4 },
  scoreValue: { width: 66, textAlign: 'right', fontFamily: fonts.semibold, fontSize: 14, color: ui.ink, fontVariant: ['tabular-nums'] },
  outcome: { fontFamily: fonts.semibold, fontSize: 14, color: ui.ink2 },
  actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
  pill: { height: 34, paddingHorizontal: 16, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  pillPrimary: { backgroundColor: ui.accent },
  pillNeutral: { backgroundColor: ui.segment },
  pillText: { fontFamily: fonts.semibold, fontSize: 14, color: ui.ink },
  form: { padding: 16, gap: 10 },
  field: { fontFamily: fonts.semibold, fontSize: 15, color: ui.ink, marginTop: 4 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { paddingHorizontal: 12, height: 34, borderRadius: 17, borderWidth: 1, borderColor: ui.line, justifyContent: 'center' },
  chipSelected: { borderColor: ui.accent, borderWidth: 1.5, backgroundColor: ui.accentSoft },
  chipText: { fontFamily: fonts.medium, fontSize: 14, color: ui.ink },
  chipTextSelected: { fontFamily: fonts.semibold, color: ui.accentPressed },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  inline: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  input: { borderWidth: 1, borderColor: ui.line, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontFamily: fonts.regular, fontSize: 15, color: ui.ink },
  short: { width: 90 },
  goal: { minHeight: 64, textAlignVertical: 'top' },
  send: { marginTop: 8 },
});
