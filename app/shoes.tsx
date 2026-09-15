import { ActionSheet, type SheetAction } from '@/components/ActionSheet';
import { router, useFocusEffect } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useState } from 'react';
import { Alert, ScrollView, StyleSheet, Text, TextInput } from 'react-native';

import { ShoeIcon } from '@/components/icons';
import { Button, Card, EmptyState, ErrorState, Loading, NavHeader, Row, Screen, SectionLabel } from '@/components/ui';
import { useHudPreferences } from '@/features/hud/usePresentation';
import { formatDistance } from '@/lib/format';
import { createShoe, deleteShoe, fetchShoes, updateShoe } from '@/services/api/client';
import type { ShoeRecord } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';

export default function ShoesScreen() {
  const units = useHudPreferences((s) => s.units);
  const [shoes, setShoes] = useState<ShoeRecord[] | null>(null);
  const [name, setName] = useState('');
  const [failed, setFailed] = useState(false);
  const [adding, setAdding] = useState(false);
  const [sheet, setSheet] = useState<{ title: string; actions: SheetAction[] } | null>(null);

  const load = useCallback(async () => {
    try {
      setShoes(await fetchShoes());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const run = (work: () => Promise<unknown>) => {
    void work()
      .then(load)
      .catch(() => Alert.alert('Could not update your shoes', 'Check your connection and try again.'));
  };

  const add = async () => {
    if (!name.trim() || adding) return;
    setAdding(true);
    try {
      await createShoe(name.trim());
      setName('');
      await load();
    } catch {
      Alert.alert('Could not add those shoes');
    } finally {
      setAdding(false);
    }
  };

  const manage = (shoe: ShoeRecord) => setSheet({ title: shoe.name, actions: [
    ...(!shoe.is_default && !shoe.retired ? [{ label: 'Wear by default', onPress: () => run(() => updateShoe(shoe.id, { is_default: true })) }] : []),
    { label: shoe.retired ? 'Bring back' : 'Retire', onPress: () => run(() => updateShoe(shoe.id, { retired: !shoe.retired })) },
    { label: 'Delete', destructive: true, onPress: () => run(() => deleteShoe(shoe.id)) },
  ] });

  const active = (shoes ?? []).filter((shoe) => !shoe.retired);
  const retired = (shoes ?? []).filter((shoe) => shoe.retired);

  const row = (shoe: ShoeRecord, last: boolean) => (
    <Row
      key={shoe.id}
      title={shoe.name}
      subtitle={`${formatDistance(shoe.distance_m, units)} · ${shoe.runs} ${shoe.runs === 1 ? 'run' : 'runs'}`}
      leading={<ShoeIcon size={24} />}
      trailing={shoe.is_default ? <Text style={styles.default}>Default</Text> : undefined}
      onPress={() => manage(shoe)}
      last={last}
    />
  );

  return (
    <Screen>
      <ActionSheet title={sheet?.title ?? "Shoes"} actions={sheet?.actions ?? null} onClose={() => setSheet(null)} />
      <StatusBar style="dark" />
      <NavHeader title="Shoes" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Card style={styles.add}>
          <TextInput
            value={name}
            onChangeText={setName}
            onSubmitEditing={() => void add()}
            placeholder="Add a pair, e.g. Daily trainers"
            placeholderTextColor={ui.ink3}
            maxLength={48}
            returnKeyType="done"
            style={styles.input}
            accessibilityLabel="Shoe name"
          />
          <Button label="Add" onPress={() => void add()} busy={adding} disabled={!name.trim()} style={styles.addButton} />
        </Card>
        <Text style={[typeScale.meta, styles.hint]}>
          New runs wear your default pair. Change a run’s shoes from its details.
        </Text>

        {failed ? <ErrorState onRetry={() => void load()} /> : shoes === null ? (
          <Loading />
        ) : shoes.length === 0 ? (
          <EmptyState title="No shoes yet" body="Each pair keeps count of the distance it has carried you." />
        ) : (
          <>
            {active.length > 0 && (
              <>
                <SectionLabel>In rotation</SectionLabel>
                <Card>{active.map((shoe, index) => row(shoe, index === active.length - 1))}</Card>
              </>
            )}
            {retired.length > 0 && (
              <>
                <SectionLabel>Retired</SectionLabel>
                <Card>{retired.map((shoe, index) => row(shoe, index === retired.length - 1))}</Card>
              </>
            )}
          </>
        )}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 40 },
  add: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 8, paddingLeft: 16 },
  input: { flex: 1, fontFamily: fonts.regular, fontSize: 16, color: ui.ink, paddingVertical: 10 },
  addButton: { height: 42, paddingHorizontal: 16 },
  hint: { paddingHorizontal: 20, paddingTop: 10 },
  default: { fontFamily: fonts.semibold, fontSize: 13, color: ui.accent },
});
