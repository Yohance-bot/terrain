import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { fonts, ui } from '@/theme';

import { FriendsIcon, MapIcon, ProfileIcon } from './icons';

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
export function TabBar({ active, badge }: { active: TabKey; badge?: boolean }) {
  const insets = useSafeAreaInsets();
  const go = (tab: (typeof TABS)[number]) => {
    if (tab.key === active) return;
    if (tab.key === 'map') router.navigate('/');
    else if (active === 'map') router.push(tab.path);
    else router.replace(tab.path);
  };
  return (
    <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, 8) }]} accessibilityRole="tabbar">
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
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    backgroundColor: ui.surface,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: ui.line,
    paddingTop: 8,
  },
  tab: { flex: 1, alignItems: 'center', gap: 3 },
  icon: { width: 28, height: 26, alignItems: 'center', justifyContent: 'center' },
  iconIdle: { opacity: 0.5 },
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
