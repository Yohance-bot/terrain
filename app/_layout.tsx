import { Stack, usePathname } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import 'react-native-reanimated';

import { colors } from '@/theme';

export const unstable_settings = {
  anchor: 'index',
};

export default function RootLayout() {
  const pathname = usePathname();
  return (
    <SafeAreaProvider>
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.background },
        }}
      />
      <StatusBar style={pathname === "/" ? "light" : "dark"} />
    </SafeAreaProvider>
  );
}
