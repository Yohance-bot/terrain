import { router, useLocalSearchParams } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { ScrollView } from 'react-native';

import { NavHeader, Screen } from '@/components/ui';
import { DuelsPanel } from '@/features/social/DuelsPanel';

/** Duels on their own, for links that arrive with an opponent already chosen. */
export default function ChallengesScreen() {
  const { opponent } = useLocalSearchParams<{ opponent?: string }>();
  return (
    <Screen>
      <StatusBar style="dark" />
      <NavHeader title="Duels" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ paddingBottom: 48 }} keyboardShouldPersistTaps="handled">
        <DuelsPanel initialOpponent={opponent ?? null} />
      </ScrollView>
    </Screen>
  );
}
