import Constants from 'expo-constants';
import { router, useFocusEffect } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { ShoeIcon } from '@/components/icons';
import { Button, Card, EmptyState, ErrorState, Loading, NavHeader, Row, Screen, SectionLabel, Segmented, Toggle } from '@/components/ui';
import { useHudPreferences } from '@/features/hud/usePresentation';
import { setDevRunnerId } from '@/lib/device';
import {
  getCaptureColorIndex,
  getNotificationsEnabled,
  getUnits,
  setCaptureColorIndex,
  setNotificationsEnabled,
  setUnits,
  type UnitPreference,
} from '@/lib/preferences';
import {
  fetchAccount,
  fetchAthleteSettings,
  fetchCredentials,
  requestAccountDeletion,
  saveAthleteSettings,
  signOutAccount,
  updateAccount,
  updateCredentials,
  updateHandle,
} from '@/services/api/client';
import type { AccountSummary } from '@/services/api/types';
import { CAPTURE_COLOR_PALETTE } from '@/theme/colors';
import { fonts, typeScale, ui } from '@/theme';

function Field({
  label,
  value,
  onChange,
  placeholder,
  secure,
  keyboard,
  last,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  secure?: boolean;
  keyboard?: 'default' | 'decimal-pad';
  last?: boolean;
}) {
  return (
    <View style={[styles.field, !last && styles.divider]}>
      <Text style={typeScale.rowTitle}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={ui.ink3}
        secureTextEntry={secure}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType={keyboard ?? 'default'}
        style={styles.fieldInput}
        accessibilityLabel={label}
      />
    </View>
  );
}

export default function SettingsScreen() {
  const units = useHudPreferences((s) => s.units);
  const economy = useHudPreferences((s) => s.economy);
  const routeDisplay = useHudPreferences((s) => s.routeDisplay);
  const playerMarker = useHudPreferences((s) => s.playerMarker);
  const weather = useHudPreferences((s) => s.weather);
  const [notifications, setNotifications] = useState(true);
  const [captureColor, setCaptureColor] = useState(0);
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [name, setName] = useState('');
  const [handle, setHandle] = useState('');
  const [weight, setWeight] = useState('');
  const [username, setUsername] = useState('');
  const [hasPassword, setHasPassword] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [saving, setSaving] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [savedWeight, setSavedWeight] = useState('');
  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const [unitsValue, notify, color, next] = await Promise.all([getUnits(), getNotificationsEnabled(), getCaptureColorIndex(), fetchAccount()]);
      useHudPreferences.setState({ units: unitsValue });
      setNotifications(notify); setCaptureColor(color); setAccount(next ?? null);
      if (next) {
        const [athlete, credentials] = await Promise.all([fetchAthleteSettings(), fetchCredentials()]);
        setName(next.display_name); setHandle(next.handle ?? '');
        const nextWeight = athlete.weight_kg === null ? '' : String(athlete.weight_kg);
        setWeight(nextWeight); setSavedWeight(nextWeight);
        setUsername(credentials.username ?? ''); setHasPassword(credentials.has_password);
      }
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const chooseUnits = (value: UnitPreference) => {
    useHudPreferences.setState({ units: value });
    void setUnits(value);
  };

  const attempt = async (key: string, work: () => Promise<unknown>, done: string) => {
    if (saving) return;
    setSaving(key);
    try {
      await work();
      Alert.alert(done);
    } catch (error) {
      const detail = error instanceof Error ? error.message.match(/"detail":"([^"]+)"/)?.[1] ?? error.message : 'Try again';
      Alert.alert('Could not save', detail);
    } finally {
      setSaving(null);
    }
  };

  const saveProfile = () =>
    attempt(
      'profile',
      async () => {
        if (!account) return;
        if (name.trim() && name.trim() !== account.display_name) setAccount(await updateAccount(name.trim()));
        if (handle.trim() && handle.trim() !== account.handle) {
          const updated = await updateHandle(handle.trim());
          setHandle(updated.handle);
          setAccount(current => current ? { ...current, handle: updated.handle } : current);
        }
      },
      'Profile saved',
    );

  const saveWeight = () => {
    if (weight === savedWeight) return;
    const trimmed = weight.trim().replace(',', '.');
    const value = trimmed === '' ? null : Number(trimmed);
    if (value !== null && (!Number.isFinite(value) || value < 25 || value > 300)) {
      Alert.alert('Enter a weight between 25 and 300 kg');
      return;
    }
    void attempt('weight', async () => { await saveAthleteSettings({ weight_kg: value }); setSavedWeight(weight); }, value === null ? 'Weight removed' : 'Weight saved');
  };

  const saveSignIn = () =>
    attempt(
      'credentials',
      async () => {
        await updateCredentials(username, currentPassword, newPassword);
        setHasPassword(true);
        setCurrentPassword('');
        setNewPassword('');
      },
      'Sign-in details saved',
    );

  const signOut = () =>
    Alert.alert('Sign out?', 'Your account keeps its runs and territory history.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sign out',
        style: 'destructive',
        onPress: () =>
          void signOutAccount()
            .then(() => {
              setDevRunnerId(null);
              router.replace('/sign-in');
            })
            .catch(() => router.replace('/sign-in')),
      },
    ]);

  const deleteRequest = () =>
    Alert.alert('Request account deletion?', 'This logs a request for us to process. It does not erase your territory history immediately.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Request deletion',
        style: 'destructive',
        onPress: () => void attempt('deletion', requestAccountDeletion, 'Account deletion request received'),
      },
    ]);

  return (
    <Screen>
      <StatusBar style="dark" />
      <NavHeader title="Settings" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <SectionLabel>Running</SectionLabel>
        <Card>
          <Row title="Units" trailing={<View style={styles.compact}><Segmented compact value={units} onChange={chooseUnits} options={[{ value: 'km', label: 'km' }, { value: 'mi', label: 'mi' }]} /></View>} />
          <View style={[styles.stack, styles.divider]}>
            <Text style={typeScale.rowTitle}>Run trail</Text>
            <Segmented
              compact
              value={routeDisplay}
              onChange={(value) => useHudPreferences.getState().setRouteDisplay(value)}
              options={[{ value: 'streets', label: 'Light up streets' }, { value: 'gps', label: 'GPS trail' }]}
            />
          </View>
          <Row
            title="Run cues & haptics"
            subtitle="Splits and territory feedback"
            trailing={
              <Toggle
                label="Run cues and haptics"
                value={notifications}
                onChange={(value) => {
                  setNotifications(value);
                  void setNotificationsEnabled(value);
                  useHudPreferences.setState({ haptics: value });
                }}
              />
            }
          />
          <Row
            title="Battery saver"
            subtitle="Less glow, slower map updates, calm camera"
            trailing={<Toggle label="Battery saver" value={economy} onChange={useHudPreferences.getState().setEconomy} />}
            last
          />
        </Card>

        <SectionLabel>Map</SectionLabel>
        <Card>
          <View style={[styles.stack, styles.divider]}>
            <Text style={typeScale.rowTitle}>You on the map</Text>
            <Segmented
              compact
              value={playerMarker}
              onChange={(value) => useHudPreferences.getState().setPlayerMarker(value)}
              options={[{ value: 'avatar', label: '3D runner' }, { value: 'classic', label: 'Classic marker' }]}
            />
          </View>
          <Row
            title="Weather lighting"
            subtitle="Approximate location with Open-Meteo, every 15 minutes"
            trailing={<Toggle label="Weather lighting" value={weather} onChange={useHudPreferences.getState().setWeather} />}
          />
          <View style={styles.stack}>
            <Text style={typeScale.rowTitle}>Capture colour</Text>
            <View style={styles.swatches}>
              {CAPTURE_COLOR_PALETTE.map((hex, index) => (
                <Pressable
                  key={hex}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: captureColor === index }}
                  accessibilityLabel={`Capture colour ${index + 1}`}
                  onPress={() => {
                    setCaptureColor(index);
                    void setCaptureColorIndex(index);
                  }}
                  style={[styles.swatchRing, captureColor === index && styles.swatchSelected]}
                >
                  <View style={[styles.swatch, { backgroundColor: hex }]} />
                </Pressable>
              ))}
            </View>
          </View>
        </Card>

        {loading ? <Loading /> : loadFailed ? <ErrorState message="Account settings could not be loaded. Your existing values have not been changed." onRetry={() => void load()} /> : !account ? <EmptyState title="Sign in for account settings" action={<Button label="Sign in" onPress={() => router.push('/sign-in')} />} /> : null}
        {account && !loading && !loadFailed && (
          <>
            <SectionLabel>Athlete</SectionLabel>
            <Card>
              <View style={[styles.inline, styles.divider]}>
                <View style={styles.inlineText}>
                  <Text style={typeScale.rowTitle}>Weight</Text>
                  <Text style={typeScale.meta}>Only used to estimate calories</Text>
                </View>
                <TextInput
                  value={weight}
                  onChangeText={setWeight}

                  placeholder="kg"
                  placeholderTextColor={ui.ink3}
                  keyboardType="decimal-pad"
                  style={styles.weight}
                  accessibilityLabel="Weight in kilograms"
                />
              </View>
              <Button label="Save weight" variant="text" onPress={saveWeight} disabled={saving !== null || weight === savedWeight} busy={saving === 'weight'} />
              <Row title="Shoes" leading={<ShoeIcon size={22} />} onPress={() => router.push('/shoes')} last />
            </Card>

            <SectionLabel>Profile</SectionLabel>
            <Card>
              <Field label="Name" value={name} onChange={setName} placeholder="Display name" />
              <Field label="Handle" value={handle} onChange={setHandle} placeholder="handle" last />
            </Card>
            <Button label="Save profile" onPress={() => void saveProfile()} busy={saving === 'profile'} disabled={saving !== null || !name.trim() || !handle.trim()} style={styles.save} />

            <SectionLabel>Sign-in details</SectionLabel>
            <Card>
              <Field label="Username" value={username} onChange={setUsername} placeholder="Username" />
              {hasPassword && <Field label="Current password" value={currentPassword} onChange={setCurrentPassword} secure />}
              <Field label="New password" value={newPassword} onChange={setNewPassword} placeholder="12+ characters" secure last />
            </Card>
            <Button label="Update sign-in details" variant="secondary" onPress={() => void saveSignIn()} busy={saving === 'credentials'} disabled={saving !== null || !username.trim() || (!hasPassword && newPassword.length < 12) || (hasPassword && !currentPassword)} style={styles.save} />

            <SectionLabel>Account</SectionLabel>
            <Card>
              <Row title="Sign out" onPress={signOut} />
              <Row title="Request account deletion" destructive onPress={deleteRequest} last />
            </Card>
          </>
        )}

        <Text style={[typeScale.small, styles.footer]}>
          TerraRun {Constants.expoConfig?.version ?? '1.0.0'}
          {'\n'}© OpenStreetMap contributors · Weather: Open-Meteo
        </Text>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 48 },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: ui.line },
  compact: { width: 110 },
  stack: { paddingHorizontal: 16, paddingVertical: 12, gap: 10 },
  swatches: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  swatchRing: { width: 36, height: 36, borderRadius: 18, borderWidth: 2, borderColor: 'transparent', alignItems: 'center', justifyContent: 'center' },
  swatchSelected: { borderColor: ui.ink },
  swatch: { width: 26, height: 26, borderRadius: 13 },
  inline: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12, gap: 12 },
  inlineText: { flex: 1, gap: 1 },
  weight: { width: 72, textAlign: 'right', fontFamily: fonts.semibold, fontSize: 17, color: ui.ink, paddingVertical: 6 },
  field: { paddingHorizontal: 16, paddingVertical: 10, gap: 4 },
  fieldInput: { fontFamily: fonts.regular, fontSize: 16, color: ui.ink, paddingVertical: 4 },
  save: { marginHorizontal: 16, marginTop: 12 },
  footer: { textAlign: 'center', lineHeight: 18, paddingTop: 28, paddingHorizontal: 20 },
});
