/** Mirrors backend/app/schemas.py. Kept by hand; the surface is four endpoints. */

export type GpsSample = {
  ts: number;
  lat: number;
  lon: number;
  accuracy_m: number | null;
  speed_mps: number | null;
  provider: string | null;
  is_mock: boolean;
  altitude_m?: number | null;
  altitude_accuracy_m?: number | null;
};

export type RunConditions = { temperature_c: number | null; weather_code: number | null };

export type RunSubmission = {
  run_id: string;
  started_at: string;
  ended_at: string;
  samples: GpsSample[];
  source?: 'tracked' | 'ambient' | 'imported';
  conditions?: RunConditions | null;
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
  captured_area_id?: string | null;
  captured_area_m2?: number;
};

export type TerritoryState = {
  owner_display_name?: string | null;
  label_coordinate?: [number, number] | null;
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
  /** Unique, typeable identity used to find this player. Server-assigned. */
  handle: string | null;
  avatar_url: string | null;
  role: 'player' | 'developer';
  created_at: string;
  provider: 'apple' | 'google' | 'developer' | null;
  total_distance_m: number;
  territories_led: number;
  developer_slot: number | null;
};

/** What one player may see of another before they are friends. */
export type PublicAccount = {
  id: string;
  display_name: string;
  handle: string;
  avatar_url: string | null;
  relationship: 'none' | 'friends' | 'request_sent' | 'request_received' | 'blocked';
};

export type FriendRequest = {
  id: string;
  account: PublicAccount;
  direction: 'incoming' | 'outgoing';
  created_at: string;
};

export type Friend = { account: PublicAccount; friends_since: string };

export type FriendList = {
  friends: Friend[];
  incoming: FriendRequest[];
  outgoing: FriendRequest[];
  blocked: PublicAccount[];
};

export type SharingEntry = {
  account: PublicAccount;
  share_location: boolean;
  notify_on_run_start: boolean;
  /** Set only while a race or other temporary grant is running. */
  location_expires_at: string | null;
};

export type SharingOverview = {
  sharing_with: SharingEntry[];
  visible_to_me: PublicAccount[];
};

export type PositionUpdate = {
  lat: number;
  lon: number;
  accuracy_m?: number | null;
  heading?: number | null;
  speed_mps?: number | null;
  is_running?: boolean;
  run_id?: string | null;
};

export type FriendPosition = {
  account: PublicAccount;
  lat: number;
  lon: number;
  accuracy_m: number | null;
  heading: number | null;
  speed_mps: number | null;
  is_running: boolean;
  updated_at: string;
};

export type LiveView = { friends: FriendPosition[]; races: RaceRecord[] };

export type SocialEvent = {
  id: number;
  kind: string;
  body: string;
  actor: PublicAccount | null;
  subject_id: string | null;
  created_at: string;
  read_at: string | null;
};

export type ChallengeMetric =
  | 'distance'
  | 'runs'
  | 'moving_time'
  | 'captured_area'
  | 'territories';
export type ChallengeComparison = 'most' | 'fastest_to';
export type ChallengeStatus =
  | 'pending'
  | 'accepted'
  | 'declined'
  | 'cancelled'
  | 'expired'
  | 'resolved';

export type ChallengeStakeSummary = {
  staked_area_id: string | null;
  staked_area_m2: number | null;
  require_opponent_area_m2: number | null;
  transferred_at: string | null;
};

export type ChallengeRecord = {
  id: string;
  challenger: PublicAccount;
  opponent: PublicAccount;
  role: 'challenger' | 'opponent';
  metric: ChallengeMetric;
  comparison: ChallengeComparison;
  target_value: number | null;
  window_start: string;
  window_end: string;
  goal_text: string;
  status: ChallengeStatus;
  accept_deadline: string;
  outcome: 'challenger' | 'opponent' | 'draw' | 'nobody' | null;
  winner_id: string | null;
  challenger_value: number | null;
  opponent_value: number | null;
  stake: ChallengeStakeSummary | null;
  resolved_at: string | null;
  created_at: string;
};

export type ChallengeDraft = {
  opponent_id: string;
  metric: ChallengeMetric;
  comparison?: ChallengeComparison;
  target_value?: number | null;
  window_days?: number;
  goal_text: string;
  stake?: { staked_area_id?: string | null; require_opponent_area_m2?: number | null } | null;
};

export type RaceStatus =
  | 'pending'
  | 'running'
  | 'finished'
  | 'declined'
  | 'cancelled'
  | 'expired';

export type RaceRecord = {
  id: string;
  challenger: PublicAccount;
  opponent: PublicAccount;
  role: 'challenger' | 'opponent';
  pin_lat: number;
  pin_lon: number;
  pin_label: string | null;
  radius_m: number;
  status: RaceStatus;
  accept_deadline: string;
  started_at: string | null;
  expires_at: string | null;
  winner_id: string | null;
  finished_at: string | null;
  created_at: string;
};

export type GhostSummary = {
  id: string;
  name: string;
  owner: PublicAccount;
  distance_m: number;
  duration_s: number;
  start_lat: number;
  start_lon: number;
  is_public: boolean;
  share_live_location: boolean;
  is_yours: boolean;
  best_elapsed_s: number | null;
  created_at: string;
};

/** `path` is [lon, lat, msFromStart], trimmed at both ends for anyone but the owner. */
export type GhostDetail = GhostSummary & { path: [number, number, number][] };

export type GhostAttempt = {
  id: string;
  ghost_id: string;
  started_at: string;
  finished_at: string | null;
  elapsed_s: number | null;
  beat_ghost: boolean | null;
  ghost_duration_s: number;
};

export type StakeableArea = {
  id: string;
  area_m2: number;
  run_id: string;
  created_at: string;
};

// --- Athlete profile ----------------------------------------------------------
// Metres and seconds throughout; `src/lib/format` owns every conversion.

export type AthleteTotals = { runs: number; distance_m: number; moving_s: number; elevation_gain_m: number };
export type WeekBucket = AthleteTotals & { week_start: string };
export type MonthBucket = AthleteTotals & { month: string };
export type StreakSummary = { current_weeks: number; best_weeks: number; current_since: string | null; ran_this_week: boolean };
export type BestEffortRecord = { distance_m: number; elapsed_s: number; run_id: string; started_at: string };
export type RunRecord = { run_id: string; started_at: string; distance_m: number; elevation_gain_m: number | null };
export type GoalMetric = 'distance' | 'time' | 'runs';
export type GoalProgress = { metric: GoalMetric; target: number; value: number; updated_at: string };

export type AthleteStats = {
  timezone: string;
  generated_at: string;
  this_week: AthleteTotals;
  this_month: AthleteTotals;
  year_to_date: AthleteTotals;
  all_time: AthleteTotals;
  last_four_weeks: { runs_per_week: number; distance_m_per_week: number; moving_s_per_week: number };
  week_days_m: number[];
  weeks: WeekBucket[];
  months: MonthBucket[];
  streak: StreakSummary;
  best_efforts: BestEffortRecord[];
  longest_run: RunRecord | null;
  biggest_climb: RunRecord | null;
  goal: GoalProgress | null;
  territories_held: number;
  territories_captured: number;
};

export type ShoeRef = { id: string; name: string };

export type RunSummary = {
  run_id: string;
  started_at: string;
  ended_at: string;
  distance_m: number;
  moving_s: number;
  elapsed_s: number;
  elevation_gain_m: number | null;
  title: string | null;
  note: string | null;
  shoe: ShoeRef | null;
  captures: number;
  personal_records: number[];
  temperature_c: number | null;
  weather_code: number | null;
};

export type RunPage = { runs: RunSummary[]; next_before: string | null };
export type RunSplit = { index: number; distance_m: number; moving_s: number; elevation_delta_m: number | null };
export type RunEffort = { distance_m: number; elapsed_s: number; rank: number | null; personal_record: boolean };

export type RunActivity = {
  summary: RunSummary;
  splits: RunSplit[];
  pace_series: [number, number][];
  elevation_series: [number, number][];
  best_efforts: RunEffort[];
  elevation_loss_m: number | null;
  calories: number | null;
};

export type RunAnnotationUpdate = { title?: string | null; note?: string | null; shoe_id?: string | null };
export type AthleteSettings = { weight_kg: number | null };
export type ShoeRecord = { id: string; name: string; is_default: boolean; retired: boolean; distance_m: number; runs: number; created_at: string };

export type FriendProfile = {
  account: PublicAccount;
  friends_since: string;
  this_week: AthleteTotals;
  year_to_date: AthleteTotals;
  all_time: AthleteTotals;
  weeks: WeekBucket[];
  streak: StreakSummary;
  best_efforts: BestEffortRecord[];
  longest_run: RunRecord | null;
  territories_held: number;
  recent_runs: RunSummary[];
};
