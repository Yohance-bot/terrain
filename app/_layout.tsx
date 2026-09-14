import {
  Barlow_400Regular,
  Barlow_500Medium,
  Barlow_600SemiBold,
  Barlow_700Bold,
  useFonts,
} from '@expo-google-fonts/barlow';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import 'react-native-reanimated';

import { colors, ui } from '@/theme';

export const unstable_settings = {
  anchor: 'index',
};

// Barlow is bundled, so this resolves in a frame or two; holding the splash
// avoids one frame of system type before the app's own.
void SplashScreen.preventAutoHideAsync().catch(() => undefined);

export default function RootLayout() {
  const [loaded, error] = useFonts({ Barlow_400Regular, Barlow_500Medium, Barlow_600SemiBold, Barlow_700Bold });

  useEffect(() => {
    if (loaded || error) void SplashScreen.hideAsync().catch(() => undefined);
  }, [loaded, error]);

  if (!loaded && !error) return null;

  return (
    <SafeAreaProvider>
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        {/* Friends and Profile behave as tabs over the map, not as pushed pages. */}
        <Stack.Screen name="friends" options={{ animation: 'none' }} />
        <Stack.Screen name="profile" options={{ animation: 'none' }} />
        <Stack.Screen
          name="goal"
          options={{
            presentation: 'formSheet',
            sheetAllowedDetents: [0.78],
            sheetGrabberVisible: true,
            contentStyle: { backgroundColor: ui.surface },
          }}
        />
      </Stack>
      {/* Screens set their own status bar; this is the fallback. */}
      <StatusBar style="dark" />
    </SafeAreaProvider>
  );
}
