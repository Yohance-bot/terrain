import { router, useFocusEffect } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useState } from 'react';
import { Alert, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { GhostIcon } from '@/components/icons';
import { Button, Card, EmptyState, ErrorState, IconTile, Loading, NavHeader, Row, Screen, SectionLabel, Toggle } from '@/components/ui';
import { useHudPreferences } from '@/features/hud/usePresentation';
import { useRecorder } from '@/features/recorder/useRecorder';
import { useGhostRace } from '@/features/social/useGhostRace';
import { formatClock, formatDistance } from '@/lib/format';
import { deleteGhost, fetchMyGhosts, fetchNearbyGhosts, updateGhost } from '@/services/api/client';
import type { GhostSummary } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';

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

function GhostItem({
  ghost,
  last,
  onRace,
  onBroadcast,
  onShareLive,
  onDelete,
}: {
  ghost: GhostSummary;
  last: boolean;
  onRace: () => void;
  onBroadcast?: (value: boolean) => void;
  onShareLive?: (value: boolean) => void;
  onDelete?: () => void;
}) {
  const units = useHudPreferences((s) => s.units);
  return (
    <View style={[styles.item, !last && styles.divider]}>
      <View style={styles.head}>
        <IconTile><GhostIcon size={22} /></IconTile>
        <View style={styles.text}>
          <Text style={typeScale.rowTitle}>{ghost.name}</Text>
          <Text style={typeScale.meta}>
            {formatDistance(ghost.distance_m, units)} · {formatClock(ghost.duration_s)}
            {ghost.is_yours ? '' : ` · @${ghost.owner.handle}`}
          </Text>
          {ghost.best_elapsed_s !== null ? <Text style={typeScale.meta}>Best attempt {formatClock(ghost.best_elapsed_s)}</Text> : null}
        </View>
        <Button label="Race" onPress={onRace} style={styles.race} />
      </View>
      {onBroadcast ? (
        <Row
          title="Broadcast this ghost"
          subtitle="Anyone nearby can race it. Both ends of the route are hidden."
          trailing={<Toggle label="Broadcast this ghost" value={ghost.is_public} onChange={onBroadcast} />}
          last={!(onShareLive && ghost.is_public)}
        />
      ) : null}
      {onShareLive && ghost.is_public ? (
        <Row
          title="Also show me live on it"
          subtitle="Off by default. Broadcasting alone never reveals this."
          trailing={<Toggle label="Also show me live on it" value={ghost.share_live_location} onChange={onShareLive} />}
          last
        />
      ) : null}
      {onDelete ? <Button variant="danger" label="Delete ghost" onPress={onDelete} style={styles.delete} /> : null}
    </View>
  );
}

export default function GhostsScreen() {
  const [mine, setMine] = useState<GhostSummary[]>([]);
  const [nearby, setNearby] = useState<GhostSummary[]>([]);
  const [busy, setBusy] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [failed, setFailed] = useState(false);
  const fix = useRecorder((state) => state.liveFix);
  const active = useGhostRace((state) => state.ghost);
  const ghostState = useGhostRace((state) => state.ghostState);

  // Nearby needs a position, but only a rough one: rounding to ~110 m keeps a
  // stream of GPS fixes from refetching the list on every step.
  const coordinate = fix?.coordinate;
  const lat = coordinate ? Math.round(coordinate[1] * 1000) / 1000 : null;
  const lon = coordinate ? Math.round(coordinate[0] * 1000) / 1000 : null;

  const load = useCallback(() => {
    void fetchMyGhosts()
      .then((ghosts) => {
        setMine(ghosts);
        setFailed(false);
      })
      .catch(() => setFailed(true))
      .finally(() => {
        setBusy(false);
        setRefreshing(false);
      });
    if (lat !== null && lon !== null) {
      void fetchNearbyGhosts(lat, lon).then(setNearby).catch(() => undefined);
    }
  }, [lat, lon]);
  useFocusEffect(load);

  const change = (ghostId: string, update: { is_public?: boolean; share_live_location?: boolean }) => {
    setMine((current) =>
      current.map((ghost) =>
        ghost.id === ghostId
          ? {
              ...ghost,
              ...update,
              // Withdrawing the broadcast takes the live sharing with it.
              share_live_location: update.is_public === false ? false : update.share_live_location ?? ghost.share_live_location,
            }
          : ghost,
      ),
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
            router.navigate('/');
          },
        },
      ],
    );

  const stop = () => {
    void useGhostRace
      .getState()
      .end({ save: true })
      .then((result) => {
        if (result) Alert.alert(result.beatGhost ? 'You beat the ghost' : 'The ghost held on');
        load();
      });
  };

  const others = nearby.filter((ghost) => !ghost.is_yours);

  return (
    <Screen>
      <StatusBar style="dark" />
      <NavHeader title="Ghosts" onBack={() => router.back()} />
      {busy ? (
        <Loading />
      ) : failed && mine.length === 0 ? (
        <ErrorState onRetry={() => { setBusy(true); load(); }} />
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => {
                setRefreshing(true);
                load();
              }}
              tintColor={ui.accent}
            />
          }
        >
          {active ? (
            <Card style={styles.active}>
              <Text style={styles.activeTitle}>Racing {active.name}</Text>
              <Text style={typeScale.meta}>{ghostState ? `Ghost ${Math.round(ghostState.progress * 100)}% along its route` : 'Starting…'}</Text>
              <Button variant="secondary" label="End ghost race" onPress={stop} />
            </Card>
          ) : null}

          <SectionLabel>Your ghosts</SectionLabel>
          <Card>
            {mine.length === 0 ? (
              <EmptyState title="No ghosts yet" body="Save a finished run as a ghost from its summary to build a benchmark." />
            ) : (
              mine.map((ghost, index) => (
                <GhostItem
                  key={ghost.id}
                  ghost={ghost}
                  last={index === mine.length - 1}
                  onRace={() => race(ghost)}
                  onBroadcast={(value) => change(ghost.id, { is_public: value })}
                  onShareLive={(value) => change(ghost.id, { share_live_location: value })}
                  onDelete={() =>
                    Alert.alert(`Delete ${ghost.name}?`, 'Attempts against it go too.', [
                      { text: 'Cancel', style: 'cancel' },
                      { text: 'Delete', style: 'destructive', onPress: () => void deleteGhost(ghost.id).then(load) },
                    ])
                  }
                />
              ))
            )}
          </Card>

          <SectionLabel>Nearby</SectionLabel>
          <Card>
            {others.length === 0 ? (
              lat === null ? (
                <EmptyState title="Waiting for your position" body="Nearby ghosts are the ones close to you, so this needs a location fix first." />
              ) : (
                <EmptyState title="None nearby" body="Broadcast ghosts appear here when you’re close to their route." />
              )
            ) : (
              others.map((ghost, index) => <GhostItem key={ghost.id} ghost={ghost} last={index === others.length - 1} onRace={() => race(ghost)} />)
            )}
          </Card>
        </ScrollView>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 48 },
  item: { paddingVertical: 12, gap: 6 },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: ui.line },
  head: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16 },
  text: { flex: 1, gap: 1 },
  race: { height: 38, paddingHorizontal: 16 },
  delete: { alignSelf: 'flex-start', marginLeft: 6 },
  active: { padding: 16, gap: 8, marginTop: 8 },
  activeTitle: { fontFamily: fonts.bold, fontSize: 18, color: ui.ink },
});
