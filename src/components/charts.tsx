import { useState } from 'react';
import { StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native';
import Svg, { Line, Path, Text as SvgText } from 'react-native-svg';

import { fonts, typeScale, ui } from '@/theme';

/**
 * Charts, drawn to one spec: thin marks, 4px rounded caps on a square baseline,
 * hairline gridlines, one series in the athlete's teal, the current period
 * emphasised and labelled, everything else a lighter step of the same hue.
 */

const AXIS = { fontFamily: fonts.medium, fontSize: 11, fill: ui.ink3 } as const;

function useWidth(initial = 0) {
  const [width, setWidth] = useState(initial);
  const onLayout = (event: LayoutChangeEvent) => setWidth(Math.round(event.nativeEvent.layout.width));
  return { width, onLayout };
}

/** Ticks at round values, three or four of them, covering the largest value. */
export function niceTicks(max: number): number[] {
  if (max <= 0) return [0, 1];
  const steps = [0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000];
  const step = steps.find((candidate) => max / candidate <= 3) ?? Math.ceil(max / 3);
  const top = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let value = 0; value <= top + 1e-9; value += step) ticks.push(Number(value.toFixed(2)));
  return ticks;
}

function formatTick(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function roundedColumn(x: number, top: number, width: number, base: number) {
  const r = Math.min(4, base - top, width / 2);
  return `M${x} ${base}V${top + r}Q${x} ${top} ${x + r} ${top}H${x + width - r}Q${x + width} ${top} ${x + width} ${top + r}V${base}Z`;
}

export type Column = { value: number; label?: string };

/** Distance per week (or month): one column per period, the last emphasised. */
export function ColumnChart({ columns, height = 164, valueLabel }: { columns: Column[]; height?: number; valueLabel?: (value: number) => string }) {
  const { width, onLayout } = useWidth();
  const axisWidth = 28;
  const plotTop = 16;
  const base = height - 26;
  const ticks = niceTicks(Math.max(...columns.map((column) => column.value), 0));
  const max = ticks[ticks.length - 1] || 1;
  const plotWidth = Math.max(0, width - axisWidth);
  const band = columns.length ? plotWidth / columns.length : 0;
  const barWidth = Math.min(14, band * 0.6);
  const y = (value: number) => base - (value / max) * (base - plotTop);
  const last = columns.length - 1;
  return (
    <View onLayout={onLayout} style={{ height }} accessibilityRole="image" accessibilityLabel={columns.map((c) => `${c.label ?? ''} ${valueLabel ? valueLabel(c.value) : c.value}`).join(', ')}>
      {width > 0 && (
        <Svg width={width} height={height}>
          {ticks.map((tick) => (
            <Line key={`g${tick}`} x1={axisWidth} x2={width} y1={Math.round(y(tick)) + 0.5} y2={Math.round(y(tick)) + 0.5} stroke={ui.line} strokeWidth={1} />
          ))}
          {ticks.map((tick) => (
            <SvgText key={`t${tick}`} x={axisWidth - 8} y={y(tick) + 4} textAnchor="end" {...AXIS}>{formatTick(tick)}</SvgText>
          ))}
          {columns.map((column, index) => {
            if (column.value <= 0) return null;
            const x = axisWidth + index * band + (band - barWidth) / 2;
            const top = y(column.value);
            return <Path key={`b${index}`} d={roundedColumn(x, top, barWidth, base)} fill={index === last ? ui.chartCurrent : ui.chartPast} />;
          })}
          {columns[last] && columns[last].value > 0 && (
            <SvgText
              x={axisWidth + last * band + band / 2}
              y={y(columns[last].value) - 6}
              textAnchor="middle"
              fontFamily={fonts.semibold}
              fontSize={12}
              fill={ui.ink}
            >
              {valueLabel ? valueLabel(columns[last].value) : formatTick(columns[last].value)}
            </SvgText>
          )}
          {columns.map((column, index) =>
            column.label ? (
              <SvgText
                key={`l${index}`}
                x={index === last ? width : axisWidth + index * band + band / 2}
                y={height - 6}
                textAnchor={index === last ? 'end' : 'middle'}
                {...AXIS}
              >
                {column.label}
              </SvgText>
            ) : null,
          )}
        </Svg>
      )}
    </View>
  );
}

/**
 * A series along the run's distance: pace (faster drawn higher) or elevation
 * (with a faint wash under the line).
 */
export function LineChart({
  points,
  height = 140,
  invert,
  area,
  yLabel,
  xLabel,
}: {
  points: [number, number][];
  height?: number;
  invert?: boolean;
  area?: boolean;
  yLabel: (value: number) => string;
  xLabel: (value: number) => string;
}) {
  const { width, onLayout } = useWidth();
  if (points.length < 2) return null;
  const axisWidth = 44;
  const top = 10;
  const base = height - 24;
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const pad = Math.max((maxY - minY) * 0.12, invert ? 5 : 2);
  const lo = minY - pad;
  const hi = maxY + pad;
  const xMax = xs[xs.length - 1] || 1;
  const plotWidth = Math.max(1, width - axisWidth);
  const px = (x: number) => axisWidth + (x / xMax) * plotWidth;
  const py = (value: number) => {
    const t = (value - lo) / (hi - lo || 1);
    return invert ? top + t * (base - top) : base - t * (base - top);
  };
  const line = points.map(([x, value], index) => `${index ? 'L' : 'M'}${px(x).toFixed(1)} ${py(value).toFixed(1)}`).join('');
  const wash = `${line}L${px(xMax).toFixed(1)} ${base}L${px(xs[0] ?? 0).toFixed(1)} ${base}Z`;
  const guides = [lo + (hi - lo) * 0.25, lo + (hi - lo) * 0.75];
  return (
    <View onLayout={onLayout} style={{ height }}>
      {width > 0 && (
        <Svg width={width} height={height}>
          {guides.map((value) => (
            <Line key={`g${value}`} x1={axisWidth} x2={width} y1={Math.round(py(value)) + 0.5} y2={Math.round(py(value)) + 0.5} stroke={ui.line} strokeWidth={1} />
          ))}
          {guides.map((value) => (
            <SvgText key={`t${value}`} x={axisWidth - 8} y={py(value) + 4} textAnchor="end" {...AXIS}>{yLabel(value)}</SvgText>
          ))}
          {area && <Path d={wash} fill={ui.chartCurrent} fillOpacity={0.12} />}
          <Path d={line} stroke={ui.chartCurrent} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" fill="none" />
          <SvgText x={axisWidth} y={height - 6} textAnchor="start" {...AXIS}>{xLabel(0)}</SvgText>
          <SvgText x={width} y={height - 6} textAnchor="end" {...AXIS}>{xLabel(xMax)}</SvgText>
        </Svg>
      )}
    </View>
  );
}

/** Progress toward a limit: the fill is the value, the track a lighter step of it. */
export function Meter({ value, max, height = 10 }: { value: number; max: number; height?: number }) {
  const fraction = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  return (
    <View
      style={[styles.track, { height, borderRadius: height / 2 }]}
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: Math.round(fraction * 100) }}
    >
      <View style={{ width: `${fraction * 100}%`, height, borderRadius: height / 2, backgroundColor: ui.accent }} />
    </View>
  );
}

/** Twelve weeks as cells: the live streak in teal, earlier running weeks lighter, misses empty. */
export function StreakCells({ weeks, streakWeeks }: { weeks: boolean[]; streakWeeks: number }) {
  const streakStart = weeks.length - streakWeeks - (weeks[weeks.length - 1] ? 0 : 1);
  return (
    <View style={styles.cells}>
      {weeks.map((ran, index) => {
        const inStreak = ran && index >= streakStart;
        return (
          <View
            key={index}
            style={[
              styles.cell,
              inStreak ? { backgroundColor: ui.chartCurrent } : ran ? { backgroundColor: ui.chartPast } : styles.cellEmpty,
            ]}
          />
        );
      })}
    </View>
  );
}

/** A month as a calendar, each running day shaded by how far it went. */
export function MonthHeatmap({
  year,
  month,
  distances,
  today,
}: {
  year: number;
  month: number;
  distances: Map<number, number>;
  today: Date;
}) {
  const first = new Date(year, month, 1);
  const days = new Date(year, month + 1, 0).getDate();
  const lead = (first.getDay() + 6) % 7;
  const max = Math.max(0, ...distances.values());
  const cells: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)];
  while (cells.length % 7) cells.push(null);
  const isToday = (day: number) => today.getFullYear() === year && today.getMonth() === month && today.getDate() === day;
  const isFuture = (day: number) => new Date(year, month, day) > today;
  const shade = (distance: number) => {
    const t = max > 0 ? distance / max : 0;
    return t > 0.66 ? { bg: ui.accent, fg: ui.surface } : t > 0.33 ? { bg: ui.chartCurrent, fg: ui.surface } : { bg: ui.chartPast, fg: ui.ink };
  };
  return (
    <View style={{ gap: 6 }}>
      <View style={styles.week}>
        {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((letter, index) => (
          <Text key={index} style={[typeScale.small, styles.weekday]}>{letter}</Text>
        ))}
      </View>
      {Array.from({ length: cells.length / 7 }, (_, row) => (
        <View key={row} style={styles.week}>
          {cells.slice(row * 7, row * 7 + 7).map((day, index) => {
            if (day === null) return <View key={index} style={styles.day} />;
            const distance = distances.get(day) ?? 0;
            const tone = distance > 0 ? shade(distance) : null;
            return (
              <View
                key={index}
                style={[
                  styles.day,
                  tone ? { backgroundColor: tone.bg } : isFuture(day) ? styles.dayFuture : styles.dayRest,
                  isToday(day) && styles.dayToday,
                ]}
              >
                <Text style={[styles.dayNumber, { color: tone ? tone.fg : isFuture(day) ? ui.ink3 : ui.ink2 }]}>{day}</Text>
              </View>
            );
          })}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  track: { backgroundColor: ui.accentSoft, overflow: 'hidden' },
  cells: { flexDirection: 'row', gap: 4 },
  cell: { flex: 1, height: 22, borderRadius: 4 },
  cellEmpty: { borderWidth: 1.5, borderColor: ui.line },
  week: { flexDirection: 'row', gap: 6 },
  weekday: { flex: 1, textAlign: 'center' },
  day: { flex: 1, height: 38, borderRadius: 8, paddingHorizontal: 6, paddingTop: 4 },
  dayRest: { backgroundColor: '#F1F4F0' },
  dayFuture: { borderWidth: 1, borderColor: ui.line },
  dayToday: { borderWidth: 2, borderColor: ui.ink },
  dayNumber: { fontFamily: fonts.semibold, fontSize: 12 },
});
