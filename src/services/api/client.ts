import { API_BASE_URL } from '@/constants/config';
import { getMeta } from '@/lib/db';
import { readAuth, writeAuth } from '@/lib/auth/storage';
import { DEV_RUNNERS, setDevRunnerId, getDeviceId } from '@/lib/device';

import { ApiRequestError } from './errors';
import type {
  HomeTerritoryUpdate,
  AccountSummary,
  ProfileSummary,
  RunResult,
  RunSubmission,
  TerritoryFeatureCollection,
  TerritoryDetails,
  TerritoryScope,
  TerritoryState,
  TerritorySyncResponse,
} from './types';

// A tunnel that has expired should not leave a pressable or startup refresh in
// limbo until iOS eventually gives up on the socket.
export const DEFAULT_REQUEST_TIMEOUT_MS = 8_000;
// The free Render instance can need 50+ seconds to wake up. Even a warm
// account list took 10.45s across the Oregon → Mumbai database connection.
export const ACCOUNT_REQUEST_TIMEOUT_MS = 90_000;
// Submitting a run requires PostGIS clipping, loop detection, and multiple ledger
// updates on the server. On cloud deployments this legitimately takes 8.5–15 seconds.
export const SUBMIT_RUN_TIMEOUT_MS = 45_000;

export interface RequestOptions extends RequestInit {
  timeoutMs?: number;
}

function territoryPath(path: string, scope?: TerritoryScope): string {
  if (!scope?.city && !scope?.area) return path;

  const query = new URLSearchParams();
  if (scope.city) query.set('city', scope.city);
  if (scope.area) query.set('area', scope.area);
  return `${path}?${query.toString()}`;
}

async function requestResponse(path: string, init?: RequestOptions): Promise<Response> {
  const deviceId = await getDeviceId();
  const token = await readAuth("token");
  const controller = new AbortController();
  let timedOut = false;
  const timeoutMs = init?.timeoutMs ?? (path.startsWith('/v1/account') || path.startsWith('/v1/auth')
    ? ACCOUNT_REQUEST_TIMEOUT_MS : DEFAULT_REQUEST_TIMEOUT_MS);
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const abortFromCaller = () => controller.abort();
  init?.signal?.addEventListener('abort', abortFromCaller, { once: true });

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'X-Device-Id': deviceId,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
    });
  } catch (error) {
    if (timedOut) {
      throw new Error(`Request timed out after ${timeoutMs / 1_000}s: ${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    init?.signal?.removeEventListener('abort', abortFromCaller);
  }

  if (!response.ok && response.status !== 304) {
    const body = await response.text();
    throw new ApiRequestError(init?.method ?? 'GET', path, response.status, body);
  }
  return response;
}

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const response = await requestResponse(path, init);
  return response.json() as Promise<T>;
}

async function requestTerritorySync<T>(
  path: string,
  knownDatasetVersion?: string
): Promise<TerritorySyncResponse<T>> {
  const response = await requestResponse(path, {
    headers: knownDatasetVersion
      ? { 'If-None-Match': `"${knownDatasetVersion}"` }
      : undefined,
  });

  return {
    data: response.status === 304 ? null : ((await response.json()) as T),
    datasetVersion: response.headers.get('X-Territory-Dataset-Version'),
    notModified: response.status === 304,
  };
}

export function fetchTerritories(scope?: TerritoryScope): Promise<TerritoryFeatureCollection> {
  return request<TerritoryFeatureCollection>(territoryPath('/v1/territories', scope));
}

export function fetchTerritoryState(scope?: TerritoryScope): Promise<TerritoryState[]> {
  return request<TerritoryState[]>(territoryPath('/v1/territories/state', scope));
}

export function fetchTerritoryDetails(territoryId: string): Promise<TerritoryDetails> {
  return request<TerritoryDetails>(`/v1/territories/${territoryId}`);
}

/** Public loop polygons; distinct from permanent generated territories. */
export function fetchCapturedAreas(): Promise<GeoJSON.FeatureCollection> {
  // Hide pre-account anonymous/test captures from the player map while keeping
  // the unfiltered endpoint available for migration and operational checks.
  return request<GeoJSON.FeatureCollection>('/v1/captured-areas?linked_only=true');
}

/** Server-dissolved geometry for each owner's connected fixed territories. */
export function fetchOwnedTerritoryAreas(): Promise<GeoJSON.FeatureCollection> {
  return request<GeoJSON.FeatureCollection>('/v1/territories/owned-areas');
}

/**
 * Fetch static boundaries with the content-addressed server dataset version.
 * Passing the previously stored version avoids retransferring unchanged GeoJSON.
 */
export function syncTerritories(options?: {
  scope?: TerritoryScope;
  knownDatasetVersion?: string;
}): Promise<TerritorySyncResponse<TerritoryFeatureCollection>> {
  return requestTerritorySync(
    territoryPath('/v1/territories', options?.scope),
    options?.knownDatasetVersion
  );
}

/**
 * Fetch the separately-polled ownership layer and identify the shape dataset
 * it applies to. If this differs from the cached boundary version, refresh
 * boundaries before joining the two layers.
 */
export function syncTerritoryState(
  scope?: TerritoryScope
): Promise<TerritorySyncResponse<TerritoryState[]>> {
  return requestTerritorySync(territoryPath('/v1/territories/state', scope));
}

/**
 * Submits a finished run. The run id is generated on the device and doubles as
 * the idempotency key, so a retry after a failed upload returns the original
 * result rather than counting the distance twice.
 */
export async function submitRun(submission: RunSubmission): Promise<RunResult> {
  const owner = await getMeta(`run.owner.${submission.run_id}`);
  if (!owner || owner !== await getDeviceId()) {
    throw new Error('This saved run belongs to another or an earlier account. Sign in with its original runner before uploading.');
  }
  return request<RunResult>('/v1/runs', {
    method: 'POST',
    body: JSON.stringify(submission),
    timeoutMs: SUBMIT_RUN_TIMEOUT_MS,
  });
}

export function fetchRun(runId: string): Promise<RunResult> {
  return request<RunResult>(`/v1/runs/${runId}`);
}

/** Fetches device-scoped, server-derived Home and progression summaries. */
export function fetchProfile(): Promise<ProfileSummary> {
  return request<ProfileSummary>('/v1/profile');
}

/**
 * Selects the device's personal Home. This does not create ownership or change
 * any territory influence; the server enforces the configured change cooldown.
 */
export function updateHomeTerritory(update: HomeTerritoryUpdate): Promise<ProfileSummary> {
  return request<ProfileSummary>('/v1/profile/home', {
    method: 'PUT',
    body: JSON.stringify(update),
  });
}

let memoryCachedAccount: AccountSummary | null = null;

export function getCachedAccount(): AccountSummary | null {
  return memoryCachedAccount;
}

export function setCachedAccount(account: AccountSummary | null): void {
  memoryCachedAccount = account;
}

export async function fetchAccount(): Promise<AccountSummary | null> {
  if (!await readAuth("token")) return null;
  const account = await request<AccountSummary | null>('/v1/account');
  memoryCachedAccount = account;
  return account;
}

export async function updateAccount(display_name: string): Promise<AccountSummary> {
  const res = await request<AccountSummary>('/v1/account', { method: 'PUT', body: JSON.stringify({ display_name }) });
  memoryCachedAccount = res;
  return res;
}

export async function signOutAccount(): Promise<void> {
  memoryCachedAccount = null;
  try { await requestResponse('/v1/auth/logout', { method: 'POST' }); }
  finally { await writeAuth('token',''); await writeAuth('device',''); setDevRunnerId(null); }
}

export async function requestAccountDeletion(): Promise<void> {
  memoryCachedAccount = null;
  await requestResponse('/v1/account/deletion-request', { method: 'POST' });
}

export async function developerLogin(pin: string): Promise<AccountSummary> {
  const res = await request<AccountSummary>('/v1/account/developer-login', { method: 'POST', body: JSON.stringify({ pin }) });
  memoryCachedAccount = res;
  return res;
}

export function fetchLocalAccounts(): Promise<AccountSummary[]> {
  return request<AccountSummary[]>('/v1/account/local-accounts');
}

export async function createLocalAccount(display_name: string): Promise<AccountSummary> {
  const res = await request<AccountSummary>('/v1/account/local-accounts', {
    method: 'POST',
    body: JSON.stringify({ display_name }),
  });
  memoryCachedAccount = res;
  return res;
}

export async function signInLocalAccount(accountId: string): Promise<AccountSummary> {
  const res = await request<AccountSummary>(`/v1/account/local-accounts/${accountId}/sign-in`, {
    method: 'POST',
  });
  memoryCachedAccount = res;
  return res;
}

export async function resetDeveloperTerritory(territoryId: string): Promise<void> {
  await requestResponse(`/v1/account/developer/territories/${territoryId}/reset`, { method: 'POST' });
}

interface SessionResponse { token: string; device_id: string; account: AccountSummary }
async function acceptSession(result: SessionResponse): Promise<AccountSummary> {
  await writeAuth('device',result.device_id);
  await writeAuth('token',result.token);
  setDevRunnerId(result.account.developer_slot ? DEV_RUNNERS[result.account.developer_slot-1]?.id ?? null : null);
  memoryCachedAccount=result.account;
  return result.account;
}
export async function passwordLogin(username:string,password:string,display_name?:string) {
  return acceptSession(await request<SessionResponse>(`/v1/auth/${display_name?'register':'login'}`,{
    method:'POST',body:JSON.stringify({username,password,...(display_name?{display_name}:{})})}));
}
export async function googleLogin(access_token:string) {
  return acceptSession(await request<SessionResponse>('/v1/auth/google',{method:'POST',body:JSON.stringify({access_token})}));
}
export function fetchCredentials() {return request<{username:string|null;has_password:boolean}>('/v1/auth/profile');}
export function updateCredentials(username:string,current_password:string,new_password:string) {
  return request('/v1/auth/profile',{method:'PUT',body:JSON.stringify({username,current_password,...(new_password?{new_password}:{})})});
}
