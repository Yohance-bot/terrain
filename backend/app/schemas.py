import uuid
from datetime import datetime
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
    provider: str | None = None
    is_mock: bool = False


class RunSubmission(BaseModel):
    run_id: uuid.UUID = Field(description="Client-generated; doubles as the idempotency key")
    started_at: datetime
    ended_at: datetime
    samples: list[GpsSample]
    source: RunSource = "tracked"


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
