import { useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ENABLE_SIMULATION } from '@/constants/config';
import { DEV_RUNNERS, getActiveDevRunnerId, getSelectedDevRunnerId, setDevRunnerId } from '@/lib/device';
import { fetchAccount, getCachedAccount } from '@/services/api/client';
import type { AccountSummary } from '@/services/api/types';
import { colors, fontSize, fontWeight, radius, spacing } from '@/theme';

/**
 * Play screen — the run preparation page. Users land here from the Play tab
 * to start a real or virtual run. Once a run begins, we navigate back to the
 * map screen which handles the recording state.
 */
export default function PlayScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const [account, setAccount] = useState<AccountSummary | null>(() => getCachedAccount());
  const [simulationSelected, setSimulationSelected] = useState(false);
  const [devRunnerId, setDevRunnerIdState] = useState<string>(() => getActiveDevRunnerId());
  const [busy, setBusy] = useState(() => !getCachedAccount());

  const developerMode = account?.role === 'developer';

  useEffect(() => {
    void getSelectedDevRunnerId().then((id) => {
      setDevRunnerIdState(id);
    });
  }, []);

  useEffect(() => {
    void fetchAccount()
      .then((a) => setAccount(a ?? null))
      .catch(() => undefined)
      .finally(() => setBusy(false));
  }, []);

  const onStart = useCallback(() => {
    // Navigate to map and signal it to start recording.
    // We pass query params so the map screen knows to auto-start.
    if (developerMode && simulationSelected) {
      router.replace({ pathname: '/', params: { autoStart: 'simulation', runnerId: devRunnerId } });
    } else {
      router.replace({ pathname: '/', params: { autoStart: 'real' } });
    }
  }, [developerMode, simulationSelected, devRunnerId, router]);

  if (busy) {
    return <View style={styles.centered}><ActivityIndicator color={colors.tabActive} /></View>;
  }

  return (
    <View style={[styles.container, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
      {/* Header */}
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}>
          <Text style={styles.backText}>‹ Back</Text>
        </Pressable>
        <Text style={styles.title}>Play</Text>
        <View style={{ width: 50 }} />
      </View>

      <View style={styles.body}>
        {/* Hero */}
        <View style={styles.hero}>
          <View style={styles.heroIconWrap}>
            <Text style={styles.heroIcon}>✦</Text>
          </View>
          <Text style={styles.heroTitle}>Ready to run?</Text>
          <Text style={styles.heroSub}>
            Track your run and claim territory for your team.
            {'\n'}Every metre counts towards your influence.
          </Text>
        </View>

        {/* Developer controls */}
        {developerMode && ENABLE_SIMULATION && (
          <View style={styles.devSection}>
            <Text style={styles.devLabel}>DEVELOPER TOOLS</Text>
            <Pressable
              onPress={() => setSimulationSelected((s) => !s)}
              style={[styles.simToggle, simulationSelected && styles.simToggleActive]}
            >
              <Text style={[styles.simToggleText, simulationSelected && styles.simToggleTextActive]}>
                {simulationSelected ? 'Virtual joystick: ON' : 'Enable virtual joystick'}
              </Text>
            </Pressable>

            {simulationSelected && (
              <View style={styles.runnerPicker}>
                <Text style={styles.runnerPickerLabel}>SELECT RUNNER</Text>
                <View style={styles.runnerChoices}>
                  {DEV_RUNNERS.map((runner) => (
                    <Pressable
                      key={runner.id}
                      onPress={() => {
                        setDevRunnerId(runner.id);
                        setDevRunnerIdState(runner.id);
                      }}
                      style={[styles.runnerChoice, devRunnerId === runner.id && styles.runnerChoiceActive]}
                    >
                      <Text style={[styles.runnerChoiceText, devRunnerId === runner.id && styles.runnerChoiceTextActive]}>
                        {runner.label}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            )}
          </View>
        )}
      </View>

      {/* Start button */}
      <View style={styles.footer}>
        <Pressable
          onPress={onStart}
          style={({ pressed }) => [styles.startBtn, pressed && styles.startBtnPressed]}
        >
          <Text style={styles.startBtnText}>
            {developerMode && simulationSelected ? 'START VIRTUAL RUN' : 'START RUN'}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0A0F14' },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#0A0F14' },

  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  backText: { color: colors.tabActive, fontSize: fontSize.md, fontWeight: fontWeight.semibold },
  title: { color: colors.surface, fontSize: fontSize.lg, fontWeight: fontWeight.bold },

  body: { flex: 1, paddingHorizontal: spacing.lg, justifyContent: 'center' },

  hero: { alignItems: 'center', marginBottom: spacing.xxl },
  heroIconWrap: { width: 72, height: 72, borderRadius: 36, backgroundColor: 'rgba(45, 212, 191, 0.12)', alignItems: 'center', justifyContent: 'center', marginBottom: spacing.lg },
  heroIcon: { color: colors.tabActive, fontSize: 32 },
  heroTitle: { color: colors.surface, fontSize: 28, fontWeight: fontWeight.bold, marginBottom: spacing.sm },
  heroSub: { color: '#94A3B8', fontSize: fontSize.sm, textAlign: 'center', lineHeight: 20 },

  devSection: { backgroundColor: '#111827', borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: '#1F2937' },
  devLabel: { color: '#64748B', fontSize: 10, fontWeight: fontWeight.bold, letterSpacing: 1.5, marginBottom: spacing.md },
  simToggle: { paddingVertical: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: '#1F2937', alignItems: 'center' },
  simToggleActive: { borderColor: colors.route, backgroundColor: 'rgba(0, 229, 255, 0.08)' },
  simToggleText: { color: '#94A3B8', fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  simToggleTextActive: { color: colors.route },

  runnerPicker: { marginTop: spacing.lg },
  runnerPickerLabel: { color: '#64748B', fontSize: 10, fontWeight: fontWeight.bold, letterSpacing: 1.5, marginBottom: spacing.sm },
  runnerChoices: { flexDirection: 'row', gap: spacing.sm },
  runnerChoice: { flex: 1, alignItems: 'center', paddingVertical: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: '#1F2937' },
  runnerChoiceActive: { backgroundColor: 'rgba(45, 212, 191, 0.12)', borderColor: colors.tabActive },
  runnerChoiceText: { color: '#94A3B8', fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  runnerChoiceTextActive: { color: colors.tabActive },

  footer: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  startBtn: { backgroundColor: colors.tabActive, paddingVertical: 16, borderRadius: radius.pill, alignItems: 'center' },
  startBtnPressed: { opacity: 0.7 },
  startBtnText: { color: '#042F2E', fontSize: 15, fontWeight: fontWeight.bold, letterSpacing: 1.2 },
});
