"""Every stage declares a complete, consistent contract.

These tests are what let Phase B rewrite stage bodies freely: if an
implementation quietly changes what a stage reads or writes, the chain breaks
here rather than three stages downstream.
"""

from __future__ import annotations

import pytest

from lib import artifacts
from lib.contracts import ArtifactSpec
from lib.registry import discover_stages, select_stages

STAGES = discover_stages()


def test_all_thirteen_stages_are_present():
    assert [s.number for s in STAGES] == list(range(1, 14))


def test_stage_names_are_unique():
    names = [s.name for s in STAGES]
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("stage", STAGES, ids=lambda s: s.name)
def test_every_stage_produces_something(stage):
    assert stage.produces, f"{stage.name} declares no outputs"
    assert all(isinstance(spec, ArtifactSpec) for spec in stage.produces)


@pytest.mark.parametrize("stage", [s for s in STAGES if s.number > 1], ids=lambda s: s.name)
def test_every_stage_after_the_first_requires_something(stage):
    # Stage 01's input is the region config, not a file. Everything else must
    # consume an upstream artifact, or it is not part of the chain.
    assert stage.requires, f"{stage.name} declares no inputs"


def test_inputs_are_produced_by_an_earlier_stage():
    """The dependency graph closes.

    A stage requiring something nothing produces would fail only at runtime,
    after however long the earlier stages take.
    """
    produced: set[str] = set()
    for stage in STAGES:
        for spec in stage.requires:
            assert spec.key in produced, (
                f"{stage.name} requires {spec.key!r}, which no earlier stage produces"
            )
        produced.update(spec.key for spec in stage.produces)


def test_no_artifact_is_produced_twice():
    seen: dict[str, str] = {}
    for stage in STAGES:
        for spec in stage.produces:
            assert spec.key not in seen, (
                f"{spec.key!r} is produced by both {seen[spec.key]} and {stage.name}"
            )
            seen[spec.key] = stage.name


def test_approval_marker_is_never_a_stage_output():
    """The human gate cannot be satisfied by the pipeline itself.

    If any stage produced APPROVED, human review would become a formality that
    a full run silently completes.
    """
    for stage in STAGES:
        assert artifacts.APPROVED not in stage.produces
        assert artifacts.APPROVED not in stage.requires
        assert artifacts.GAMEPLAY_APPROVED not in stage.produces
        assert artifacts.GAMEPLAY_APPROVED not in stage.requires


def test_publish_gates_on_human_approval():
    publish = next(s for s in STAGES if s.number == 9)
    assert artifacts.APPROVED in publish.module.GATES
    gameplay_review = next(s for s in STAGES if s.number == 12)
    assert artifacts.GAMEPLAY_APPROVED in gameplay_review.module.GATES


def test_artifact_keys_are_unique():
    keys = [spec.key for spec in artifacts.ALL_ARTIFACTS]
    assert len(set(keys)) == len(keys)


def test_artifact_paths_stay_inside_the_region_root(ctx):
    for spec in artifacts.ALL_ARTIFACTS:
        assert spec.path(ctx).is_relative_to(ctx.region_root)


def test_stage_selection_respects_range():
    selected = select_stages(STAGES, from_stage=4, to_stage=6)
    assert [s.number for s in selected] == [4, 5, 6]


def test_inverted_stage_range_is_rejected():
    with pytest.raises(ValueError):
        select_stages(STAGES, from_stage=7, to_stage=2)
