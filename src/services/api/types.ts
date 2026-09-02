/** Mirrors backend/app/schemas.py. Kept by hand; the surface is four endpoints. */

export type GpsSample = {
  ts: number;
  lat: number;
  lon: number;
  accuracy_m: number | null;
  speed_mps: number | null;
  provider: string | null;
  is_mock: boolean;
};

export type RunSubmission = {
  run_id: string;
  started_at: string;
  ended_at: string;
  samples: GpsSample[];
  source?: 'tracked' | 'ambient' | 'imported';
};

export type SegmentResult = {
  territory_id: string;
  slug: string;
  name: string;
  distance_m: number;
  seconds_in: number;
  total_distance_m: number;
  active_influence: number;
  legacy_influence: number;
  influence_granted: number;
  owner_device_id: string | null;
  is_owned_by_you: boolean;
  ownership_changed: boolean;
  /** Present only when a server-validated loop secured this territory. */
  capture_method: 'loop' | null;
};

export type RunResult = {
  run_id: string;
  status:
    | 'submitted'
    | 'validated'
    | 'provisional'
    | 'applied'
    | 'rejected'
    | 'challenged'
    | 'reversed';
  distance_m: number;
  duration_s: number;
  sample_count: number;
  samples_dropped: number;
  segments: SegmentResult[];
};

export type TerritoryState = {
  territory_id: string;
  slug: string;
  name: string;
  kind: string;
  version: number;
  owner_device_id: string | null;
  total_distance_m: number;
};

export type TerritoryInfluenceEntry = {
  device_id: string;
  display_name: string;
  active_influence: number;
  legacy_influence: number;
  total_distance_m: number;
  share: number;
  is_owner: boolean;
  is_you: boolean;
};

export type TerritoryDetails = {
  territory_id: string;
  slug: string;
  name: string;
  kind: string;
  owner_device_id: string | null;
  total_active_influence: number;
  standings: TerritoryInfluenceEntry[];
};

/**
 * Opaque, content-addressed version of a published region returned in
 * `X-Territory-Dataset-Version`. Compare it only for equality.
 */
export type TerritoryDatasetVersion = string;

export type TerritoryScope = {
  city?: string;
  area?: string;
};

/**
 * Metadata returned with the static dataset and live ownership endpoints.
 * The body shapes remain unchanged for compatibility with existing callers.
 */
export type TerritorySyncResponse<T> = {
  data: T | null;
  datasetVersion: TerritoryDatasetVersion | null;
  notModified: boolean;
};

export type TerritoryFeatureCollection = {
  type: 'FeatureCollection';
  /** Legacy numeric value; use the response metadata for cache invalidation. */
  dataset_version: number;
  attribution: string;
  features: GeoJSON.Feature[];
};

export type HomeSelectionMetadata = {
  source?: 'onboarding' | 'settings';
  note?: string | null;
};

export type HomeTerritoryUpdate = {
  territory_id: string;
  metadata?: HomeSelectionMetadata;
};

export type HomeTerritorySummary = {
  territory_id: string;
  slug: string;
  name: string;
  selected_at: string;
  change_available_at: string;
  metadata: Required<HomeSelectionMetadata>;
};

export type ExperienceSummary = {
  applied_tracked_runs: number;
  applied_tracked_distance_m: number;
  total_xp: number;
  level: number;
  xp_into_level: number;
  xp_to_next_level: number;
  meters_per_xp: number;
  xp_per_level: number;
};

export type LegacySummary = {
  applied_tracked_runs: number;
  territories_contributed: number;
  contributed_distance_m: number;
  lifetime_influence: number;
  active_influence: number;
};

export type PrestigeSummary = {
  score: number;
  legacy_component: number;
  active_component: number;
  consistency_component: number;
  legacy_weight: number;
  active_weight: number;
  run_weight: number;
};

export type ProfileSummary = {
  device_id: string;
  home: HomeTerritorySummary | null;
  experience: ExperienceSummary;
  legacy: LegacySummary;
  prestige: PrestigeSummary;
};

export type AccountSummary = {
  id: string;
  display_name: string;
  avatar_url: string | null;
  role: 'player' | 'developer';
  created_at: string;
  provider: 'apple' | 'google' | 'developer' | null;
  total_distance_m: number;
  territories_led: number;
  developer_slot: number | null;
};
