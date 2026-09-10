import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useGhostRace } from '@/features/social/useGhostRace';
import { useRecorder } from '@/features/recorder/useRecorder';
import {
  deleteGhost,
  fetchMyGhosts,
  fetchNearbyGhosts,
  updateGhost,
} from '@/services/api/client';
import type { GhostSummary } from '@/services/api/types';
import { formatDistance } from '@/lib/geo';
import { colors, fontSize, fontWeight, radius, spacing } from '@/theme';

/**
 * Ghosts you have recorded, and public ones nearby.
 *
 * Broadcasting a ghost publishes the recorded route. Being visible live while
 * someone races it is a second, separate switch — publishing a benchmark is not
 * an invitation to be followed.
 */

function message(error: unknown): string {
  if (!(error instanceof Error)) return 'Try again';
  const detail = error.message.match(/"detail":"([^"]+)"/);
  return detail?.[1] ?? error.message;
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${String(rest).padStart(2, '0')}`;
}

function GhostCard({
  ghost,
  onRace,
  onBroadcast,
  onShareLive,
  onDelete,
}: {
  ghost: GhostSummary;
  onRace: () => void;
  onBroadcast?: (value: boolean) => void;
  onShareLive?: (value: boolean) => void;
  onDelete?: () => void;
}) {
  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <View style={styles.cardText}>
          <Text style={styles.cardTitle}>{ghost.name}</Text>
          <Text style={styles.cardMeta}>
            {formatDistance(ghost.distance_m)} · {formatDuration(ghost.duration_s)}
            {ghost.is_yours ? '' : ` · @${ghost.owner.handle}`}
          </Text>
          {ghost.best_elapsed_s !== null ? (
            <Text style={styles.cardMeta}>Best attempt {formatDuration(ghost.best_elapsed_s)}</Text>
          ) : null}
        </View>
        <Pressable style={styles.raceButton} onPress={onRace}>
          <Text style={styles.raceButtonText}>Race</Text>
        </Pressable>
      </View>

      {onBroadcast ? (
        <View style={styles.toggleRow}>
          <View style={styles.cardText}>
            <Text style={styles.toggleLabel}>Broadcast this ghost</Text>
            <Text style={styles.hint}>
              Anyone nearby can race it. Both ends of the route are hidden from them.
            </Text>
          </View>
          <Switch value={ghost.is_public} onValueChange={onBroadcast} />
        </View>
      ) : null}

      {onShareLive && ghost.is_public ? (
        <View style={styles.toggleRow}>
          <View style={styles.cardText}>
            <Text style={styles.toggleLabel}>Also show me live on it</Text>
            <Text style={styles.hint}>Off by default. Broadcasting alone never reveals this.</Text>
          </View>
          <Switch value={ghost.share_live_location} onValueChange={onShareLive} />
        </View>
      ) : null}

      {onDelete ? (
        <Pressable onPress={onDelete}>
          <Text style={styles.delete}>Delete ghost</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export default function GhostsScreen() {
  const [mine, setMine] = useState<GhostSummary[]>([]);
  const [nearby, setNearby] = useState<GhostSummary[]>([]);
  const [busy, setBusy] = useState(true);
  const fix = useRecorder((state) => state.liveFix);
  const active = useGhostRace((state) => state.ghost);
  const ghostState = useGhostRace((state) => state.ghostState);

  const load = useCallback(() => {
    void fetchMyGhosts()
      .then(setMine)
      .catch(() => undefined)
      .finally(() => setBusy(false));
    // Nearby needs a position; without one there is simply nothing to show.
    const coordinate = fix?.coordinate;
    if (coordinate) {
      void fetchNearbyGhosts(coordinate[1], coordinate[0])
        .then(setNearby)
        .catch(() => undefined);
    }
  }, [fix?.coordinate]);
  useFocusEffect(load);

  const change = (
    ghostId: string,
    update: { is_public?: boolean; share_live_location?: boolean }
  ) => {
    setMine((current) =>
      current.map((ghost) =>
        ghost.id === ghostId
          ? {
              ...ghost,
              ...update,
              // Withdrawing the broadcast takes the live sharing with it.
              share_live_location:
                update.is_public === false ? false : update.share_live_location ?? ghost.share_live_location,
            }
          : ghost
      )
    );
    void updateGhost(ghostId, update).catch((error) => {
      Alert.alert('Could not update that ghost', message(error));
      load();
    });
  };

  const race = (ghost: GhostSummary) =>
    Alert.alert(
      `Race ${ghost.name}?`,
      'The ghost starts moving as soon as you begin. Start your run first, then keep your eyes on the road — the result is worked out for you.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Start',
          onPress: () => {
            void useGhostRace.getState().begin(ghost.id);
            router.push('/');
          },
        },
      ]
    );

  const stop = () => {
    void useGhostRace
      .getState()
      .end({ save: true })
      .then((result) => {
        if (result) {
          Alert.alert(result.beatGhost ? 'You beat the ghost' : 'The ghost held on');
        }
        load();
      });
  };

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}>
          <Text style={styles.back}>‹ Back</Text>
        </Pressable>
        <Text style={styles.title}>Ghosts</Text>
        <View style={styles.headerSpacer} />
      </View>

      {busy ? (
        <ActivityIndicator style={styles.loading} color={colors.primary} />
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={false} onRefresh={load} />}>
          {active ? (
            <View style={styles.activeCard}>
              <Text style={styles.activeTitle}>Racing {active.name}</Text>
              <Text style={styles.hint}>
                {ghostState
                  ? `Ghost ${Math.round(ghostState.progress * 100)}% along its route`
                  : 'Starting…'}
              </Text>
              <Pressable style={styles.stopButton} onPress={stop}>
                <Text style={styles.stopButtonText}>End ghost race</Text>
              </Pressable>
            </View>
          ) : null}

          <Text style={styles.sectionTitle}>Your ghosts</Text>
          {mine.length === 0 ? (
            <Text style={styles.hint}>
              Finish a run and save it as a ghost from the run summary to build a benchmark.
            </Text>
          ) : (
            mine.map((ghost) => (
              <GhostCard
                key={ghost.id}
                ghost={ghost}
                onRace={() => race(ghost)}
                onBroadcast={(value) => change(ghost.id, { is_public: value })}
                onShareLive={(value) => change(ghost.id, { share_live_location: value })}
                onDelete={() =>
                  Alert.alert(`Delete ${ghost.name}?`, 'Attempts against it go too.', [
                    { text: 'Cancel', style: 'cancel' },
                    {
                      text: 'Delete',
                      style: 'destructive',
                      onPress: () => void deleteGhost(ghost.id).then(load),
                    },
                  ])
                }
              />
            ))
          )}

          <Text style={styles.sectionTitle}>Nearby</Text>
          {nearby.length === 0 ? (
            <Text style={styles.hint}>
              No broadcast ghosts around here yet. They stay off the map until you open this list.
            </Text>
          ) : (
            nearby
              .filter((ghost) => !ghost.is_yours)
              .map((ghost) => (
                <GhostCard key={ghost.id} ghost={ghost} onRace={() => race(ghost)} />
              ))
          )}
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

  card: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  cardText: { flex: 1 },
  cardTitle: { fontSize: fontSize.md, fontWeight: fontWeight.medium, color: colors.text },
  cardMeta: { fontSize: fontSize.xs, color: colors.textMuted },
  toggleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  toggleLabel: { fontSize: fontSize.sm, color: colors.text },
  delete: { fontSize: fontSize.xs, color: colors.danger, marginTop: spacing.xs },

  raceButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    backgroundColor: colors.primary,
  },
  raceButtonText: {
    color: colors.background,
    fontSize: fontSize.sm,
    fontWeight: fontWeight.medium,
  },

  activeCard: {
    borderWidth: 1,
    borderColor: colors.ownedByYou,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.xs,
  },
  activeTitle: { fontSize: fontSize.md, fontWeight: fontWeight.bold, color: colors.text },
  stopButton: {
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    marginTop: spacing.xs,
  },
  stopButtonText: { fontSize: fontSize.sm, color: colors.text },
});
