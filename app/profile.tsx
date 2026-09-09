import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import {
  fetchAccount,
  requestAccountDeletion,
  signOutAccount,
  updateAccount,
  fetchCredentials,
  updateCredentials,
} from "@/services/api/client";
import { setDevRunnerId } from "@/lib/device";
import type { AccountSummary } from "@/services/api/types";
import { formatDistance } from "@/lib/geo";
import { getCaptureColorIndex, setCaptureColorIndex } from "@/lib/preferences";
import { CAPTURE_COLOR_PALETTE } from "@/theme/colors";
import { colors, fontSize, fontWeight, radius, spacing } from "@/theme";

export default function ProfileScreen() {
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [hasPassword, setHasPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(true);
  const [captureColor, setCaptureColor] = useState(0);

  const load = useCallback(() => {
    setBusy(true);
    void fetchAccount()
      .then((next) => {
        setAccount(next);
        setName(next?.display_name ?? "");
      })
      .catch(() => undefined)
      .finally(() => setBusy(false));
    void fetchCredentials()
      .then((value) => {
        setUsername(value.username ?? "");
        setHasPassword(value.has_password);
      })
      .catch(() => undefined);
    void getCaptureColorIndex().then(setCaptureColor);
  }, []);
  useFocusEffect(load);

  const save = async () => {
    if (!name.trim()) return;
    try {
      const updated = await updateAccount(name.trim());
      setAccount(updated);
      Alert.alert("Profile saved");
    } catch (e) {
      Alert.alert(
        "Could not save",
        e instanceof Error ? e.message : "Try again",
      );
    }
  };
  const signOut = () =>
    Alert.alert(
      "Sign out?",
      "Your account keeps its runs and territory history.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Sign out",
          style: "destructive",
          onPress: () =>
            void signOutAccount()
              .then(() => {
                setDevRunnerId(null);
                router.replace("/sign-in");
              })
              .catch(() => router.replace("/sign-in")),
        },
      ],
    );
  const deleteRequest = () =>
    Alert.alert(
      "Request account deletion?",
      "This logs a request for us to process. It does not erase your territory history immediately.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Request deletion",
          style: "destructive",
          onPress: () =>
            void requestAccountDeletion().then(() =>
              Alert.alert(
                "Request received",
                "Your account deletion request has been logged.",
              ),
            ),
        },
      ],
    );

  return (
    <SafeAreaView style={styles.screen} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}>
          <Text style={styles.back}>‹ Map</Text>
        </Pressable>
        <Text style={styles.title}>Profile</Text>
        <View />
      </View>
      {busy ? (
        <ActivityIndicator color={colors.primary} />
      ) : !account ? (
        <View style={styles.empty}>
          <Text style={styles.emptyTitle}>You’re playing anonymously</Text>
          <Text style={styles.muted}>
            Sign in with Google or your username and password.
          </Text>
          {
            <Pressable
              style={styles.primary}
              onPress={() => router.push("/sign-in")}
            >
              <Text style={styles.primaryText}>Sign in</Text>
            </Pressable>
          }
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>
              {account.display_name.slice(0, 1).toUpperCase()}
            </Text>
          </View>
          <Text style={styles.name}>{account.display_name}</Text>
          <Text style={styles.muted}>
            Joined {new Date(account.created_at).toLocaleDateString()}
          </Text>
          <TextInput
            value={name}
            onChangeText={setName}
            maxLength={32}
            style={styles.input}
            placeholder="Display name"
          />
          <Pressable style={styles.primary} onPress={() => void save()}>
            <Text style={styles.primaryText}>Save profile</Text>
          </Pressable>
          <View style={styles.stats}>
            <Stat
              value={formatDistance(account.total_distance_m)}
              label="Distance"
            />
            <Stat
              value={String(account.territories_led)}
              label="Territories led"
            />
          </View>

          {/* Capture Color Picker */}
          <View style={styles.colorPickerSection}>
            <Text style={styles.colorPickerLabel}>Capture color</Text>
            <Text style={styles.colorPickerSub}>
              Your loop captures will appear in this colour.
            </Text>
            <View style={styles.colorRow}>
              {CAPTURE_COLOR_PALETTE.map((hex, index) => (
                <Pressable
                  key={hex}
                  onPress={() => {
                    setCaptureColor(index);
                    void setCaptureColorIndex(index);
                  }}
                  style={[
                    styles.colorCircleWrap,
                    captureColor === index && styles.colorCircleWrapActive,
                  ]}
                >
                  <View
                    style={[styles.colorCircle, { backgroundColor: hex }]}
                  />
                </Pressable>
              ))}
            </View>
          </View>

          <View style={{ width: "100%", paddingVertical: 20 }}>
            <Text style={styles.name}>Sign-in details</Text>
            <Text style={styles.muted}>
              Works for Google and developer accounts too.
            </Text>
            <TextInput
              accessibilityLabel="Username"
              style={styles.input}
              placeholder="Username"
              autoCapitalize="none"
              autoCorrect={false}
              value={username}
              onChangeText={setUsername}
              maxLength={32}
            />
            {hasPassword && (
              <TextInput
                accessibilityLabel="Current password"
                style={styles.input}
                placeholder="Current password"
                secureTextEntry
                value={currentPassword}
                onChangeText={setCurrentPassword}
              />
            )}
            <TextInput
              accessibilityLabel="New password"
              style={styles.input}
              placeholder="New password · 12+ characters"
              secureTextEntry
              value={newPassword}
              onChangeText={setNewPassword}
              maxLength={128}
            />
            <Pressable
              style={styles.primary}
              disabled={saving}
              onPress={() => {
                setSaving(true);
                void updateCredentials(username, currentPassword, newPassword)
                  .then(() => {
                    setHasPassword(true);
                    setCurrentPassword("");
                    setNewPassword("");
                    Alert.alert("Sign-in details saved");
                  })
                  .catch((e) => Alert.alert("Could not update", e.message))
                  .finally(() => setSaving(false));
              }}
            >
              <Text style={styles.primaryText}>
                {saving ? "Saving…" : "Update sign-in details"}
              </Text>
            </Pressable>
          </View>
          <Pressable
            style={styles.row}
            onPress={() => router.push("/settings")}
          >
            <Text style={styles.rowText}>Settings</Text>
            <Text>›</Text>
          </Pressable>
          <Pressable style={styles.row} onPress={signOut}>
            <Text style={styles.rowText}>Sign out</Text>
            <Text>›</Text>
          </Pressable>
          <Pressable style={styles.delete} onPress={deleteRequest}>
            <Text style={styles.deleteText}>Request account deletion</Text>
          </Pressable>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}
function Stat({ value, label }: { value: string; label: string }) {
  return (
    <View>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background, padding: spacing.lg },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.xl,
  },
  back: { color: colors.primary, fontWeight: fontWeight.semibold },
  title: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.bold,
    color: colors.text,
  },
  content: { alignItems: "center" },
  avatar: {
    width: 76,
    height: 76,
    borderRadius: 38,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.primary,
  },
  avatarText: {
    fontSize: 32,
    color: colors.surface,
    fontWeight: fontWeight.bold,
  },
  name: {
    fontSize: 24,
    fontWeight: fontWeight.bold,
    color: colors.text,
    marginTop: spacing.sm,
  },
  muted: { fontSize: fontSize.sm, color: colors.textMuted },
  input: {
    width: "100%",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: spacing.xl,
    color: colors.text,
  },
  primary: {
    width: "100%",
    backgroundColor: colors.primary,
    borderRadius: radius.md,
    padding: spacing.md,
    alignItems: "center",
    marginTop: spacing.sm,
  },
  primaryText: { color: colors.surface, fontWeight: fontWeight.bold },
  stats: {
    width: "100%",
    flexDirection: "row",
    justifyContent: "space-around",
    paddingVertical: spacing.xl,
  },
  statValue: {
    fontSize: 22,
    fontWeight: fontWeight.bold,
    color: colors.text,
    textAlign: "center",
  },
  row: {
    width: "100%",
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderColor: colors.border,
  },
  rowText: { color: colors.text, fontSize: fontSize.md },
  delete: { marginTop: spacing.xl, padding: spacing.sm },
  deleteText: { color: "#B42318", fontWeight: fontWeight.semibold },
  empty: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: spacing.sm,
  },
  emptyTitle: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.bold,
    color: colors.text,
  },
  colorPickerSection: {
    width: "100%",
    paddingVertical: spacing.lg,
    borderTopWidth: 1,
    borderColor: colors.border,
  },
  colorPickerLabel: {
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
    color: colors.text,
  },
  colorPickerSub: {
    fontSize: fontSize.xs,
    color: colors.textMuted,
    marginTop: 2,
    marginBottom: spacing.md,
  },
  colorRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  colorCircleWrap: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 2,
    borderColor: "transparent",
    alignItems: "center",
    justifyContent: "center",
  },
  colorCircleWrapActive: { borderColor: colors.primary },
  colorCircle: { width: 28, height: 28, borderRadius: 14 },
});
