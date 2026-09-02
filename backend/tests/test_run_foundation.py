"""Contract tests for S0 persistence shapes without requiring an auth provider."""

import uuid

import pytest
from pydantic import ValidationError

from app.models import AuditEvent, ConfigurationRevision, Run, RunLifecycleEvent
from app.schemas import AuditEventRecord, ConfigurationRevisionDraft, RunLifecycleEventRecord


def test_run_retains_legacy_processing_version_and_new_ruleset_version():
    columns = Run.__table__.c

    assert "pipeline_version" in columns
    assert columns["ruleset_version"].default.arg == 1
    assert columns["lifecycle_version"].default.arg == 1
    assert columns["processed_at"].nullable is True


def test_lifecycle_events_are_ordered_per_run():
    constraints = {constraint.name for constraint in RunLifecycleEvent.__table__.constraints}

    assert "uq_run_lifecycle_sequence" in constraints
    assert RunLifecycleEvent.__table__.c.run_id.index is True


def test_configuration_revisions_are_versioned_and_auditable():
    constraints = {constraint.name for constraint in ConfigurationRevision.__table__.constraints}

    assert "uq_configuration_namespace_version" in constraints
    assert ConfigurationRevision.__table__.c.payload.nullable is False
    assert ConfigurationRevision.__table__.c.created_by_kind.default.arg == "system"


def test_audit_event_retains_actor_target_and_before_after_states():
    columns = AuditEvent.__table__.c

    required = {
        "actor_kind",
        "action",
        "target_type",
        "target_ref",
        "before_state",
        "after_state",
    }
    assert required <= set(columns.keys())
    assert columns["target_ref"].nullable is False


def test_provider_neutral_schema_records_accept_local_actor_references():
    lifecycle = RunLifecycleEventRecord(
        sequence=1,
        to_status="submitted",
        actor_kind="device",
        actor_ref=str(uuid.uuid4()),
    )
    revision = ConfigurationRevisionDraft(
        namespace="run_rules",
        version=1,
        payload={"minimum_presence_m": 100},
    )
    audit = AuditEventRecord(
        actor_kind="system",
        action="configuration.created",
        target_type="configuration_revision",
        target_ref="run_rules:1",
        after_state=revision.model_dump(mode="json"),
    )

    assert lifecycle.actor_kind == "device"
    assert revision.status == "draft"
    assert audit.after_state is not None


def test_lifecycle_schema_rejects_unknown_states():
    with pytest.raises(ValidationError):
        RunLifecycleEventRecord(sequence=1, to_status="unknown")
