import { Pressable, StyleSheet, Text, View } from 'react-native';

import { formatClock, formatDistance, formatPace, paceSeconds, runTitle, weekdayShort, type Units } from '@/lib/format';
import type { RunSummary } from '@/services/api/types';
import { fonts, typeScale, ui } from '@/theme';

import { RecordIcon } from './icons';

/** One run in a list: the day, what it was called, the three numbers that matter. */
export function RunRow({
  run,
  units,
  onPress,
  last,
  showNote,
}: {
  run: RunSummary;
  units: Units;
  onPress?: () => void;
  last?: boolean;
  showNote?: boolean;
}) {
  const started = new Date(run.started_at);
  const records = run.personal_records.length;
  const body = (
    <View style={[styles.row, !last && styles.divider]}>
      <View style={styles.day}>
        <Text style={styles.weekday}>{weekdayShort(started).toUpperCase()}</Text>
        <Text style={styles.date}>{started.getDate()}</Text>
      </View>
      <View style={styles.body}>
        <View style={styles.titleLine}>
          <Text style={[typeScale.rowTitle, styles.title]} numberOfLines={1}>{run.title ?? runTitle(started)}</Text>
          {records > 0 ? (
            <View style={styles.tag}>
              <RecordIcon size={14} color={ui.accent} strokeWidth={2} />
              <Text style={styles.tagText}>{records === 1 ? 'PR' : `${records} PRs`}</Text>
            </View>
          ) : run.captures > 0 ? (
            <Text style={styles.tagText}>{run.captures} captured</Text>
          ) : null}
        </View>
        <Text style={[typeScale.meta, styles.numbers]}>
          {formatDistance(run.distance_m, units)} · {formatPace(paceSeconds(run.distance_m, run.moving_s, units), units)} · {formatClock(run.moving_s)}
        </Text>
        {showNote && run.note ? <Text style={[typeScale.body, styles.note]} numberOfLines={3}>{run.note}</Text> : null}
      </View>
    </View>
  );
  if (!onPress) return body;
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => pressed && { opacity: 0.6 }}>
      {body}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: 14, paddingVertical: 12, paddingHorizontal: 16 },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: ui.line },
  day: { width: 34, alignItems: 'center' },
  weekday: { fontFamily: fonts.semibold, fontSize: 11, color: ui.ink3 },
  date: { fontFamily: fonts.semibold, fontSize: 20, lineHeight: 23, color: ui.ink },
  body: { flex: 1, gap: 2 },
  titleLine: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  title: { flex: 1 },
  tag: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  tagText: { fontFamily: fonts.semibold, fontSize: 13, color: ui.accent },
  numbers: { fontVariant: ['tabular-nums'] },
  note: { paddingTop: 4 },
});
