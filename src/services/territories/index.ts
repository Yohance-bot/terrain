import { getDb, getMeta, setMeta } from '@/lib/db';
import { fetchTerritoryState, syncTerritories } from '@/services/api/client';
import type { TerritoryState } from '@/services/api/types';

/**
 * Territory shapes change only when the dataset is republished, so they are
 * cached on the device after the first successful load. Running environments have
 * poor connectivity -- `04_APPLICATION_ARCHITECTURE` requires that boundaries
 * still render without a network.
 *
 * Ownership is cached only as a last-known map rendering fallback. It is
 * explicitly labelled by its source and is never used to calculate influence,
 * decide a claim, or substitute for a server response.
 */

const CACHE_KEY = 'territories_geojson';
const CACHE_VERSION_KEY = 'territories_cache_version';
const OWNERSHIP_CACHE_KEY = 'territories_last_known_ownership';
const OWNERSHIP_CACHE_UPDATED_AT_KEY = 'territories_last_known_ownership_updated_at';

type OwnershipSnapshot = {
  states: TerritoryState[];
  fetchedAt: string;
};

export type OwnershipState = {
  ownedByYou: Set<string>;
  ownedByOthers: Set<string>;
  states: TerritoryState[];
  /** True only when the network request failed and this is an older observation. */
  fromCache: boolean;
  fetchedAt: Date;
};

/** Drop cached GeoJSON (e.g. after a pipeline republish). */
export async function clearTerritoryCache(): Promise<void> {
  const db = await getDb();
  await db.runAsync('DELETE FROM meta WHERE key IN (?, ?)', [
    CACHE_KEY,
    CACHE_VERSION_KEY,
  ]);
}

export async function loadTerritories(options?: {
  forceRefresh?: boolean;
}): Promise<{
  collection: GeoJSON.FeatureCollection;
  fromCache: boolean;
}> {
  if (options?.forceRefresh) {
    await clearTerritoryCache();
  }

  try {
    const knownDatasetVersion = options?.forceRefresh
      ? undefined
      : await getMeta(CACHE_VERSION_KEY);
    const remote = await syncTerritories({ knownDatasetVersion: knownDatasetVersion ?? undefined });
    if (remote.notModified) {
      const cached = await getMeta(CACHE_KEY);
      if (!cached) throw new Error('Territory server returned 304 without a local shape cache.');
      return { collection: JSON.parse(cached) as GeoJSON.FeatureCollection, fromCache: false };
    }
    if (!remote.data) throw new Error('Territory server returned no shape dataset.');
    const collection: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: remote.data.features,
    };
    await setMeta(CACHE_KEY, JSON.stringify(collection));
    if (remote.datasetVersion) {
      await setMeta(CACHE_VERSION_KEY, remote.datasetVersion);
    }
    return { collection, fromCache: false };
  } catch (error) {
    const cached = await getMeta(CACHE_KEY);
    if (!cached) throw error;
    return { collection: JSON.parse(cached) as GeoJSON.FeatureCollection, fromCache: true };
  }
}

function toOwnershipState(
  deviceId: string,
  states: TerritoryState[],
  fetchedAt: Date,
  fromCache: boolean
): OwnershipState {
  const ownedByYou = new Set<string>();
  const ownedByOthers = new Set<string>();

  for (const state of states) {
    if (!state.owner_device_id) continue;
    if (state.owner_device_id === deviceId) ownedByYou.add(state.territory_id);
    else ownedByOthers.add(state.territory_id);
  }

  return { ownedByYou, ownedByOthers, states, fromCache, fetchedAt };
}

/** Persist a server-provided ownership observation for offline map rendering. */
export async function cacheLastKnownOwnership(
  states: TerritoryState[],
  fetchedAt = new Date()
): Promise<void> {
  const snapshot: OwnershipSnapshot = { states, fetchedAt: fetchedAt.toISOString() };
  await setMeta(OWNERSHIP_CACHE_KEY, JSON.stringify(snapshot));
  await setMeta(OWNERSHIP_CACHE_UPDATED_AT_KEY, snapshot.fetchedAt);
}

/** Returns no value when the device has not yet observed ownership from the server. */
export async function loadLastKnownOwnership(deviceId: string): Promise<OwnershipState | null> {
  const raw = await getMeta(OWNERSHIP_CACHE_KEY);
  if (!raw) return null;

  try {
    const snapshot = JSON.parse(raw) as Partial<OwnershipSnapshot>;
    if (!Array.isArray(snapshot.states) || typeof snapshot.fetchedAt !== 'string') return null;
    const fetchedAt = new Date(snapshot.fetchedAt);
    if (Number.isNaN(fetchedAt.getTime())) return null;
    return toOwnershipState(deviceId, snapshot.states, fetchedAt, true);
  } catch {
    return null;
  }
}

/**
 * Loads the current server state and preserves it as a map-only fallback.
 * A cached response retains its age/source so callers cannot mistake it for an
 * authoritative ownership decision.
 */
export async function loadOwnership(deviceId: string): Promise<OwnershipState> {
  try {
    const states = await fetchTerritoryState();
    const fetchedAt = new Date();
    await cacheLastKnownOwnership(states, fetchedAt);
    return toOwnershipState(deviceId, states, fetchedAt, false);
  } catch (error) {
    const cached = await loadLastKnownOwnership(deviceId);
    if (cached) return cached;
    throw error;
  }
}
