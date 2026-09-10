import { API_BASE_URL } from '@/constants/config';
import { getMeta } from '@/lib/db';
import { readAuth, writeAuth } from '@/lib/auth/storage';
import { DEV_RUNNERS, setDevRunnerId, getDeviceId } from '@/lib/device';

import { ApiRequestError } from './errors';
import type {
  HomeTerritoryUpdate,
  AccountSummary,
  ChallengeDraft,
  ChallengeRecord,
  Friend,
  FriendList,
  FriendRequest,
  GhostAttempt,
  GhostDetail,
  GhostSummary,
  LiveView,
  PositionUpdate,
  PublicAccount,
  RaceRecord,
  SharingOverview,
  SocialEvent,
  StakeableArea,
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


// --- Social ----------------------------------------------------------------
// Friendship gates location sharing, challenges and races, so every one of
// these calls is account-scoped and requires a signed-in session.

/** Find a player by handle prefix, display-name prefix, or exact account ID. */
export function searchAccounts(query: string): Promise<PublicAccount[]> {
  return request<PublicAccount[]>(`/v1/social/search?q=${encodeURIComponent(query)}`);
}

export function fetchFriends(): Promise<FriendList> {
  return request<FriendList>('/v1/social/friends');
}

/** Accepts a handle (with or without '@') or a raw account ID. */
export function sendFriendRequest(identifier: string): Promise<FriendRequest> {
  const value = identifier.trim().replace(/^@/, '');
  const isAccountId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
  return request<FriendRequest>('/v1/social/friends/requests', {
    method: 'POST',
    body: JSON.stringify(isAccountId ? { account_id: value } : { handle: value }),
  });
}

export function acceptFriendRequest(requestId: string): Promise<Friend> {
  return request<Friend>(`/v1/social/friends/requests/${requestId}/accept`, { method: 'POST' });
}

export async function declineFriendRequest(requestId: string): Promise<void> {
  await requestResponse(`/v1/social/friends/requests/${requestId}/decline`, { method: 'POST' });
}

export async function removeFriend(accountId: string): Promise<void> {
  await requestResponse(`/v1/social/friends/${accountId}`, { method: 'DELETE' });
}

export async function blockAccount(accountId: string): Promise<void> {
  await requestResponse(`/v1/social/block/${accountId}`, { method: 'POST' });
}

export async function unblockAccount(accountId: string): Promise<void> {
  await requestResponse(`/v1/social/block/${accountId}`, { method: 'DELETE' });
}

export async function updateHandle(handle: string): Promise<PublicAccount> {
  const updated = await request<PublicAccount>('/v1/social/handle', {
    method: 'PUT',
    body: JSON.stringify({ handle }),
  });
  if (memoryCachedAccount) memoryCachedAccount = { ...memoryCachedAccount, handle: updated.handle };
  return updated;
}

// --- Sharing and presence ---------------------------------------------------
// Position reporting is a single round trip: it posts where you are and returns
// what you are allowed to see, because the client polls this while recording.

export function fetchSharing(): Promise<SharingOverview> {
  return request<SharingOverview>('/v1/social/sharing');
}

export function updateSharing(
  accountId: string,
  update: { share_location?: boolean; notify_on_run_start?: boolean }
): Promise<SharingOverview['sharing_with'][number]> {
  return request(`/v1/social/sharing/${accountId}`, {
    method: 'PUT',
    body: JSON.stringify(update),
  });
}

export function reportPosition(update: PositionUpdate): Promise<LiveView> {
  return request<LiveView>('/v1/social/position', {
    method: 'POST',
    body: JSON.stringify(update),
    // A missed position is not worth stalling a recording screen for.
    timeoutMs: 6_000,
  });
}

export async function clearPosition(): Promise<void> {
  await requestResponse('/v1/social/position', { method: 'DELETE' });
}

export function fetchLive(): Promise<LiveView> {
  return request<LiveView>('/v1/social/live');
}

/** Tells only the friends who opted in to run-start alerts. */
export async function announceRunStart(runId: string): Promise<void> {
  await requestResponse(`/v1/social/runs/${runId}/started`, { method: 'POST' });
}

export function fetchSocialEvents(unreadOnly = false): Promise<SocialEvent[]> {
  return request<SocialEvent[]>(`/v1/social/events${unreadOnly ? '?unread_only=true' : ''}`);
}

export async function markEventsRead(): Promise<void> {
  await requestResponse('/v1/social/events/read', { method: 'POST' });
}

// --- Challenges -------------------------------------------------------------

export function fetchChallenges(): Promise<ChallengeRecord[]> {
  return request<ChallengeRecord[]>('/v1/social/challenges');
}

/** Individual loop closures you own, which is what a stake transfers. */
export function fetchStakeableAreas(): Promise<StakeableArea[]> {
  return request<StakeableArea[]>('/v1/social/challenges/stakeable');
}

export function createChallenge(draft: ChallengeDraft): Promise<ChallengeRecord> {
  return request<ChallengeRecord>('/v1/social/challenges', {
    method: 'POST',
    body: JSON.stringify(draft),
  });
}

export function answerChallenge(
  challengeId: string,
  answer: 'accept' | 'decline' | 'cancel'
): Promise<ChallengeRecord> {
  return request<ChallengeRecord>(`/v1/social/challenges/${challengeId}/${answer}`, {
    method: 'POST',
  });
}

// --- Races ------------------------------------------------------------------

export function fetchRaces(): Promise<RaceRecord[]> {
  return request<RaceRecord[]>('/v1/social/races');
}

export function createRace(race: {
  opponent_id: string;
  pin_lat: number;
  pin_lon: number;
  pin_label?: string | null;
  radius_m?: number;
}): Promise<RaceRecord> {
  return request<RaceRecord>('/v1/social/races', {
    method: 'POST',
    body: JSON.stringify(race),
  });
}

export function answerRace(
  raceId: string,
  answer: 'accept' | 'decline' | 'withdraw'
): Promise<RaceRecord> {
  return request<RaceRecord>(`/v1/social/races/${raceId}/${answer}`, { method: 'POST' });
}

// --- Ghosts -----------------------------------------------------------------

export function fetchMyGhosts(): Promise<GhostSummary[]> {
  return request<GhostSummary[]>('/v1/social/ghosts/mine');
}

/** Public ghosts near a point. The map keeps these behind a layer toggle. */
export function fetchNearbyGhosts(
  lat: number,
  lon: number,
  radiusM = 2000
): Promise<GhostSummary[]> {
  return request<GhostSummary[]>(
    `/v1/social/ghosts/nearby?lat=${lat}&lon=${lon}&radius_m=${radiusM}`
  );
}

export function createGhost(
  runId: string,
  name: string,
  isPublic = false
): Promise<GhostSummary> {
  return request<GhostSummary>('/v1/social/ghosts', {
    method: 'POST',
    body: JSON.stringify({ run_id: runId, name, is_public: isPublic }),
  });
}

export function fetchGhost(ghostId: string): Promise<GhostDetail> {
  return request<GhostDetail>(`/v1/social/ghosts/${ghostId}`);
}

export function updateGhost(
  ghostId: string,
  update: { name?: string; is_public?: boolean; share_live_location?: boolean }
): Promise<GhostSummary> {
  return request<GhostSummary>(`/v1/social/ghosts/${ghostId}`, {
    method: 'PUT',
    body: JSON.stringify(update),
  });
}

export async function deleteGhost(ghostId: string): Promise<void> {
  await requestResponse(`/v1/social/ghosts/${ghostId}`, { method: 'DELETE' });
}

export function startGhostAttempt(ghostId: string): Promise<GhostAttempt> {
  return request<GhostAttempt>(`/v1/social/ghosts/${ghostId}/attempts`, { method: 'POST' });
}

export function finishGhostAttempt(
  attemptId: string,
  elapsedS: number,
  runId?: string
): Promise<GhostAttempt> {
  return request<GhostAttempt>(`/v1/social/ghosts/attempts/${attemptId}/finish`, {
    method: 'POST',
    body: JSON.stringify({ elapsed_s: elapsedS, ...(runId ? { run_id: runId } : {}) }),
  });
}
