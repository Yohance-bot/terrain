"""Phase 1 persistence: raw route evidence, an influence ledger, and derived standings."""

import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.db import Base


class Territory(Base):
    __tablename__ = "territories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    area: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # Spatial indexes are created explicitly in the migration rather than implicitly
    # by GeoAlchemy2, so the schema is fully described by the migration files.
    geom: Mapped[object] = mapped_column(
        Geography(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("slug", "version", name="uq_territory_slug_version"),)


class Device(Base):
    """Stands in for a user. This is not an account.

    No authentication, no recovery, no profile. It exists only so two testers can
    contest the same territory. Replaced wholesale when accounts arrive.
    """

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # This prototype has no account identity. On device-scoped deletion, the
    # opaque device pseudonym remains only in immutable gameplay ledgers while
    # this marker and label removal sever the personal/device profile surface.
    privacy_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceProfile(Base):
    """Device-scoped personal progression and Home selection.

    This remains deliberately separate from territory standings: Home is a
    personal attachment and cannot create ownership or alter influence.
    """

    __tablename__ = "device_profiles"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    home_territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id"), nullable=True, index=True
    )
    home_selected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    home_change_available_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    home_selection_source: Mapped[str | None] = mapped_column(String(24), nullable=True)
    home_selection_note: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Account(Base):
    """A player identity layered on top of the existing immutable device ledgers."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    display_name: Mapped[str] = mapped_column(String(32), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="player")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountAuthMethod(Base):
    """Provider subjects are global and are never exposed in public standings."""

    __tablename__ = "account_auth_methods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_account_auth_provider_subject"),
    )


class DeviceLink(Base):
    """Current account for a device; gameplay continues to use device ids."""

    __tablename__ = "device_links"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), primary_key=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountDeletionRequest(Base):
    """Logged request; deletion execution remains deliberately out of scope."""

    __tablename__ = "account_deletion_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    __tablename__ = "runs"

    # Client-generated, which makes it the idempotency key for submission.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)

    # Server-computed. The client never asserts distance (`05` Principle 1).
    distance_m: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    # One row per route, not one row per GPS point.
    geom: Mapped[object] = mapped_column(
        Geography(geometry_type="LINESTRING", srid=4326, spatial_index=False), nullable=True
    )
    sample_ts: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger), nullable=True)
    sample_accuracy_m: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)

    # Retained in full. These traces are the dataset for designing the real
    # route-matching algorithm, which `03` leaves open. The retention service
    # replaces this value with an empty object after the policy window.
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw_trace_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    route_reduced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="submitted")
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="tracked")
    pipeline_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The current prototype still uses raw cumulative distance, but the rules that
    # interpret a run need their own version once influence replaces that rule.
    # `pipeline_version` remains the route-matching implementation version.
    ruleset_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=settings.ruleset_version
    )
    # A monotonic counter for lifecycle transitions. The transition history lives
    # in `run_lifecycle_events`; this value supports cheap optimistic checks later.
    lifecycle_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_runs_review_queue", "device_id", "status", "created_at"),
    )


class RunLifecycleEvent(Base):
    """Append-only record of a run state transition.

    The synchronous prototype does not write these events yet, so adding this
    table deliberately does not alter submission semantics. The future worker
    must write an event in the same transaction as each state change.
    """

    __tablename__ = "run_lifecycle_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    # These fields intentionally do not reference an authentication table. S0
    # still has only locally trusted devices; an identity provider can later map
    # its stable subject to actor_ref without changing this audit history.
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_run_lifecycle_sequence"),)


class ConfigurationRevision(Base):
    """Versioned, auditable configuration payload for future game/processing rules.

    S0 persists revisions but intentionally does not provide an admin mutation
    path. Local scripts can create revisions with a `system` actor until account
    and role-based access work is introduced.
    """

    __tablename__ = "configuration_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    created_by_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    created_by_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("namespace", "version", name="uq_configuration_namespace_version"),
        Index("ix_configuration_revisions_namespace_status", "namespace", "status"),
    )


class AuditEvent(Base):
    """Append-only operational audit event for future console and scripted actions."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_audit_events_target", "target_type", "target_ref"),
        Index("ix_audit_events_created_at", "created_at"),
    )


class RunTerritorySegment(Base):
    """Append-only. Never updated, never deleted.

    Every standing in the game is derived from these rows, so a change to matching
    logic is a reprocess rather than a data loss.
    """

    __tablename__ = "run_territory_segments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True
    )
    territory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id"), nullable=False, index=True
    )
    territory_version: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    seconds_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Whether this run is what took the territory. Recorded at the moment it happens
    # so the post-run reveal can be replayed later without re-deriving history.
    caused_ownership_change: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # `loop` means this territory was included by a server-validated enclosed
    # area, rather than only by a route segment clipping through its boundary.
    capture_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TerritoryStanding(Base):
    """Derived cache. Truncating this table loses nothing.

    `total_distance_m` remains only for the established M1 map-state response.
    Ownership is derived solely from decayed active influence.
    """

    __tablename__ = "territory_standings"

    territory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id"), primary_key=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), primary_key=True
    )
    total_distance_m: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    active_influence: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False, default=0)
    legacy_influence: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InfluenceGrant(Base):
    """Append-only server-issued contribution to a territory's two ledgers."""

    __tablename__ = "influence_grants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True
    )
    territory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id"), nullable=False, index=True
    )
    territory_version: Mapped[int] = mapped_column(Integer, nullable=False)
    pipeline_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ruleset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    activity: Mapped[str] = mapped_column(String(16), nullable=False)
    distance_m: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    moving_time_s: Mapped[int] = mapped_column(Integer, nullable=False)
    effort: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False)
    active_influence: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False)
    legacy_influence: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False)
    half_life_days: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("run_id", "territory_id", name="uq_influence_grant_run_territory"),
        Index(
            "ix_influence_grants_territory_device_granted",
            "territory_id",
            "device_id",
            "granted_at",
        ),
    )


class TerritoryOwnership(Base):
    __tablename__ = "territory_ownership"

    territory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id"), primary_key=True
    )
    owner_device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True
    )
    previous_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True
    )
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CapturedArea(Base):
    """A public, player-created loop area independent of fixed territories."""

    __tablename__ = "captured_areas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, unique=True, index=True
    )
    owner_device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True
    )
    geom: Mapped[object] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=False), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
