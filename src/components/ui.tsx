import { LinearGradient } from 'expo-linear-gradient';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { fonts, typeScale, ui } from '@/theme';

import { ChevronLeftIcon, ChevronRightIcon } from './icons';

/**
 * The pieces every non-map screen is built from.
 *
 * Content sits on white cards over the mint gradient: the gradient gives the
 * screen its colour, the cards keep text on a surface where it reads cleanly.
 */

export function GradientBackground() {
  return (
    <LinearGradient
      colors={[ui.gradientTop, ui.gradientBottom]}
      locations={[0, 0.6]}
      style={StyleSheet.absoluteFill}
      pointerEvents="none"
    />
  );
}

/** A full screen over the gradient, with room left for the top inset. */
export function Screen({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <KeyboardAvoidingView style={[styles.screen, style]} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <GradientBackground />
      {children}
    </KeyboardAvoidingView>
  );
}

/** The large title a tab screen opens with. */
export function ScreenTitle({ title, right }: { title: string; right?: ReactNode }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.screenTitle, { paddingTop: insets.top + 12 }]}>
      <Text style={typeScale.screenTitle} accessibilityRole="header">{title}</Text>
      {right}
    </View>
  );
}

/** A pushed screen's bar: back, a centred title, an optional action. */
export function NavHeader({ title, onBack, right }: { title?: string; onBack: () => void; right?: ReactNode }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.navHeader, { paddingTop: insets.top + 4 }]}>
      <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={onBack} hitSlop={8} style={styles.navButton}>
        <ChevronLeftIcon size={24} color={ui.ink} />
      </Pressable>
      <Text style={[typeScale.navTitle, { flex: 1, textAlign: 'center' }]} numberOfLines={1}>{title ?? ''}</Text>
      <View style={styles.navButton}>{right}</View>
    </View>
  );
}

export function RoundButton({ onPress, label, children }: { onPress: () => void; label: string; children: ReactNode }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={6}
      style={({ pressed }) => [styles.roundButton, pressed && styles.pressed]}
    >
      {children}
    </Pressable>
  );
}

export function SectionLabel({ children, right }: { children: string; right?: ReactNode }) {
  return (
    <View style={styles.sectionLabel}>
      <Text style={typeScale.sectionLabel}>{children.toUpperCase()}</Text>
      {right}
    </View>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Row({
  title,
  subtitle,
  value,
  leading,
  trailing,
  onPress,
  last,
  destructive,
}: {
  title: string;
  subtitle?: string;
  value?: string;
  leading?: ReactNode;
  trailing?: ReactNode;
  onPress?: () => void;
  last?: boolean;
  destructive?: boolean;
}) {
  const content = (
    <View style={[styles.row, !last && styles.rowDivider]}>
      {leading}
      <View style={styles.rowText}>
        <Text style={[typeScale.rowTitle, destructive && { color: ui.danger }]} numberOfLines={2}>{title}</Text>
        {subtitle ? <Text style={typeScale.meta} numberOfLines={2}>{subtitle}</Text> : null}
      </View>
      {value ? <Text style={[typeScale.meta, styles.rowValue]} numberOfLines={1}>{value}</Text> : null}
      {trailing ?? (onPress ? <ChevronRightIcon size={16} color={ui.ink3} /> : null)}
    </View>
  );
  if (!onPress) return content;
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => pressed && styles.pressed}>
      {content}
    </Pressable>
  );
}

export function Toggle({ value, onChange, label }: { value: boolean; onChange: (value: boolean) => void; label: string }) {
  return (
    <Switch
      accessibilityLabel={label}
      value={value}
      onValueChange={onChange}
      trackColor={{ true: ui.accent, false: ui.line }}
      thumbColor={ui.surface}
      ios_backgroundColor={ui.line}
    />
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  compact,
}: {
  options: { value: T; label: string; badge?: string }[];
  value: T;
  onChange: (value: T) => void;
  compact?: boolean;
}) {
  return (
    <View style={[styles.segmented, compact && styles.segmentedCompact]} accessibilityRole="tablist">
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            onPress={() => onChange(option.value)}
            style={[styles.segment, selected && styles.segmentSelected]}
          >
            <Text style={[styles.segmentText, selected && styles.segmentTextSelected]}>{option.label}</Text>
            {option.badge ? <Text style={styles.segmentBadge}>{option.badge}</Text> : null}
          </Pressable>
        );
      })}
    </View>
  );
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  icon,
  disabled,
  busy,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'text' | 'danger';
  icon?: ReactNode;
  disabled?: boolean;
  busy?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const inactive = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: inactive, busy }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        variant === 'primary' && styles.buttonPrimary,
        variant === 'secondary' && styles.buttonSecondary,
        (variant === 'text' || variant === 'danger') && styles.buttonText,
        pressed && (variant === 'primary' ? { backgroundColor: ui.accentPressed } : styles.pressed),
        inactive && styles.disabled,
        style,
      ]}
    >
      {busy ? (
        <ActivityIndicator color={variant === 'primary' ? ui.surface : ui.accent} />
      ) : (
        <>
          {icon}
          <Text
            style={[
              styles.buttonLabel,
              variant === 'primary' && { color: ui.surface },
              variant === 'secondary' && { color: ui.ink },
              variant === 'text' && { color: ui.accent },
              variant === 'danger' && { color: ui.danger },
            ]}
          >
            {label}
          </Text>
        </>
      )}
    </Pressable>
  );
}

/** A row of headline numbers separated by hairlines. */
export function StatRow({ items }: { items: { value: string; label: string }[] }) {
  return (
    <View style={styles.statRow}>
      {items.map((item, index) => (
        <View key={item.label} style={[styles.stat, index > 0 && styles.statDivider]}>
          <Text style={typeScale.figure} numberOfLines={1} adjustsFontSizeToFit>{item.value}</Text>
          <Text style={typeScale.small}>{item.label}</Text>
        </View>
      ))}
    </View>
  );
}

export function Avatar({ name, size = 42, tone = 'soft' }: { name: string; size?: number; tone?: 'accent' | 'soft' }) {
  return (
    <View
      style={[
        styles.avatar,
        { width: size, height: size, borderRadius: size / 2 },
        tone === 'accent' ? { backgroundColor: ui.accent } : { backgroundColor: ui.accentSoft },
      ]}
    >
      <Text style={{ fontFamily: fonts.semibold, fontSize: size * 0.4, color: tone === 'accent' ? ui.surface : ui.accent }}>
        {name.trim().slice(0, 1).toUpperCase() || '?'}
      </Text>
    </View>
  );
}

/** An icon on a soft teal tile, for section leads. */
export function IconTile({ children }: { children: ReactNode }) {
  return <View style={styles.iconTile}>{children}</View>;
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <View style={styles.empty}>
      <Text style={[typeScale.rowTitle, { textAlign: 'center' }]}>{title}</Text>
      {body ? <Text style={[typeScale.meta, { textAlign: 'center' }]}>{body}</Text> : null}
      {action}
    </View>
  );
}

export function ErrorState({ message = 'Check your connection and try again.', onRetry }: { message?: string; onRetry: () => void }) {
  return <View accessibilityRole="alert"><EmptyState title="Couldn’t load this" body={message} action={<Button label="Try again" variant="secondary" onPress={onRetry} />} /></View>;
}

export function Loading() {
  return (
    <View style={styles.loading}>
      <ActivityIndicator color={ui.accent} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: ui.surface },
  screenTitle: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, paddingBottom: 12 },
  navHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 8, paddingBottom: 6 },
  navButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  roundButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: ui.surface,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: ui.ink,
    shadowOpacity: 0.08,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
  },
  sectionLabel: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', paddingHorizontal: 20, paddingTop: 22, paddingBottom: 8 },
  card: {
    marginHorizontal: 16,
    backgroundColor: ui.surface,
    borderRadius: 16,
    shadowColor: ui.ink,
    shadowOpacity: 0.05,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 2 },
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 56, paddingVertical: 10, paddingHorizontal: 16 },
  rowDivider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: ui.line },
  rowText: { flex: 1, gap: 1 },
  rowValue: { maxWidth: 160 },
  pressed: { opacity: 0.6 },
  disabled: { opacity: 0.45 },
  segmented: { flexDirection: 'row', minHeight: 44, padding: 3, borderRadius: 11, backgroundColor: ui.segment },
  segmentedCompact: { minHeight: 44, borderRadius: 9 },
  segment: { flex: 1, flexDirection: 'row', gap: 6, alignItems: 'center', justifyContent: 'center', borderRadius: 8 },
  segmentSelected: {
    backgroundColor: ui.surface,
    shadowColor: ui.ink,
    shadowOpacity: 0.08,
    shadowRadius: 2,
    shadowOffset: { width: 0, height: 1 },
  },
  segmentText: { fontFamily: fonts.medium, fontSize: 15, color: ui.ink2 },
  segmentTextSelected: { fontFamily: fonts.semibold, color: ui.ink },
  segmentBadge: { fontFamily: fonts.semibold, fontSize: 12, color: ui.accent },
  button: { minHeight: 50, paddingVertical: 12, borderRadius: 14, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18 },
  buttonPrimary: { backgroundColor: ui.accent },
  buttonSecondary: { backgroundColor: ui.surface, borderWidth: 1, borderColor: ui.line },
  buttonText: { minHeight: 44 },
  buttonLabel: { fontFamily: fonts.semibold, fontSize: 16 },
  statRow: { flexDirection: 'row' },
  stat: { flex: 1, gap: 1 },
  statDivider: { paddingLeft: 12, borderLeftWidth: StyleSheet.hairlineWidth, borderLeftColor: ui.line },
  avatar: { alignItems: 'center', justifyContent: 'center' },
  iconTile: { width: 40, height: 40, borderRadius: 12, backgroundColor: ui.accentSoft, alignItems: 'center', justifyContent: 'center' },
  empty: { alignItems: 'center', gap: 8, paddingHorizontal: 32, paddingVertical: 28 },
  loading: { paddingVertical: 48, alignItems: 'center' },
});
