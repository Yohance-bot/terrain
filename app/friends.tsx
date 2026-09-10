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
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  acceptFriendRequest,
  blockAccount,
  declineFriendRequest,
  fetchAccount,
  fetchFriends,
  fetchSharing,
  removeFriend,
  searchAccounts,
  sendFriendRequest,
  unblockAccount,
  updateHandle,
  updateSharing,
} from '@/services/api/client';
import type {
  AccountSummary,
  FriendList,
  PublicAccount,
  SharingEntry,
  SharingOverview,
} from '@/services/api/types';
import { colors, fontSize, fontWeight, radius, spacing } from '@/theme';

const EMPTY: FriendList = { friends: [], incoming: [], outgoing: [], blocked: [] };

function message(error: unknown): string {
  if (!(error instanceof Error)) return 'Try again';
  // ApiRequestError carries the raw JSON body; surface the server's sentence.
  const detail = error.message.match(/"detail":"([^"]+)"/);
  return detail?.[1] ?? error.message;
}

function Avatar({ account }: { account: PublicAccount }) {
  return (
    <View style={styles.avatar}>
      <Text style={styles.avatarText}>{account.display_name.slice(0, 1).toUpperCase()}</Text>
    </View>
  );
}

function Row({
  account,
  children,
}: {
  account: PublicAccount;
  children?: React.ReactNode;
}) {
  return (
    <View style={styles.row}>
      <Avatar account={account} />
      <View style={styles.rowText}>
        <Text style={styles.rowName} numberOfLines={1}>
          {account.display_name}
        </Text>
        <Text style={styles.rowHandle} numberOfLines={1}>
          @{account.handle}
        </Text>
      </View>
      <View style={styles.rowActions}>{children}</View>
    </View>
  );
}

function Action({
  label,
  onPress,
  tone = 'neutral',
}: {
  label: string;
  onPress: () => void;
  tone?: 'primary' | 'neutral' | 'danger';
}) {
  return (
    <Pressable
      style={[
        styles.action,
        tone === 'primary' && styles.actionPrimary,
        tone === 'danger' && styles.actionDanger,
      ]}
      onPress={onPress}>
      <Text
        style={[
          styles.actionText,
          tone === 'primary' && styles.actionTextPrimary,
          tone === 'danger' && styles.actionTextDanger,
        ]}>
        {label}
      </Text>
    </Pressable>
  );
}

const NO_SHARING: SharingOverview = { sharing_with: [], visible_to_me: [] };

function FriendCard({
  entry,
  watching,
  onToggle,
  onChallenge,
  onManage,
}: {
  entry: SharingEntry;
  /** True when this friend is currently visible on your own map. */
  watching: boolean;
  onToggle: (update: { share_location?: boolean; notify_on_run_start?: boolean }) => void;
  onChallenge: () => void;
  onManage: () => void;
}) {
  return (
    <View style={styles.card}>
      <Row account={entry.account}>
        <Action label="Challenge" onPress={onChallenge} />
        <Action label="•••" onPress={onManage} />
      </Row>
      <View style={styles.toggleRow}>
        <View style={styles.toggleText}>
          <Text style={styles.toggleLabel}>Share my live location</Text>
          <Text style={styles.toggleHint}>
            {entry.location_expires_at
              ? 'On for a race, ending when the race does'
              : 'Off by default. Turn it off again any time.'}
          </Text>
        </View>
        <Switch
          value={entry.share_location}
          onValueChange={(value) => onToggle({ share_location: value })}
        />
      </View>
      <View style={styles.toggleRow}>
        <View style={styles.toggleText}>
          <Text style={styles.toggleLabel}>Tell them when I start a run</Text>
          <Text style={styles.toggleHint}>Separate from location — one without the other is fine.</Text>
        </View>
        <Switch
          value={entry.notify_on_run_start}
          onValueChange={(value) => onToggle({ notify_on_run_start: value })}
        />
      </View>
      {watching ? <Text style={styles.watching}>Sharing with you right now</Text> : null}
    </View>
  );
}

export default function FriendsScreen() {
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [list, setList] = useState<FriendList>(EMPTY);
  const [busy, setBusy] = useState(true);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PublicAccount[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [handleDraft, setHandleDraft] = useState('');
  const [editingHandle, setEditingHandle] = useState(false);
  const [sharing, setSharing] = useState<SharingOverview>(NO_SHARING);

  const load = useCallback(() => {
    void fetchFriends()
      .then(setList)
      .catch(() => undefined)
      .finally(() => setBusy(false));
    void fetchSharing()
      .then(setSharing)
      .catch(() => undefined);
    void fetchAccount()
      .then((next) => {
        setAccount(next);
        setHandleDraft(next?.handle ?? '');
      })
      .catch(() => undefined);
  }, []);
  useFocusEffect(load);

  // The search result rows carry the relationship, so any action that changes
  // it has to refresh them alongside the lists below.
  const refreshAll = useCallback(async () => {
    setList(await fetchFriends());
    setSharing(await fetchSharing().catch(() => NO_SHARING));
    if (query.trim().length >= 2) {
      setResults(await searchAccounts(query.trim()).catch(() => []));
    }
  }, [query]);

  const act = (work: () => Promise<unknown>, failure: string) => {
    void work()
      .then(refreshAll)
      .catch((error) => Alert.alert(failure, message(error)));
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

  const saveHandle = async () => {
    try {
      const updated = await updateHandle(handleDraft.trim());
      setAccount((current) => (current ? { ...current, handle: updated.handle } : current));
      setHandleDraft(updated.handle);
      setEditingHandle(false);
    } catch (error) {
      Alert.alert('Could not save that handle', message(error));
    }
  };

  const toggleSharing = (
    friendId: string,
    update: { share_location?: boolean; notify_on_run_start?: boolean }
  ) => {
    // Reflect the switch immediately; sharing controls that lag feel unsafe.
    setSharing((current) => ({
      ...current,
      sharing_with: current.sharing_with.map((entry) =>
        entry.account.id === friendId
          ? {
              ...entry,
              ...update,
              location_expires_at:
                update.share_location === undefined ? entry.location_expires_at : null,
            }
          : entry
      ),
    }));
    void updateSharing(friendId, update).catch((error) => {
      Alert.alert('Could not change sharing', message(error));
      void fetchSharing().then(setSharing).catch(() => undefined);
    });
  };

  const confirmRemove = (target: PublicAccount) =>
    Alert.alert(`Remove ${target.display_name}?`, 'You can send a new request later.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Remove',
        style: 'destructive',
        onPress: () => act(() => removeFriend(target.id), 'Could not remove'),
      },
      {
        text: 'Block',
        style: 'destructive',
        onPress: () =>
          act(() => blockAccount(target.id), 'Could not block'),
      },
    ]);

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}>
          <Text style={styles.back}>‹ Map</Text>
        </Pressable>
        <Text style={styles.title}>Friends</Text>
        <View style={styles.headerSpacer} />
      </View>

      {busy ? (
        <ActivityIndicator style={styles.loading} color={colors.primary} />
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={false} onRefresh={load} />}>
          <View style={styles.identity}>
            <Text style={styles.identityLabel}>Your handle</Text>
            {editingHandle ? (
              <View style={styles.identityEdit}>
                <TextInput
                  value={handleDraft}
                  onChangeText={setHandleDraft}
                  autoCapitalize="none"
                  autoCorrect={false}
                  maxLength={24}
                  style={[styles.input, styles.identityInput]}
                  placeholder="handle"
                  placeholderTextColor={colors.textMuted}
                />
                <Action label="Save" tone="primary" onPress={() => void saveHandle()} />
              </View>
            ) : (
              <Pressable style={styles.identityEdit} onPress={() => setEditingHandle(true)}>
                <Text style={styles.identityHandle}>@{account?.handle ?? '—'}</Text>
                <Text style={styles.identityChange}>Change</Text>
              </Pressable>
            )}
            <Text style={styles.hint}>Friends can find you by this handle.</Text>
          </View>

          <Text style={styles.sectionTitle}>Add a friend</Text>
          <View style={styles.searchRow}>
            <TextInput
              value={query}
              onChangeText={setQuery}
              onSubmitEditing={() => void search()}
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="search"
              style={[styles.input, styles.searchInput]}
              placeholder="Handle, name or account ID"
              placeholderTextColor={colors.textMuted}
            />
            <Action label="Search" tone="primary" onPress={() => void search()} />
          </View>

          {searching ? <ActivityIndicator color={colors.primary} /> : null}
          {results !== null && results.length === 0 && !searching ? (
            <Text style={styles.hint}>No account matches that name or ID.</Text>
          ) : null}
          {results?.map((found) => (
            <Row key={found.id} account={found}>
              {found.relationship === 'none' ? (
                <Action
                  label="Add"
                  tone="primary"
                  onPress={() => act(() => sendFriendRequest(found.handle), 'Could not send')}
                />
              ) : (
                <Text style={styles.stateText}>
                  {found.relationship === 'friends'
                    ? 'Friends'
                    : found.relationship === 'request_sent'
                      ? 'Requested'
                      : found.relationship === 'request_received'
                        ? 'Asked you'
                        : 'Blocked'}
                </Text>
              )}
            </Row>
          ))}

          {list.incoming.length > 0 ? (
            <>
              <Text style={styles.sectionTitle}>Requests</Text>
              {list.incoming.map((request) => (
                <Row key={request.id} account={request.account}>
                  <Action
                    label="Accept"
                    tone="primary"
                    onPress={() => act(() => acceptFriendRequest(request.id), 'Could not accept')}
                  />
                  <Action
                    label="Decline"
                    onPress={() => act(() => declineFriendRequest(request.id), 'Could not decline')}
                  />
                </Row>
              ))}
            </>
          ) : null}

          {list.outgoing.length > 0 ? (
            <>
              <Text style={styles.sectionTitle}>Sent</Text>
              {list.outgoing.map((request) => (
                <Row key={request.id} account={request.account}>
                  <Action
                    label="Cancel"
                    onPress={() =>
                      act(() => removeFriend(request.account.id), 'Could not cancel')
                    }
                  />
                </Row>
              ))}
            </>
          ) : null}

          <Text style={styles.sectionTitle}>
            {list.friends.length > 0 ? `Friends · ${list.friends.length}` : 'Friends'}
          </Text>
          {list.friends.length === 0 ? (
            <Text style={styles.hint}>
              No friends yet. Search for someone’s handle to send the first request.
            </Text>
          ) : (
            list.friends.map((friend) => {
              const entry = sharing.sharing_with.find(
                (row) => row.account.id === friend.account.id
              ) ?? {
                account: friend.account,
                share_location: false,
                notify_on_run_start: false,
                location_expires_at: null,
              };
              return (
                <FriendCard
                  key={friend.account.id}
                  entry={entry}
                  watching={sharing.visible_to_me.some((row) => row.id === friend.account.id)}
                  onToggle={(update) => toggleSharing(friend.account.id, update)}
                  onChallenge={() =>
                    router.push(`/challenges?opponent=${friend.account.id}`)
                  }
                  onManage={() => confirmRemove(friend.account)}
                />
              );
            })
          )}

          {list.blocked.length > 0 ? (
            <>
              <Text style={styles.sectionTitle}>Blocked</Text>
              {list.blocked.map((blocked) => (
                <Row key={blocked.id} account={blocked}>
                  <Action
                    label="Unblock"
                    onPress={() => act(() => unblockAccount(blocked.id), 'Could not unblock')}
                  />
                </Row>
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
  headerSpacer: { width: 48 },
  back: { color: colors.textMuted, fontSize: fontSize.md, width: 48 },
  title: { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: colors.text },
  loading: { marginTop: spacing.xl },
  content: { padding: spacing.md, paddingBottom: spacing.xl, gap: spacing.sm },

  identity: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.xs,
  },
  identityLabel: { color: colors.textMuted, fontSize: fontSize.sm },
  identityEdit: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  identityHandle: { flex: 1, fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: colors.text },
  identityChange: { color: colors.textMuted, fontSize: fontSize.sm },
  identityInput: { flex: 1 },

  sectionTitle: {
    marginTop: spacing.md,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
    color: colors.text,
  },
  hint: { color: colors.textMuted, fontSize: fontSize.sm },

  searchRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  searchInput: { flex: 1 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    color: colors.text,
  },

  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rowText: { flex: 1 },
  rowName: { fontSize: fontSize.md, color: colors.text, fontWeight: fontWeight.medium },
  rowHandle: { fontSize: fontSize.sm, color: colors.textMuted },
  rowActions: { flexDirection: 'row', gap: spacing.xs },
  stateText: { color: colors.textMuted, fontSize: fontSize.sm },

  card: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.sm,
    marginBottom: spacing.sm,
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  toggleText: { flex: 1 },
  toggleLabel: { fontSize: fontSize.sm, color: colors.text },
  toggleHint: { fontSize: fontSize.xs, color: colors.textMuted },
  watching: {
    fontSize: fontSize.xs,
    color: colors.ownedByYou,
    paddingBottom: spacing.xs,
  },

  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: { fontSize: fontSize.md, fontWeight: fontWeight.bold, color: colors.text },

  action: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  actionPrimary: { backgroundColor: colors.primary, borderColor: colors.primary },
  actionDanger: { borderColor: colors.danger },
  actionText: { fontSize: fontSize.sm, color: colors.text, fontWeight: fontWeight.medium },
  actionTextPrimary: { color: colors.background },
  actionTextDanger: { color: colors.danger },
});
