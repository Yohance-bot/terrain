import { router } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { GradientBackground } from "@/components/ui";
import { MapIcon } from "@/components/icons";
import { fonts, ui } from "@/theme";
import { StatusBar } from "expo-status-bar";
import { passwordLogin } from "@/services/api/client";
import { startGoogleSignIn } from "@/lib/auth/google";
import { accountErrorMessage } from "@/services/api/errors";
export default function SignInScreen() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [create, setCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(google = false) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (google) {
        if (await startGoogleSignIn()) router.replace("/");
      } else {
        await passwordLogin(
          username.trim(),
          password,
          create ? name.trim() : undefined,
        );
        router.replace("/");
      }
    } catch (e) {
      setError(accountErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <SafeAreaView style={s.screen}>
      <GradientBackground />
      <StatusBar style="dark" />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          contentContainerStyle={s.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <View style={s.hero}>
            <View style={s.mark}>
              <MapIcon size={30} color={ui.start} />
            </View>
            <Text style={s.eyebrow}>TERRARUN</Text>
            <Text style={s.title}>Your next run.{"\n"}A world to claim.</Text>
            <Text style={s.subtitle}>Find your rhythm. Leave your mark.</Text>
          </View>
          <View style={s.card}>
            <Text style={s.heading}>
              {create ? "Meet your runner." : "Welcome back."}
            </Text>
            <Pressable
              accessibilityRole="button"
              disabled={busy}
              style={s.google}
              onPress={() => void submit(true)}
            >
              <Feather name="globe" size={20} color={ui.ink} />
              <Text style={s.googleText}>Continue with Google</Text>
            </Pressable>
            <Text style={s.divider}>OR USE YOUR USERNAME</Text>
            {create && (
              <TextInput
                accessibilityLabel="Display name"
                style={s.input}
                placeholder="Runner name"
                placeholderTextColor="#79877E"
                value={name}
                onChangeText={setName}
                maxLength={32}
              />
            )}
            <TextInput
              accessibilityLabel="Username"
              style={s.input}
              placeholder="Username"
              placeholderTextColor="#79877E"
              value={username}
              onChangeText={setUsername}
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="username"
              maxLength={32}
            />
            <TextInput
              accessibilityLabel="Password"
              style={s.input}
              placeholder={create ? "Password · 12+ characters" : "Password"}
              placeholderTextColor="#79877E"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              returnKeyType="go"
              onSubmitEditing={() => { if (username.trim() && password && (!create || name.trim().length >= 2)) void submit(); }}
              autoComplete={create ? "new-password" : "current-password"}
              maxLength={128}
            />
            {error ? (
              <Text accessibilityRole="alert" style={s.error}>
                {error}
              </Text>
            ) : null}
            <Pressable
              accessibilityRole="button"
              style={[s.primary, (busy || !username.trim() || !password || (create && name.trim().length < 2)) && { opacity: 0.45 }]}
              disabled={
                busy ||
                !username.trim() ||
                !password ||
                (create && name.trim().length < 2)
              }
              onPress={() => void submit()}
            >
              {busy ? (
                <ActivityIndicator color={ui.surface} />
              ) : (
                <>
                  <Text style={s.primaryText}>
                    {create ? "Create account" : "Let’s get moving"}
                  </Text>
                  <Feather name="arrow-up-right" size={20} color={ui.surface} />
                </>
              )}
            </Pressable>
            <Pressable
              accessibilityRole="button"
              disabled={busy}
              onPress={() => {
                setCreate(!create);
                setError("");
              }}
            >
              <Text style={s.switch}>
                {create
                  ? "Already a runner? Sign in"
                  : "New here? Create a runner account"}
              </Text>
            </Pressable>
          </View>
          <Text style={s.foot}>
            {busy
              ? "Connecting… The cloud server may take a minute to wake up."
              : "Developer runners use their assigned username and password."}
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: ui.surface },
  scroll: { padding: 24, paddingBottom: 40 },
  hero: { paddingTop: 24, paddingBottom: 30 },
  mark: {
    width: 60,
    height: 60,
    borderRadius: 20,
    backgroundColor: ui.accent,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 22,
  },
  eyebrow: {
    fontSize: 12,
    letterSpacing: 3,
    color: ui.accent,
    fontFamily: fonts.bold,
  },
  title: {
    fontSize: 36,
    lineHeight: 41,
    fontFamily: fonts.bold,
    letterSpacing: -1.4,
    color: ui.ink,
    marginVertical: 10,
  },
  subtitle: { fontSize: 15, color: ui.ink2 },
  card: { padding: 22, borderRadius: 28, backgroundColor: "#FFF", gap: 12 },
  heading: {
    fontSize: 22,
    fontFamily: fonts.bold,
    color: ui.ink,
    marginBottom: 8,
  },
  google: {
    flexDirection: "row",
    gap: 12,
    borderWidth: 1,
    borderColor: ui.line,
    borderRadius: 16,
    padding: 17,
    alignItems: "center",
    justifyContent: "center",
  },
  googleText: { fontSize: 15, fontFamily: fonts.semibold, color: ui.ink },
  divider: {
    fontSize: 10,
    letterSpacing: 1.5,
    textAlign: "center",
    color: ui.ink3,
    marginVertical: 7,
  },
  input: {
    borderRadius: 14,
    backgroundColor: ui.accentSoft,
    padding: 16,
    fontSize: 16,
    fontFamily: fonts.regular,
    color: ui.ink,
  },
  primary: {
    backgroundColor: ui.accent,
    borderRadius: 16,
    padding: 18,
    flexDirection: "row",
    gap: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: { color: ui.surface, fontSize: 16, fontFamily: fonts.bold },
  switch: {
    textAlign: "center",
    color: ui.accent,
    fontSize: 13,
    paddingTop: 10,
  },
  foot: {
    fontSize: 12,
    lineHeight: 18,
    color: ui.ink2,
    textAlign: "center",
    marginTop: 24,
  },
  error: { color: ui.danger, fontSize: 13, lineHeight: 19 },
});
