import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { fonts, ui } from '@/theme';
export type SheetAction = { label: string; onPress: () => void; destructive?: boolean };
/** Android native alerts truncate actions beyond three buttons. */
export function ActionSheet({ title, actions, onClose }: { title: string; actions: SheetAction[] | null; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  return <Modal transparent animationType="slide" visible={actions !== null} onRequestClose={onClose}>
    <View style={styles.backdrop}>
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Dismiss options" />
      <View style={[styles.sheet, { paddingBottom: Math.max(16, insets.bottom) }]} accessibilityViewIsModal>
        <Text style={styles.title}>{title}</Text>
        <ScrollView>{actions?.map((action, index) => <Pressable key={`${action.label}-${index}`} accessibilityRole="button" onPress={() => { onClose(); action.onPress(); }} style={styles.action}>
          <Text style={[styles.label, action.destructive && { color: '#B42318' }]}>{action.label}</Text>
        </Pressable>)}</ScrollView>
        <Pressable onPress={onClose} accessibilityRole="button" style={styles.action}><Text style={styles.label}>Cancel</Text></Pressable>
      </View>
    </View>
  </Modal>;
}
const styles = StyleSheet.create({ backdrop: { flex: 1, backgroundColor: '#00000066', justifyContent: 'flex-end' }, sheet: { backgroundColor: ui.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, maxHeight: '75%' }, title: { fontFamily: fonts.bold, fontSize: 21, color: ui.ink, marginBottom: 16 }, action: { minHeight: 52, justifyContent: 'center', paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: ui.line }, label: { fontFamily: fonts.regular, fontSize: 16, color: ui.ink } });
