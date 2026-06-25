"""Tests for Piece stage state tracking and per-piece trigger.

Stage state is tracked in meta.yaml under stage_states:
    stage_states:
        brief: ready
        outline: ready
        draft: superseded
        review: empty

Trigger is per-piece in meta.yaml:
    trigger: manual | on_advance | auto
"""
import pytest
from pathlib import Path
import yaml

from quill.piece import Piece, load_piece, _stage_filename


# ---------------------------------------------------------------------------
# Stage state — read/write
# ---------------------------------------------------------------------------


class TestStageState:
    """Piece.get_stage_state / set_stage_state."""

    def test_default_state_is_empty(self, sample_piece):
        """Stages not in meta.yaml are 'empty' by default."""
        piece = load_piece(sample_piece)
        assert piece.get_stage_state("outline") == "empty"
        assert piece.get_stage_state("review") == "empty"

    def test_set_and_get_stage_state(self, sample_piece):
        """set_stage_state persists to meta.yaml, get_stage_state reads it."""
        piece = load_piece(sample_piece)
        piece.set_stage_state("brief", "ready")
        piece.set_stage_state("draft", "generating")

        # Reload from disk to verify persistence
        reloaded = load_piece(sample_piece)
        assert reloaded.get_stage_state("brief") == "ready"
        assert reloaded.get_stage_state("draft") == "generating"

    def test_set_stage_state_preserves_other_stages(self, sample_piece):
        """Setting one stage's state doesn't clobber others."""
        piece = load_piece(sample_piece)
        piece.set_stage_state("brief", "ready")
        piece.set_stage_state("outline", "ready")
        piece.set_stage_state("draft", "superseded")

        reloaded = load_piece(sample_piece)
        assert reloaded.get_stage_state("brief") == "ready"
        assert reloaded.get_stage_state("outline") == "ready"
        assert reloaded.get_stage_state("draft") == "superseded"

    def test_stage_state_in_to_dict(self, sample_piece):
        """to_dict() includes stage_states."""
        piece = load_piece(sample_piece)
        piece.set_stage_state("brief", "ready")
        d = piece.to_dict()
        assert "stage_states" in d
        assert d["stage_states"]["brief"] == "ready"


# ---------------------------------------------------------------------------
# Supersede
# ---------------------------------------------------------------------------


class TestSupersede:
    """Piece.supersede_from — marks later stages as superseded."""

    def test_supersede_marks_later_stages(self, sample_piece):
        """Stages after the given stage are marked superseded."""
        piece = load_piece(sample_piece)
        # Set up: brief=ready, outline=ready, draft=ready
        piece.set_stage_state("brief", "ready")
        piece.set_stage_state("outline", "ready")
        piece.set_stage_state("draft", "ready")

        # Supersede from outline — draft and everything after should be superseded
        piece.supersede_from("outline")

        reloaded = load_piece(sample_piece)
        assert reloaded.get_stage_state("brief") == "ready"
        assert reloaded.get_stage_state("outline") == "ready"  # the target stays
        assert reloaded.get_stage_state("draft") == "superseded"

    def test_supersede_resets_frontier(self, sample_piece):
        """supersede_from also resets current_stage to the given stage."""
        piece = load_piece(sample_piece)
        assert piece.current_stage == "draft"  # from fixture

        piece.supersede_from("outline")

        reloaded = load_piece(sample_piece)
        assert reloaded.current_stage == "outline"

    def test_supersede_clears_superseded_content(self, sample_piece):
        """Superseded stages have their content files cleared."""
        piece = load_piece(sample_piece)
        # draft.md exists in fixture
        draft_file = sample_piece / _stage_filename("draft")
        assert draft_file.exists()

        piece.supersede_from("outline")

        # draft.md should be gone or empty
        assert not draft_file.exists() or draft_file.read_text().strip() == ""

    def test_supersede_handles_empty_stages(self, sample_piece):
        """Superseding when later stages are already empty doesn't error."""
        piece = load_piece(sample_piece)
        # review doesn't exist in fixture — should be fine
        piece.supersede_from("brief")
        reloaded = load_piece(sample_piece)
        assert reloaded.get_stage_state("outline") == "superseded"


# ---------------------------------------------------------------------------
# Navigation guard
# ---------------------------------------------------------------------------


class TestCanNavigate:
    """Piece.can_navigate — checks if a stage is viewable."""

    def test_ready_stage_is_navigable(self, sample_piece):
        piece = load_piece(sample_piece)
        piece.set_stage_state("brief", "ready")
        assert piece.can_navigate("brief") is True

    def test_empty_stage_is_not_navigable(self, sample_piece):
        piece = load_piece(sample_piece)
        assert piece.can_navigate("humanize") is False

    def test_superseded_stage_is_navigable(self, sample_piece):
        """Superseded stages still have content — user can view them."""
        piece = load_piece(sample_piece)
        piece.set_stage_state("draft", "superseded")
        assert piece.can_navigate("draft") is True

    def test_generating_stage_is_navigable(self, sample_piece):
        """User can view a stage that's currently generating (e.g. partial output)."""
        piece = load_piece(sample_piece)
        piece.set_stage_state("draft", "generating")
        assert piece.can_navigate("draft") is True


# ---------------------------------------------------------------------------
# Per-piece trigger
# ---------------------------------------------------------------------------


class TestPieceTrigger:
    """Piece.trigger — per-piece trigger mode."""

    def test_default_trigger_is_on_advance(self, sample_piece):
        """Pieces default to on_advance when no trigger is set."""
        piece = load_piece(sample_piece)
        assert piece.trigger == "on_advance"

    def test_set_trigger_persists(self, sample_piece):
        piece = load_piece(sample_piece)
        piece.trigger = "manual"
        piece.save()

        reloaded = load_piece(sample_piece)
        assert reloaded.trigger == "manual"

    def test_trigger_in_to_dict(self, sample_piece):
        piece = load_piece(sample_piece)
        piece.trigger = "auto"
        d = piece.to_dict()
        assert d["trigger"] == "auto"

    def test_trigger_from_meta_yaml(self, tmp_output):
        """Trigger is read from meta.yaml on load."""
        piece_dir = tmp_output / "trigger-test"
        piece_dir.mkdir()
        meta = {
            "id": "trigger-test",
            "title": "Trigger Test",
            "current_stage": "brief",
            "trigger": "auto",
        }
        (piece_dir / "meta.yaml").write_text(
            yaml.dump(meta, default_flow_style=False), encoding="utf-8",
        )
        (piece_dir / _stage_filename("brief")).write_text(
            "---\nid: trigger-test\n---\n\nBrief content.", encoding="utf-8",
        )

        piece = load_piece(piece_dir)
        assert piece.trigger == "auto"
