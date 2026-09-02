import { getMeta, setMeta } from '@/lib/db';

export type UnitPreference = 'km' | 'mi';

const UNITS_KEY = 'preference_units';
const NOTIFICATIONS_KEY = 'preference_notifications';
const CAPTURE_COLOR_KEY = 'preference_capture_color';

export async function getUnits(): Promise<UnitPreference> {
  return (await getMeta(UNITS_KEY)) === 'mi' ? 'mi' : 'km';
}

export async function setUnits(value: UnitPreference): Promise<void> {
  await setMeta(UNITS_KEY, value);
}

export async function getNotificationsEnabled(): Promise<boolean> {
  return (await getMeta(NOTIFICATIONS_KEY)) !== 'false';
}

export async function setNotificationsEnabled(value: boolean): Promise<void> {
  await setMeta(NOTIFICATIONS_KEY, String(value));
}

export async function getCaptureColorIndex(): Promise<number> {
  const raw = await getMeta(CAPTURE_COLOR_KEY);
  const parsed = raw ? parseInt(raw, 10) : 0;
  return Number.isFinite(parsed) ? parsed : 0;
}

export async function setCaptureColorIndex(index: number): Promise<void> {
  await setMeta(CAPTURE_COLOR_KEY, String(index));
}

