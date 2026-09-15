import { router, useNavigation } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import { useReducedMotion } from 'react-native-reanimated';
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { tabAnimation, useTabMotion } from './tabMotion';
import { fonts, ui } from '@/theme';

import { FriendsIcon, MapIcon, ProfileIcon, StartIcon } from './icons';

export type TabKey = 'map' | 'friends' | 'profile';

const TABS: { key: TabKey; label: string; path: '/' | '/friends' | '/profile' }[] = [
  { key: 'map', label: 'Map', path: '/' },
  { key: 'friends', label: 'Friends', path: '/friends' },
  { key: 'profile', label: 'Profile', path: '/profile' },
];

/**
 * Map · Friends · Profile.
 *
 * The map is never unmounted: it stays at the bottom of the stack with its
 * renderers alive, Friends and Profile sit over it, and switching between those
 * two replaces one with the other instead of stacking them.
 */
export function TabBar({ active, badge, onStart, onStartOptions }: {
  active: TabKey; badge?: boolean; onStart?: () => void; onStartOptions?: () => void;
}) {
  const navigation = useNavigation();
  const reducedMotion = useReducedMotion();
  const insets = useSafeAreaInsets();
  const go = (tab: (typeof TABS)[number]) => {
    if (tab.key === active) return;
    const animation = tabAnimation(active, tab.key);
    useTabMotion.setState({ animation });
    navigation.setOptions({
      animation: reducedMotion ? 'none' : animation,
      animationDuration: 220,
      animationTypeForReplace: 'push',
    });
    requestAnimationFrame(() => {
      if (tab.key === 'map') router.navigate('/');
      else if (active === 'map') router.push(tab.path);
      else router.replace(tab.path);
    });
  };
  return (
    <View style={styles.dock}>
      {onStart && <Pressable accessibilityRole="button" accessibilityLabel="Start a run"
        accessibilityHint={onStartOptions ? 'Long press for developer run options' : undefined}
        onPress={onStart} onLongPress={onStartOptions}
        style={({ pressed }) => [styles.start, pressed && { opacity: 0.85 }]}>
        <LinearGradient colors={['#FFE878', '#FFD42A', '#F5B700']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.startFill}>
          <StartIcon size={22} color={ui.startInk} /><Text style={styles.startLabel}>Start run</Text>
        </LinearGradient>
      </Pressable>}
    {/* `tablist`, not `tabbar`: the latter is an iOS-only role, and Android does
        not warn about roles it does not know — it throws from the view manager on
        the main thread, which killed the app the moment this bar was mounted.
        `tablist` is valid on both, and is the correct pairing for the `tab` roles
        on the buttons below. `scripts/test-a11y-roles.mjs` guards the rest. */}
    <View style={[styles.bar, { paddingBottom: Platform.OS === 'ios' ? Math.max(8, insets.bottom - 16) : Math.max(insets.bottom, 6) }]} accessibilityRole="tablist">
      {TABS.map((tab) => {
        const selected = tab.key === active;
        const Icon = tab.key === 'map' ? MapIcon : tab.key === 'friends' ? FriendsIcon : ProfileIcon;
        return (
          <Pressable
            key={tab.key}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            accessibilityLabel={tab.label}
            onPress={() => go(tab)}
            style={styles.tab}
          >
            <View style={[styles.icon, !selected && styles.iconIdle]}>
              <Icon size={24} color={ui.icon} strokeWidth={selected ? 2 : 1.75} />
              {badge && tab.key === 'friends' ? <View style={styles.badge} /> : null}
            </View>
            <Text style={[styles.label, selected && styles.labelSelected]}>{tab.label}</Text>
          </Pressable>
        );
      })}
    </View>
    </View>
  );
}

const styles = StyleSheet.create({
  dock: { backgroundColor: ui.surface, borderTopLeftRadius: 26, borderTopRightRadius: 26, overflow: 'hidden' },
  start: { marginHorizontal: 18, marginTop: 12, marginBottom: 8, borderRadius: 18, overflow: 'hidden' },
  startFill: { minHeight: 50, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  startLabel: { fontFamily: fonts.bold, color: ui.startInk, fontSize: 16 },
  bar: {
    flexDirection: 'row',
    backgroundColor: ui.surface,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: ui.line,
    paddingTop: 8,
  },
  tab: { flex: 1, alignItems: 'center', gap: 3 },
  icon: { width: 28, height: 26, alignItems: 'center', justifyContent: 'center' },
  iconIdle: { opacity: 0.75 },
  badge: {
    position: 'absolute',
    top: 0,
    right: -1,
    width: 9,
    height: 9,
    borderRadius: 5,
    backgroundColor: ui.accent,
    borderWidth: 2,
    borderColor: ui.surface,
  },
  label: { fontFamily: fonts.medium, fontSize: 11, letterSpacing: 0.2, color: ui.ink3 },
  labelSelected: { fontFamily: fonts.semibold, color: ui.accent },
});
