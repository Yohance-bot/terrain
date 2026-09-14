import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { PlusIcon, SearchIcon } from '@/components/icons';
import { TabBar } from '@/components/TabBar';
import { Avatar, Card, EmptyState, ErrorState, Loading, Row, RoundButton, Screen, ScreenTitle, SectionLabel, Segmented } from '@/components/ui';
import { DuelsPanel } from '@/features/social/DuelsPanel';
import { useSocial } from '@/features/social/useSocial';
import {
  acceptFriendRequest,
  declineFriendRequest,
  fetchAccount,
  fetchFriends,
  fetchSharing,
  removeFriend,
  searchAccounts,
  sendFriendRequest,
  unblockAccount,
} from '@/services/api/client';
import type { AccountSummary, FriendList, PublicAccount, SharingOverview } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';

const EMPTY: FriendList = { friends: [], incoming: [], outgoing: [], blocked: [] };
const NO_SHARING: SharingOverview = { sharing_with: [], visible_to_me: [] };

function message(error: unknown): string {
  if (!(error instanceof Error)) return 'Try again';
  const detail = error.message.match(/"detail":"([^"]+)"/);
  return detail?.[1] ?? error.message;
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

export default function FriendsScreen() {
  const params = useLocalSearchParams<{ tab?: string }>();
  const [tab, setTab] = useState<'friends' | 'duels'>(params.tab === 'duels' ? 'duels' : 'friends');
  const unread = useSocial((state) => state.unreadCount);
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [list, setList] = useState<FriendList>(EMPTY);
  const [sharing, setSharing] = useState<SharingOverview>(NO_SHARING);
  const [failed, setFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(true);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PublicAccount[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [showSearch, setShowSearch] = useState(false);

  const load = useCallback(() => {
    return Promise.all([fetchFriends(), fetchSharing(), fetchAccount()])
      .then(([nextList, nextSharing, nextAccount]) => {
        setList(nextList); setSharing(nextSharing); setAccount(nextAccount ?? null); setFailed(false);
      })
      .catch(() => setFailed(true))
      .finally(() => { setBusy(false); setRefreshing(false); });
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const refreshAll = useCallback(async () => {
    setList(await fetchFriends());
    setSharing(await fetchSharing().catch(() => NO_SHARING));
    if (query.trim().length >= 2) setResults(await searchAccounts(query.trim()).catch(() => []));
  }, [query]);

  const act = (work: () => Promise<unknown>, failure: string) => {
    void work().then(refreshAll).catch((error) => Alert.alert(failure, message(error)));
  };

  const search = async () => {
    const text = query.trim();
    if (text.length < 2) {
      setResults(null);
      return;
    }
    setSearching(true);
    try {
      setResults(await searchAccounts(text));
    } catch (error) {
      Alert.alert('Could not search', message(error));
    } finally {
      setSearching(false);
    }
  };

  const switchTab = (next: 'friends' | 'duels') => {
    setTab(next);
    if (next === 'duels') void useSocial.getState().markRead();
  };

  const incoming = list.incoming.length;

  return (
    <Screen>
      <StatusBar style="dark" />
      <ScreenTitle
        title="Friends"
        right={
          tab === 'friends' ? (
            <RoundButton label="Add a friend" onPress={() => setShowSearch((open) => !open)}>
              <PlusIcon size={20} color={ui.icon} />
            </RoundButton>
          ) : undefined
        }
      />
      <View style={styles.segment}>
        <Segmented
          value={tab}
          onChange={switchTab}
          options={[
            { value: 'friends', label: 'Friends', badge: incoming > 0 ? String(incoming) : undefined },
            { value: 'duels', label: 'Duels', badge: unread > 0 ? String(unread) : undefined },
          ]}
        />
      </View>

      <ScrollView
        style={styles.fill}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={tab === 'friends' ? <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); void load(); }} tintColor={ui.accent} /> : undefined}
      >
        {tab === 'duels' ? (
          <DuelsPanel />
        ) : failed ? (
          <ErrorState onRetry={() => { setBusy(true); setFailed(false); void load(); }} />
        ) : busy ? (
          <Loading />
        ) : (
          <>
            {(showSearch || list.friends.length === 0) && (
              <>
                <View style={styles.search}>
                  <SearchIcon size={18} color={ui.ink3} />
                  <TextInput
                    value={query}
                    onChangeText={setQuery}
                    onSubmitEditing={() => void search()}
                    autoCapitalize="none"
                    autoCorrect={false}
                    returnKeyType="search"
                    placeholder="Search by name, @handle or account ID"
                    placeholderTextColor={ui.ink3}
                    style={styles.searchInput}
                    accessibilityLabel="Search for a friend"
                  />
                  {searching ? <ActivityIndicator color={ui.accent} /> : null}
                </View>
                {results !== null && (
                  <Card style={styles.results}>
                    {results.length === 0 ? (
                      <EmptyState title="No one matches that" body="Try their exact @handle." />
                    ) : (
                      results.map((found, index) => (
                        <Row
                          key={found.id}
                          title={found.display_name}
                          subtitle={`@${found.handle}`}
                          leading={<Avatar name={found.display_name} />}
                          last={index === results.length - 1}
                          trailing={
                            found.relationship === 'none' ? (
                              <Pill label="Add" tone="primary" onPress={() => act(() => sendFriendRequest(found.handle), 'Could not send')} />
                            ) : (
                              <Text style={styles.state}>
                                {found.relationship === 'friends' ? 'Friends' : found.relationship === 'request_sent' ? 'Requested' : found.relationship === 'request_received' ? 'Asked you' : 'Blocked'}
                              </Text>
                            )
                          }
                        />
                      ))
                    )}
                  </Card>
                )}
                {account?.handle ? (
                  <Text style={[typeScale.meta, styles.handle]}>Friends find you as @{account.handle}. Change it in Settings.</Text>
                ) : null}
              </>
            )}

            {incoming > 0 && (
              <>
                <SectionLabel>{`Requests · ${incoming}`}</SectionLabel>
                <Card>
                  {list.incoming.map((request, index) => (
                    <Row
                      key={request.id}
                      title={request.account.display_name}
                      subtitle={`@${request.account.handle}`}
                      leading={<Avatar name={request.account.display_name} />}
                      last={index === incoming - 1}
                      trailing={
                        <View style={styles.pills}>
                          <Pill label="Decline" onPress={() => act(() => declineFriendRequest(request.id), 'Could not decline')} />
                          <Pill label="Accept" tone="primary" onPress={() => act(() => acceptFriendRequest(request.id), 'Could not accept')} />
                        </View>
                      }
                    />
                  ))}
                </Card>
              </>
            )}

            <SectionLabel>{list.friends.length > 0 ? `Friends · ${list.friends.length}` : 'Friends'}</SectionLabel>
            <Card>
              {list.friends.length === 0 ? (
                <EmptyState title="No friends yet" body="Search for someone’s @handle to send the first request." />
              ) : (
                list.friends.map((friend, index) => {
                  const live = sharing.visible_to_me.some((row) => row.id === friend.account.id);
                  return (
                    <Row
                      key={friend.account.id}
                      title={friend.account.display_name}
                      subtitle={live ? 'Sharing their location with you' : `@${friend.account.handle}`}
                      leading={
                        <View>
                          <Avatar name={friend.account.display_name} tone={live ? 'accent' : 'soft'} />
                          {live ? <View style={styles.liveDot} /> : null}
                        </View>
                      }
                      onPress={() => router.push(`/friend/${friend.account.id}`)}
                      last={index === list.friends.length - 1}
                    />
                  );
                })
              )}
            </Card>

            {list.outgoing.length > 0 && (
              <>
                <SectionLabel>Sent</SectionLabel>
                <Card>
                  {list.outgoing.map((request, index) => (
                    <Row
                      key={request.id}
                      title={request.account.display_name}
                      subtitle={`@${request.account.handle}`}
                      leading={<Avatar name={request.account.display_name} />}
                      last={index === list.outgoing.length - 1}
                      trailing={<Pill label="Cancel" onPress={() => act(() => removeFriend(request.account.id), 'Could not cancel')} />}
                    />
                  ))}
                </Card>
              </>
            )}

            {list.blocked.length > 0 && (
              <>
                <SectionLabel>Blocked</SectionLabel>
                <Card>
                  {list.blocked.map((blocked, index) => (
                    <Row
                      key={blocked.id}
                      title={blocked.display_name}
                      leading={<Avatar name={blocked.display_name} />}
                      last={index === list.blocked.length - 1}
                      trailing={<Pill label="Unblock" onPress={() => act(() => unblockAccount(blocked.id), 'Could not unblock')} />}
                    />
                  ))}
                </Card>
              </>
            )}
          </>
        )}
      </ScrollView>
      <TabBar active="friends" badge={unread > 0 || incoming > 0} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  content: { paddingBottom: 32 },
  segment: { paddingHorizontal: 16, paddingBottom: 4 },
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginHorizontal: 16,
    marginTop: 12,
    height: 46,
    paddingHorizontal: 14,
    borderRadius: 14,
    backgroundColor: ui.surface,
  },
  searchInput: { flex: 1, fontFamily: fonts.regular, fontSize: 16, color: ui.ink },
  results: { marginTop: 10 },
  handle: { paddingHorizontal: 20, paddingTop: 10 },
  state: { fontFamily: fonts.medium, fontSize: 14, color: ui.ink3 },
  pills: { flexDirection: 'row', gap: 8 },
  pill: { height: 32, paddingHorizontal: 14, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  pillPrimary: { backgroundColor: ui.accent },
  pillNeutral: { backgroundColor: ui.segment },
  pillText: { fontFamily: fonts.semibold, fontSize: 14, color: ui.ink },
  liveDot: { position: 'absolute', right: -1, bottom: -1, width: 13, height: 13, borderRadius: 7, backgroundColor: ui.start, borderWidth: 2, borderColor: ui.surface },
});
