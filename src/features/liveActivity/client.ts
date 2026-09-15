import { requireOptionalNativeModule } from 'expo-modules-core';
import { Platform } from 'react-native';
import { createRunActivityClient, type RunActivityNative } from './controller';

const native = Platform.OS === 'ios' ? requireOptionalNativeModule<RunActivityNative>('RunLiveActivity') : null;
export const runActivity = createRunActivityClient(native, error => {
  if (__DEV__) console.warn('[live-activity]', error instanceof Error ? error.message : 'Unavailable');
});
