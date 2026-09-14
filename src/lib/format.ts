/**
 * How the athlete reads numbers: their units, their clock, their language.
 *
 * The server speaks metres and seconds only; every conversion happens here so a
 * pace in the log and a pace on the profile can never disagree.
 */

export type Units = 'km' | 'mi';

export const METRES_PER_MILE = 1609.344;
const FEET_PER_METRE = 3.28084;

export function unitLabel(units: Units): string {
  return units === 'mi' ? 'mi' : 'km';
}

export function metresPerUnit(units: Units): number {
  return units === 'mi' ? METRES_PER_MILE : 1000;
}

/** "5.20" — two decimals under 10, one under 100, none beyond. */
export function distanceNumber(metres: number, units: Units): string {
  const value = metres / metresPerUnit(units);
  const digits = value < 10 ? 2 : value < 100 ? 1 : 0;
  return value.toFixed(digits);
}

export function formatDistance(metres: number, units: Units): string {
  return `${distanceNumber(metres, units)} ${unitLabel(units)}`;
}

/** Seconds per km or mile, or null when there is nothing to divide. */
export function paceSeconds(metres: number, movingSeconds: number, units: Units): number | null {
  if (metres <= 0 || movingSeconds <= 0) return null;
  return movingSeconds / (metres / metresPerUnit(units));
}

export function formatPaceValue(secondsPerUnit: number | null): string {
  if (secondsPerUnit === null || !Number.isFinite(secondsPerUnit)) return '–:––';
  const rounded = Math.round(secondsPerUnit);
  const minutes = Math.floor(rounded / 60);
  return `${minutes}:${String(rounded % 60).padStart(2, '0')}`;
}

export function formatPace(secondsPerUnit: number | null, units: Units): string {
  return `${formatPaceValue(secondsPerUnit)} /${unitLabel(units)}`;
}

/** A stopwatch reading: "40:00", "1:04:10". */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = String(total % 60).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

/** A total: "41h 12m", "38m". */
export function formatHours(seconds: number): string {
  const total = Math.max(0, Math.round(seconds / 60));
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export function formatElevation(metres: number | null, units: Units): string {
  if (metres === null) return '–';
  return units === 'mi' ? `${Math.round(metres * FEET_PER_METRE)} ft` : `${Math.round(metres)} m`;
}

/** Named by when it happened, the way a runner would say it. */
export function runTitle(startedAt: Date): string {
  const hour = startedAt.getHours();
  if (hour >= 4 && hour < 11) return 'Morning run';
  if (hour >= 11 && hour < 14) return 'Lunch run';
  if (hour >= 14 && hour < 17) return 'Afternoon run';
  if (hour >= 17 && hour < 21) return 'Evening run';
  return 'Night run';
}

/** WMO weather codes, as Open-Meteo reports them, in a word or two. */
export function weatherLabel(code: number | null): string | null {
  if (code === null) return null;
  if (code === 0) return 'Clear';
  if (code <= 2) return 'Partly cloudy';
  if (code === 3) return 'Overcast';
  if (code === 45 || code === 48) return 'Fog';
  if (code >= 51 && code <= 57) return 'Drizzle';
  if (code >= 61 && code <= 67) return 'Rain';
  if (code >= 71 && code <= 77) return 'Snow';
  if (code >= 80 && code <= 82) return 'Showers';
  if (code === 85 || code === 86) return 'Snow showers';
  if (code >= 95) return 'Thunderstorm';
  return null;
}

export const EFFORT_LABELS: Record<number, string> = {
  400: '400 m',
  805: '½ mile',
  1000: '1K',
  1609: '1 mile',
  3219: '2 mile',
  5000: '5K',
  10000: '10K',
  15000: '15K',
  16093: '10 mile',
  20000: '20K',
  21097: 'Half marathon',
  30000: '30K',
  42195: 'Marathon',
};

/** The IANA zone the phone is in, so weeks and months break where the athlete's do. */
export function localTimeZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

export function weekdayShort(date: Date): string {
  return WEEKDAYS[date.getDay()]!;
}

export function monthShort(monthIndex: number): string {
  return MONTHS[monthIndex]!;
}

export function monthName(monthIndex: number): string {
  return MONTH_NAMES[monthIndex]!;
}

/** "Sep 7" from a server date string ("2026-09-07") without a timezone shift. */
export function shortDate(isoDate: string): string {
  const [, month, day] = isoDate.split('-').map(Number);
  return `${MONTHS[(month ?? 1) - 1]} ${day}`;
}
