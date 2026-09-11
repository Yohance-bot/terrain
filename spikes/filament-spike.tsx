import { StyleSheet, Text, View } from 'react-native';
import { Camera, DefaultLight, FilamentScene, FilamentView, Model } from 'react-native-filament';

/**
 * Throwaway native-rendering spike (see docs/ plan). Not part of the app's
 * map UI. Proves react-native-filament can load and render a real GLB asset
 * on this device/simulator before any camera-sync or occlusion work.
 */
function Scene() {
  return (
    <FilamentView style={styles.filament}>
      <Camera />
      <DefaultLight />
      <Model source={require('../assets/filament-spike/building.glb')} />
    </FilamentView>
  );
}

export default function FilamentSpikeScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.label}>Filament spike — building.glb</Text>
      <FilamentScene>
        <Scene />
      </FilamentScene>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#111' },
  label: { color: '#fff', padding: 12, fontSize: 12 },
  filament: { flex: 1 },
});
