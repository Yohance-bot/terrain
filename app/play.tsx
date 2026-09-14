import { useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ENABLE_SIMULATION } from '@/constants/config';
import { DEV_RUNNERS, getActiveDevRunnerId, getSelectedDevRunnerId, setDevRunnerId } from '@/lib/device';
import { fetchAccount, getCachedAccount } from '@/services/api/client';
import type { AccountSummary } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';
import { StartIcon, MapIcon } from '@/components/icons';
import { Button, Card, EmptyState, IconTile, Loading, NavHeader, Row, Screen, Toggle } from '@/components/ui';
import { StatusBar } from 'expo-status-bar';

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

  const [failed, setFailed] = useState(false);
  const developerMode = account?.role === 'developer';

  useEffect(() => {
    void getSelectedDevRunnerId().then((id) => {
      setDevRunnerIdState(id);
    });
  }, []);

  useEffect(() => {
    void fetchAccount()
      .then((a) => setAccount(a ?? null))
      .catch(() => setFailed(true))
      .finally(() => setBusy(false));
  }, []);

  const onStart = useCallback(() => {
    // Navigate to map and signal it to start recording.
    // We pass query params so the map screen knows to auto-start.
    if (developerMode && simulationSelected) {
      router.navigate({ pathname: '/', params: { autoStart: 'simulation', runnerId: devRunnerId } });
    } else {
      router.navigate({ pathname: '/', params: { autoStart: 'real' } });
    }
  }, [developerMode, simulationSelected, devRunnerId, router]);

  return (
    <Screen>
      <StatusBar style="dark" />
      <NavHeader title="Start a run" onBack={() => router.back()} />
      {busy ? <Loading /> : (
        <ScrollView contentContainerStyle={styles.body}>
          <View style={styles.hero}>
            <IconTile><StartIcon size={28} /></IconTile>
            <Text style={styles.title}>Make this run yours.</Text>
            <Text style={styles.subtitle}>Follow your rhythm, light up your streets and see what you claimed when you finish.</Text>
          </View>
          <Card>
            <Row title="Your route, recorded" subtitle="Distance, pace and time as you move" leading={<MapIcon />} />
            <Row title="Ready when you are" subtitle="Allow location access when prompted. You can finish your run from the map." last />
          </Card>
          {failed && <EmptyState title="Account check unavailable" body="You can still record a real run. Reopen this page when connected to access developer controls." />}
          {developerMode && ENABLE_SIMULATION && (
            <Card style={styles.developer}>
              <Row title="Virtual joystick" subtitle="Simulate movement with your developer runner" trailing={<Toggle label="Virtual joystick" value={simulationSelected} onChange={setSimulationSelected} />} last />
              {simulationSelected && DEV_RUNNERS.filter((_, index) => index === (account?.developer_slot ?? 1) - 1).map((runner) => (
                <Button key={runner.id} label={runner.label} variant="secondary" onPress={() => { setDevRunnerId(runner.id); setDevRunnerIdState(runner.id); }} style={styles.runner} />
              ))}
            </Card>
          )}
        </ScrollView>
      )}
      <View style={[styles.footer, { paddingBottom: Math.max(insets.bottom, 16) }]}>
        <Button label={developerMode && simulationSelected ? 'Start virtual run' : 'Start run'} onPress={onStart} disabled={busy} icon={<StartIcon color={ui.surface} />} />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  body: { flexGrow: 1, justifyContent: 'center', paddingVertical: 24 },
  hero: { alignItems: 'center', gap: 16, paddingHorizontal: 28, paddingBottom: 28 },
  title: { fontFamily: fonts.bold, fontSize: 32, color: ui.ink, textAlign: 'center' },
  subtitle: { ...typeScale.body, color: ui.ink2, textAlign: 'center', lineHeight: 23 },
  developer: { marginTop: 20, paddingBottom: 8 },
  runner: { marginHorizontal: 16, marginBottom: 8 },
  footer: { paddingHorizontal: 20, paddingTop: 12 },
});
