import * as Crypto from 'expo-crypto';
import { readAuth } from '@/lib/auth/storage';

import { getMeta, setMeta } from '@/lib/db';

/**
 * An anonymous, device-scoped identifier. This is NOT an account.
 *
 * Accounts are out of scope for this milestone, but the placeholder ownership
 * rule still needs to tell two runners apart, otherwise nothing can ever change
 * hands. There is no authentication, no recovery and no profile behind this. It
 * is replaced wholesale when real identity arrives.
 */

const KEY = 'device_id';
const DEV_RUNNER_KEY = 'developer_runner_id';
let cached: string | null = null;

export const DEV_RUNNERS = [
  { id: '10000000-0000-4000-8000-000000000001', label: 'Developer 1' },
  { id: '10000000-0000-4000-8000-000000000002', label: 'Developer 2' },
  { id: '10000000-0000-4000-8000-000000000003', label: 'Developer 3' },
] as const;

let devRunnerId: string | null = null;

export function getActiveDevRunnerId(): string {
  if (devRunnerId && DEV_RUNNERS.some((runner) => runner.id === devRunnerId)) {
    return devRunnerId;
  }
  return DEV_RUNNERS[0].id;
}

export async function getSelectedDevRunnerId(): Promise<string> {
  if (devRunnerId && DEV_RUNNERS.some((runner) => runner.id === devRunnerId)) {
    return devRunnerId;
  }
  const saved = await getMeta(DEV_RUNNER_KEY);
  if (saved && DEV_RUNNERS.some((runner) => runner.id === saved)) {
    devRunnerId = saved;
    return saved;
  }
  return DEV_RUNNERS[0].id;
}

/** Local-developer identity override for virtual runs. The backend only grants
 * this role through its local developer PIN gate. */
export function setDevRunnerId(id: string | null) {
  devRunnerId = DEV_RUNNERS.some((runner) => runner.id === id) ? id : null;
  void setMeta(DEV_RUNNER_KEY, devRunnerId ?? '');
}

export async function getDeviceId(): Promise<string> {
  const authenticated = await readAuth("device");
  if (authenticated) return authenticated;
  if (devRunnerId) return devRunnerId;
  const savedDeveloperRunner = await getMeta(DEV_RUNNER_KEY);
  if (savedDeveloperRunner && DEV_RUNNERS.some((runner) => runner.id === savedDeveloperRunner)) {
    devRunnerId = savedDeveloperRunner;
    return savedDeveloperRunner;
  }
  if (cached) return cached;

  const existing = await getMeta(KEY);
  if (existing) {
    cached = existing;
    return existing;
  }

  const created = Crypto.randomUUID();
  await setMeta(KEY, created);
  cached = created;
  return created;
}
