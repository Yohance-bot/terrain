import { useState } from 'react';
import { Linking, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { fonts, ui } from '@/theme';

/** Keep map credits available in one tap without covering a street with a banner. */
export function MapAttribution() {
  const [open, setOpen] = useState(false);
  return <>
    <Pressable accessibilityRole="button" accessibilityLabel="Map credits: OpenStreetMap, OpenFreeMap and Open-Meteo"
      onPress={() => setOpen(true)} style={styles.control}>
      <Text style={styles.label}>© OpenStreetMap · ⓘ</Text>
    </Pressable>
    <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
      <View style={styles.scrim}>
        <Pressable style={StyleSheet.absoluteFill} onPress={() => setOpen(false)} accessibilityLabel="Close map credits" />
        <View style={styles.sheet} accessibilityViewIsModal>
          <Text style={styles.title}>Map & weather credits</Text>
          {([
            ['© OpenStreetMap contributors', 'https://www.openstreetmap.org/copyright'],
            ['Map tiles by OpenFreeMap', 'https://openfreemap.org/'],
            ['Weather by Open-Meteo', 'https://open-meteo.com/'],
          ] as const).map(([label, url]) => <Pressable key={url} accessibilityRole="link" onPress={() => void Linking.openURL(url).catch(() => undefined)} style={styles.row}>
            <Text style={styles.link}>{label} ↗</Text>
          </Pressable>)}
          <Pressable onPress={() => setOpen(false)} accessibilityRole="button" style={styles.row}><Text style={styles.link}>Done</Text></Pressable>
        </View>
      </View>
    </Modal>
  </>;
}
const styles = StyleSheet.create({
  control: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-end' },
  label: { color: '#FFFFFF', backgroundColor: '#16221DCC', fontFamily: fonts.medium, fontSize: 10, paddingHorizontal: 7, paddingVertical: 4, borderRadius: 7 },
  scrim: { flex: 1, justifyContent: 'center', padding: 24, backgroundColor: ui.scrim },
  sheet: { backgroundColor: ui.surface, borderRadius: 24, padding: 22 },
  title: { fontFamily: fonts.bold, fontSize: 20, color: ui.ink, marginBottom: 12 },
  row: { minHeight: 48, justifyContent: 'center' },
  link: { fontFamily: fonts.semibold, fontSize: 14, color: ui.accent },
});
