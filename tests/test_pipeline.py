"""Tests for pipeline.py — stage transitions, progress, validation."""

import pytest
from pathlib import Path

import yaml

from quill.pipeline import Pipeline, Stage, load_pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline():
    """Load the real default pipeline."""
    return load_pipeline("default")


@pytest.fixture
def simple_pipeline():
    """A minimal 3-stage pipeline for focused tests."""
    stages = {
        "start": Stage(key="start", name="Start", next="middle", can_reject_to=[]),
        "middle": Stage(key="middle", name="Middle", next="end", can_reject_to=["start"]),
        "end": Stage(key="end", name="End", next=None, can_reject_to=["middle"]),
    }
    return Pipeline(
        name="simple",
        stages=stages,
        stage_order=["start", "middle", "end"],
    )


# ---------------------------------------------------------------------------
# Stage navigation
# ---------------------------------------------------------------------------


class TestStageNavigation:
    """Test next_stage, can_advance, and stage lookups."""

    def test_next_stage(self, simple_pipeline):
        assert simple_pipeline.next_stage("start") == "middle"
        assert simple_pipeline.next_stage("middle") == "end"
        assert simple_pipeline.next_stage("end") is None

    def test_can_advance(self, simple_pipeline):
        assert simple_pipeline.can_advance("start") is True
        assert simple_pipeline.can_advance("middle") is True
        assert simple_pipeline.can_advance("end") is False

    def test_get_stage(self, simple_pipeline):
        stage = simple_pipeline.get_stage("middle")
        assert stage is not None
        assert stage.name == "Middle"

    def test_get_nonexistent_stage(self, simple_pipeline):
        assert simple_pipeline.get_stage("nope") is None


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


class TestTransitions:
    """Test validate_transition logic."""

    def test_valid_advance(self, simple_pipeline):
        valid, msg = simple_pipeline.validate_transition("start", "middle")
        assert valid is True
        assert "Advancing" in msg

    def test_valid_reject(self, simple_pipeline):
        valid, msg = simple_pipeline.validate_transition("middle", "start")
        assert valid is True
        assert "Reverting" in msg

    def test_invalid_same_stage(self, simple_pipeline):
        valid, msg = simple_pipeline.validate_transition("middle", "middle")
        assert valid is False
        assert "Already at" in msg

    def test_invalid_unknown_target(self, simple_pipeline):
        valid, msg = simple_pipeline.validate_transition("start", "nope")
        assert valid is False
        assert "Unknown stage" in msg

    def test_invalid_skip_stage(self, simple_pipeline):
        """Can't skip from start directly to end."""
        valid, msg = simple_pipeline.validate_transition("start", "end")
        assert valid is False
        assert "Cannot transition" in msg

    def test_reject_targets(self, simple_pipeline):
        assert simple_pipeline.valid_reject_targets("middle") == ["start"]
        assert simple_pipeline.valid_reject_targets("start") == []
        assert simple_pipeline.valid_reject_targets("end") == ["middle"]


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


class TestProgress:
    """Test progress calculation."""

    def test_progress_first_stage(self, simple_pipeline):
        p = simple_pipeline.progress("start")
        assert p["current"] == "start"
        assert p["current_index"] == 0
        assert p["percent"] == 0
        assert p["next"] == "middle"
        assert p["total_stages"] == 3

    def test_progress_middle_stage(self, simple_pipeline):
        p = simple_pipeline.progress("middle")
        assert p["current_index"] == 1
        assert p["percent"] == 50

    def test_progress_final_stage(self, simple_pipeline):
        p = simple_pipeline.progress("end")
        assert p["current_index"] == 2
        assert p["percent"] == 100
        assert p["next"] is None

    def test_progress_unknown_stage(self, simple_pipeline):
        p = simple_pipeline.progress("nope")
        assert p["current_index"] == -1
        assert p["percent"] == 0

    def test_progress_reject_targets_are_lists(self, pipeline):
        """All reject targets should be lists, never bare strings."""
        for stage_key in pipeline.stage_order:
            p = pipeline.progress(stage_key)
            assert isinstance(p["can_reject_to"], list), f"{stage_key} reject targets not a list"


# ---------------------------------------------------------------------------
# Real pipeline loading
# ---------------------------------------------------------------------------


class TestDefaultPipeline:
    """Test the actual default workflow."""

    def test_loads_default(self, pipeline):
        assert pipeline.name == "default"
        assert len(pipeline.stages) == 12

    def test_stage_order(self, pipeline):
        expected = ["brief", "structure", "outline", "research", "draft", "review", "revise",
                     "humanize", "validate", "polish", "summary", "done"]
        assert pipeline.stage_order == expected

    def test_brief_leads_to_structure(self, pipeline):
        assert pipeline.next_stage("brief") == "structure"

    def test_done_is_terminal(self, pipeline):
        assert pipeline.next_stage("done") is None
        assert pipeline.can_advance("done") is False

    def test_review_can_reject_to_draft(self, pipeline):
        assert pipeline.can_reject_to("review", "draft") is True

    def test_validate_can_reject_to_humanize(self, pipeline):
        assert pipeline.can_reject_to("validate", "humanize") is True

    def test_summary_stage_exists(self, pipeline):
        """Summary stage should be in the pipeline."""
        stage = pipeline.get_stage("summary")
        assert stage is not None
        assert stage.name == "Summary"

    def test_summary_is_content_stage(self, pipeline):
        """Summary should use two-call (generate → evaluate) mode."""
        assert pipeline.is_content_stage("summary") is True

    def test_polish_next_is_summary(self, pipeline):
        """Polish should advance to summary, not done."""
        assert pipeline.next_stage("polish") == "summary"

    def test_summary_next_is_done(self, pipeline):
        """Summary should advance to done."""
        assert pipeline.next_stage("summary") == "done"

    def test_summary_can_reject_to_polish(self, pipeline):
        """Summary should be able to reject back to polish."""
        assert pipeline.can_reject_to("summary", "polish") is True

    def test_stage_order_includes_summary(self, pipeline):
        """Summary should be between polish and done in stage order."""
        expected = ["brief", "structure", "outline", "research", "draft", "review", "revise",
                     "humanize", "validate", "polish", "summary", "done"]
        assert pipeline.stage_order == expected

    def test_stage_count_with_summary(self, pipeline):
        """Pipeline should have 12 stages (including summary and structure)."""
        assert len(pipeline.stages) == 12

    def test_summary_stage_inputs(self, pipeline):
        """Summary stage should read polish.md as input."""
        assert "summary" in pipeline.stage_inputs
        assert "polish.md" in pipeline.stage_inputs["summary"]
