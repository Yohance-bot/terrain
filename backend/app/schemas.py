import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RunStatus = Literal[
    "submitted",
    "validated",
    "provisional",
    "applied",
    "rejected",
    "challenged",
    "reversed",
]
RunSource = Literal["tracked", "ambient", "imported"]
ConfigurationStatus = Literal["draft", "active", "retired"]


class GpsSample(BaseModel):
    """One GPS fix.

    The evidence fields -- accuracy, speed, provider, is_mock -- are captured and
    stored but never read. `05_ANTICHEAT_AND_TRUST` Principle 2 calls this the one
    genuinely irreversible decision: a run recorded without them can never be
    verified later. No detection logic exists in this milestone.
    """

    ts: int = Field(description="Epoch milliseconds")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = None
    speed_mps: float | None = None
    # Metres above sea level and its reported accuracy. Absent from runs recorded
    # before altitude was captured; elevation is simply unknown for those.
    altitude_m: float | None = Field(default=None, ge=-500, le=9000)
    altitude_accuracy_m: float | None = None
    provider: str | None = None
    is_mock: bool = False


class RunConditions(BaseModel):
    """Weather as the phone read it when the run started; purely descriptive."""

    temperature_c: float | None = Field(default=None, ge=-60, le=60)
    weather_code: int | None = Field(default=None, ge=0, le=99)


class RunSubmission(BaseModel):
    run_id: uuid.UUID = Field(description="Client-generated; doubles as the idempotency key")
    started_at: datetime
    ended_at: datetime
    samples: list[GpsSample]
    source: RunSource = "tracked"
    conditions: RunConditions | None = None


class RunLifecycleEventRecord(BaseModel):
    """Persistence shape for a future worker or admin workflow, not an API contract."""

    sequence: int = Field(ge=1)
    from_status: RunStatus | None = None
    to_status: RunStatus
    actor_kind: str = Field(default="system", max_length=32)
    actor_ref: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=512)
    details: dict[str, Any] | None = None


class ConfigurationRevisionDraft(BaseModel):
    """Local, provider-neutral configuration authoring shape for later S0 tooling."""

    namespace: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    payload: dict[str, Any]
    status: ConfigurationStatus = "draft"
    actor_kind: str = Field(default="system", max_length=32)
    actor_ref: str | None = Field(default=None, max_length=128)


class AuditEventRecord(BaseModel):
    """Append-only operational audit payload; identity integration remains a TODO."""

    actor_kind: str = Field(max_length=32)
    actor_ref: str | None = Field(default=None, max_length=128)
    action: str = Field(min_length=1, max_length=64)
    target_type: str = Field(min_length=1, max_length=64)
    target_ref: str = Field(min_length=1, max_length=128)
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    reason: str | None = Field(default=None, max_length=512)
    details: dict[str, Any] | None = None


class SegmentResult(BaseModel):
    territory_id: uuid.UUID
    slug: str
    name: str
    distance_m: float
    seconds_in: int
    total_distance_m: float = Field(
        description="This device's cumulative distance inside the territory"
    )
    active_influence: float = Field(
        default=0, description="This device's current decayed active standing"
    )
    legacy_influence: float = Field(
        default=0, description="This device's lifetime influence standing"
    )
    influence_granted: float = Field(
        default=0, description="Influence this run granted to the segment"
    )
    owner_device_id: uuid.UUID | None
    is_owned_by_you: bool
    ownership_changed: bool
    capture_method: Literal["loop"] | None = None


class RunResult(BaseModel):
    run_id: uuid.UUID
    status: RunStatus
    distance_m: float
    duration_s: int
    sample_count: int
    samples_dropped: int
    segments: list[SegmentResult]
    captured_area_id: uuid.UUID | None = None
    captured_area_m2: float = 0


class InternalRunReviewItem(BaseModel):
    """Restricted operations shape; never returned from player routes."""

    run_id: uuid.UUID
    device_id: uuid.UUID
    status: Literal["provisional", "challenged"]
    started_at: datetime
    ended_at: datetime
    distance_m: float
    source: RunSource
    lifecycle_version: int


class ManualRunReversal(BaseModel):
    """An accountable internal decision, deliberately separate from player input."""

    operator_ref: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=512)


class ManualRunReversalResult(BaseModel):
    run_id: uuid.UUID
    status: Literal["reversed"]
    rebuilt_territory_ids: list[uuid.UUID]


class TerritoryState(BaseModel):
    owner_display_name: str | None = None
    label_coordinate: list[float] | None = None
    territory_id: uuid.UUID
    slug: str
    name: str
    kind: str
    version: int
    owner_device_id: uuid.UUID | None
    total_distance_m: float


class TerritoryInfluenceEntry(BaseModel):
    device_id: uuid.UUID
    display_name: str
    active_influence: float
    legacy_influence: float
    total_distance_m: float
    share: float
    is_owner: bool
    is_you: bool


class TerritoryDetails(BaseModel):
    territory_id: uuid.UUID
    slug: str
    name: str
    kind: str
    owner_device_id: uuid.UUID | None
    total_active_influence: float
    standings: list[TerritoryInfluenceEntry]


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    dataset_version: int
    attribution: str
    features: list[dict[str, Any]]


HomeSelectionSource = Literal["onboarding", "settings"]


class HomeSelectionMetadata(BaseModel):
    """Bounded context for a Home choice; never a location-history payload."""

    source: HomeSelectionSource = "onboarding"
    note: str | None = Field(default=None, max_length=64)


class HomeTerritoryUpdate(BaseModel):
    territory_id: uuid.UUID
    metadata: HomeSelectionMetadata = Field(default_factory=HomeSelectionMetadata)


class HomeTerritorySummary(BaseModel):
    territory_id: uuid.UUID
    slug: str
    name: str
    selected_at: datetime
    change_available_at: datetime
    metadata: HomeSelectionMetadata


class ExperienceSummary(BaseModel):
    applied_tracked_runs: int
    applied_tracked_distance_m: float
    total_xp: int
    level: int
    xp_into_level: int
    xp_to_next_level: int
    meters_per_xp: float
    xp_per_level: int


class LegacySummary(BaseModel):
    applied_tracked_runs: int
    territories_contributed: int
    contributed_distance_m: float
    lifetime_influence: float
    active_influence: float


class PrestigeSummary(BaseModel):
    score: float
    legacy_component: float
    active_component: float
    consistency_component: float
    legacy_weight: float
    active_weight: float
    run_weight: float


class ProfileSummary(BaseModel):
    device_id: uuid.UUID
    home: HomeTerritorySummary | None
    experience: ExperienceSummary
    legacy: LegacySummary
    prestige: PrestigeSummary


class PrivacyRetentionPolicy(BaseModel):
    raw_trace_retention_days: int
    route_polyline_full_precision_days: int


class DeviceDeletionSummary(BaseModel):
    device_id: uuid.UUID
    raw_traces_deleted: int
    deletion_scope: Literal["device"]


class AccountSummary(BaseModel):
    id: uuid.UUID
    display_name: str
    handle: str | None = None
    avatar_url: str | None
    role: Literal["player", "developer"]
    created_at: datetime
    provider: Literal["apple", "google", "developer", "local"] | None = None
    total_distance_m: float = 0
    territories_led: int = 0
    developer_slot: int | None = None


class AccountUpdate(BaseModel):
    display_name: str = Field(min_length=2, max_length=32)


class DeveloperLogin(BaseModel):
    pin: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(default=None, min_length=2, max_length=32)


class LocalAccountCreate(BaseModel):
    display_name: str = Field(min_length=2, max_length=32)


class DeveloperTerritoryConfirmation(BaseModel):
    confirmed: bool = False
    reason: str = Field(min_length=3, max_length=256)


# --- Social layer -----------------------------------------------------------

RelationshipStatus = Literal[
    "none", "friends", "request_sent", "request_received", "blocked"
]


class PublicAccount(BaseModel):
    """What one player may see of another before they are friends."""

    id: uuid.UUID
    display_name: str
    handle: str
    avatar_url: str | None = None
    relationship: RelationshipStatus = "none"


class HandleUpdate(BaseModel):
    handle: str = Field(min_length=3, max_length=24)


class FriendRequestCreate(BaseModel):
    """Either identifier works, matching the two ways a player can be found."""

    handle: str | None = Field(default=None, max_length=25)
    account_id: uuid.UUID | None = None


class FriendRequest(BaseModel):
    id: uuid.UUID
    account: PublicAccount
    direction: Literal["incoming", "outgoing"]
    created_at: datetime


class Friend(BaseModel):
    account: PublicAccount
    friends_since: datetime


class FriendList(BaseModel):
    friends: list[Friend]
    incoming: list[FriendRequest]
    outgoing: list[FriendRequest]
    blocked: list[PublicAccount]


class SharingUpdate(BaseModel):
    """Both toggles are independent; omitting one leaves it unchanged."""

    share_location: bool | None = None
    notify_on_run_start: bool | None = None


class SharingEntry(BaseModel):
    account: PublicAccount
    share_location: bool
    notify_on_run_start: bool
    # Set only while a race or other temporary grant is running.
    location_expires_at: datetime | None = None


class SharingOverview(BaseModel):
    """Deliberately symmetrical: what you share out, and who can see you."""

    sharing_with: list[SharingEntry]
    visible_to_me: list[PublicAccount]


class PositionUpdate(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)
    heading: float | None = None
    speed_mps: float | None = Field(default=None, ge=0)
    is_running: bool = False
    run_id: uuid.UUID | None = None


class FriendPosition(BaseModel):
    account: PublicAccount
    lat: float
    lon: float
    accuracy_m: float | None = None
    heading: float | None = None
    speed_mps: float | None = None
    is_running: bool
    updated_at: datetime


class LiveView(BaseModel):
    friends: list[FriendPosition]
    # Populated after RaceRecord is defined; races share this single poll.
    races: list["RaceRecord"] = []


class SocialEventRecord(BaseModel):
    id: int
    kind: str
    body: str
    actor: PublicAccount | None = None
    subject_id: uuid.UUID | None = None
    created_at: datetime
    read_at: datetime | None = None


ChallengeMetric = Literal["distance", "runs", "moving_time", "captured_area", "territories"]
ChallengeComparison = Literal["most", "fastest_to"]
ChallengeStatus = Literal[
    "pending", "accepted", "declined", "cancelled", "expired", "resolved"
]
ChallengeOutcome = Literal["challenger", "opponent", "draw", "nobody"]


class ChallengeStakeInput(BaseModel):
    """Only loop closures can be staked; fixed territory ownership is derived."""

    staked_area_id: uuid.UUID | None = None
    require_opponent_area_m2: float | None = Field(default=None, ge=0)


class ChallengeStakeSummary(BaseModel):
    staked_area_id: uuid.UUID | None = None
    staked_area_m2: float | None = None
    require_opponent_area_m2: float | None = None
    transferred_at: datetime | None = None


class ChallengeCreate(BaseModel):
    opponent_id: uuid.UUID
    metric: ChallengeMetric
    comparison: ChallengeComparison = "most"
    # Required for 'fastest_to': the value both players race to reach.
    target_value: float | None = Field(default=None, gt=0)
    window_days: int = Field(default=3, ge=1, le=30)
    goal_text: str = Field(min_length=3, max_length=240)
    stake: ChallengeStakeInput | None = None


class ChallengeRecord(BaseModel):
    id: uuid.UUID
    challenger: PublicAccount
    opponent: PublicAccount
    role: Literal["challenger", "opponent"]
    metric: ChallengeMetric
    comparison: ChallengeComparison
    target_value: float | None
    window_start: datetime
    window_end: datetime
    goal_text: str
    status: ChallengeStatus
    accept_deadline: datetime
    outcome: ChallengeOutcome | None = None
    winner_id: uuid.UUID | None = None
    # Live totals while a challenge is running; final ones once it is resolved.
    challenger_value: float | None = None
    opponent_value: float | None = None
    stake: ChallengeStakeSummary | None = None
    resolved_at: datetime | None = None
    created_at: datetime


RaceStatus = Literal["pending", "running", "finished", "declined", "cancelled", "expired"]


class RaceCreate(BaseModel):
    opponent_id: uuid.UUID
    pin_lat: float = Field(ge=-90, le=90)
    pin_lon: float = Field(ge=-180, le=180)
    pin_label: str | None = Field(default=None, max_length=80)
    # Close enough counts; the client should not ask for pinpoint accuracy.
    radius_m: float = Field(default=25, ge=10, le=100)


class RaceRecord(BaseModel):
    id: uuid.UUID
    challenger: PublicAccount
    opponent: PublicAccount
    role: Literal["challenger", "opponent"]
    pin_lat: float
    pin_lon: float
    pin_label: str | None = None
    radius_m: float
    status: RaceStatus
    accept_deadline: datetime
    started_at: datetime | None = None
    expires_at: datetime | None = None
    winner_id: uuid.UUID | None = None
    finished_at: datetime | None = None
    created_at: datetime


LiveView.model_rebuild()


class GhostCreate(BaseModel):
    run_id: uuid.UUID
    name: str = Field(min_length=2, max_length=80)
    # Broadcasting the recorded route. Live location is a separate choice below.
    is_public: bool = False


class GhostUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    is_public: bool | None = None
    # Only meaningful alongside is_public, and never implied by it.
    share_live_location: bool | None = None


class GhostSummary(BaseModel):
    id: uuid.UUID
    name: str
    owner: PublicAccount
    distance_m: float
    duration_s: int
    start_lat: float
    start_lon: float
    is_public: bool
    share_live_location: bool
    is_yours: bool
    best_elapsed_s: int | None = None
    created_at: datetime


class GhostDetail(GhostSummary):
    """`path` is [[lon, lat, ms_from_start], ...], trimmed for anyone but the owner."""

    path: list[list[float]]


class GhostAttemptRecord(BaseModel):
    id: uuid.UUID
    ghost_id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None = None
    elapsed_s: int | None = None
    beat_ghost: bool | None = None
    ghost_duration_s: int


class GhostAttemptFinish(BaseModel):
    elapsed_s: int = Field(gt=0)
    run_id: uuid.UUID | None = None


class StakeableArea(BaseModel):
    """One loop closure a player owns, individually addressable so it can be staked."""

    id: uuid.UUID
    area_m2: float
    run_id: uuid.UUID
    created_at: datetime


# --- Athlete profile ----------------------------------------------------------
#
# Distances are metres and durations seconds throughout; the phone formats them
# in the athlete's units. Calendar groupings (weeks from Monday, months) are
# computed in the timezone the phone sends, so a run just after midnight lands
# on the day the athlete lived it.

GoalMetric = Literal["distance", "time", "runs"]


class AthleteTotals(BaseModel):
    runs: int
    distance_m: float
    moving_s: int
    elevation_gain_m: float


class FourWeekAverages(BaseModel):
    runs_per_week: float
    distance_m_per_week: float
    moving_s_per_week: float


class WeekBucket(BaseModel):
    week_start: date
    runs: int
    distance_m: float
    moving_s: int
    elevation_gain_m: float


class MonthBucket(BaseModel):
    month: str
    runs: int
    distance_m: float
    moving_s: int
    elevation_gain_m: float


class StreakSummary(BaseModel):
    """Consecutive weeks with at least one run. This week counts once run in."""

    current_weeks: int
    best_weeks: int
    current_since: date | None = None
    ran_this_week: bool


class BestEffortRecord(BaseModel):
    distance_m: int
    elapsed_s: float
    run_id: uuid.UUID
    started_at: datetime


class RunRecord(BaseModel):
    run_id: uuid.UUID
    started_at: datetime
    distance_m: float
    elevation_gain_m: float | None = None


class WeeklyGoalUpdate(BaseModel):
    """`target` is metres for distance, seconds for time, a count for runs."""

    metric: GoalMetric
    target: float = Field(gt=0, le=1_000_000)


class GoalProgress(BaseModel):
    metric: GoalMetric
    target: float
    value: float
    updated_at: datetime


class AthleteStats(BaseModel):
    timezone: str
    generated_at: datetime
    this_week: AthleteTotals
    this_month: AthleteTotals
    year_to_date: AthleteTotals
    all_time: AthleteTotals
    last_four_weeks: FourWeekAverages
    week_days_m: list[float]
    weeks: list[WeekBucket]
    months: list[MonthBucket]
    streak: StreakSummary
    best_efforts: list[BestEffortRecord]
    longest_run: RunRecord | None = None
    biggest_climb: RunRecord | None = None
    goal: GoalProgress | None = None
    territories_held: int
    territories_captured: int


class ShoeRef(BaseModel):
    id: uuid.UUID
    name: str


class RunSummary(BaseModel):
    run_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    distance_m: float
    moving_s: int
    elapsed_s: int
    elevation_gain_m: float | None = None
    # Null until the athlete names it; the phone titles it by time of day.
    title: str | None = None
    note: str | None = None
    shoe: ShoeRef | None = None
    captures: int = 0
    # Distances at which this run was the fastest yet when it was recorded.
    personal_records: list[int] = []
    temperature_c: float | None = None
    weather_code: int | None = None


class RunPage(BaseModel):
    runs: list[RunSummary]
    next_before: datetime | None = None


class RunSplit(BaseModel):
    index: int
    distance_m: float
    moving_s: float
    elevation_delta_m: float | None = None


class RunEffort(BaseModel):
    distance_m: int
    elapsed_s: float
    # 1-3 among every effort this athlete has run at the distance, else null.
    rank: int | None = None
    personal_record: bool = False


class RunActivity(BaseModel):
    summary: RunSummary
    splits: list[RunSplit]
    pace_series: list[tuple[float, float]]
    elevation_series: list[tuple[float, float]]
    best_efforts: list[RunEffort]
    elevation_loss_m: float | None = None
    calories: int | None = None


class RunAnnotationUpdate(BaseModel):
    """Only the fields sent change; send null to clear one."""

    title: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=1000)
    shoe_id: uuid.UUID | None = None


class AthleteSettingsRecord(BaseModel):
    weight_kg: float | None = Field(default=None, ge=25, le=300)


class ShoeRecord(BaseModel):
    id: uuid.UUID
    name: str
    is_default: bool
    retired: bool
    distance_m: float
    runs: int
    created_at: datetime


class ShoeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    is_default: bool = False


class ShoeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=48)
    is_default: bool | None = None
    retired: bool | None = None


class FriendProfile(BaseModel):
    """A friend's training, and nothing that places them: no routes, notes or shoes."""

    account: PublicAccount
    friends_since: datetime
    this_week: AthleteTotals
    year_to_date: AthleteTotals
    all_time: AthleteTotals
    weeks: list[WeekBucket]
    streak: StreakSummary
    best_efforts: list[BestEffortRecord]
    longest_run: RunRecord | None = None
    territories_held: int
    recent_runs: list[RunSummary]
