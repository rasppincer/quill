"""Tests for orchestrator.py — per-stage, per-chapter execution with sliding context."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from quill.narrative_state import NarrativeState


# ---------------------------------------------------------------------------
# Sliding context assembly
# ---------------------------------------------------------------------------


class TestSlidingContext:
    """Test the sliding context window assembly."""

    def test_first_chapter_minimal_context(self):
        """Chapter 1 has no prior chapters — only parent context + forward outlines."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        ctx = orch._build_sliding_context(
            chapter_index=0,
            total_chapters=5,
            stage="draft",
            chapter_content="Chapter 1 content...",
            prior_states=[],
            prior_full_texts={},
            forward_outlines=["Chapter 2 outline", "Chapter 3 outline"],
            parent_brief="A story about gold...",
        )
        assert ctx["CHAPTER_INDEX"] == 1
        assert ctx["TOTAL_CHAPTERS"] == 5
        assert "Chapter 1 content..." in ctx["CONTENT"]
        assert ctx["PRIOR_CONTEXT"] == ""
        assert "Chapter 2 outline" in ctx["FORWARD_OUTLINES"]

    def test_second_chapter_gets_full_text(self):
        """Chapter 2 gets chapter 1's full text (close neighbor)."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        ctx = orch._build_sliding_context(
            chapter_index=1,
            total_chapters=5,
            stage="revise",
            chapter_content="Chapter 2 content...",
            prior_states=[],
            prior_full_texts={0: "Full text of chapter 1..."},
            forward_outlines=["Chapter 3 outline"],
            parent_brief="A story about gold...",
        )
        assert "Full text of chapter 1..." in ctx["PRIOR_CONTEXT"]
        assert "Chapter 2 content..." in ctx["CONTENT"]

    def test_far_chapter_gets_narrative_state(self):
        """Chapter 4 gets NarrativeState for chapters 1-2, full text for chapter 3."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        ns1 = NarrativeState(
            characters=[{"name": "Aris", "state": "curious"}],
            tone="tense",
            key_events=["Discovery"],
        )
        ns2 = NarrativeState(
            characters=[{"name": "Aris", "state": "suspicious"}],
            tone="tense, paranoid",
            key_events=["Aris found pattern"],
        )
        ctx = orch._build_sliding_context(
            chapter_index=3,
            total_chapters=6,
            stage="humanize",
            chapter_content="Chapter 4 content...",
            prior_states=[ns1, ns2],
            prior_full_texts={2: "Full text of chapter 3..."},
            forward_outlines=["Chapter 5 outline", "Chapter 6 outline"],
            parent_brief="A story about gold...",
        )
        # Distant chapters (1-2) in NarrativeState
        assert "Aris" in ctx["PRIOR_CONTEXT"]
        assert "suspicious" in ctx["PRIOR_CONTEXT"]
        # Close neighbor (3) in full text
        assert "Full text of chapter 3..." in ctx["PRIOR_CONTEXT"]
        # Current chapter
        assert "Chapter 4 content..." in ctx["CONTENT"]

    def test_last_chapter_no_forward(self):
        """Last chapter has no forward outlines."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        ctx = orch._build_sliding_context(
            chapter_index=4,
            total_chapters=5,
            stage="polish",
            chapter_content="Chapter 5 content...",
            prior_states=[],
            prior_full_texts={3: "Full text of chapter 4..."},
            forward_outlines=[],
            parent_brief="A story about gold...",
        )
        assert ctx["FORWARD_OUTLINES"] == ""

    def test_state_stage_context(self):
        """State stage gets standard context (same as other stages)."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        ctx = orch._build_sliding_context(
            chapter_index=0,
            total_chapters=3,
            stage="state",
            chapter_content="Polished chapter 1...",
            prior_states=[],
            prior_full_texts={},
            forward_outlines=[],
            parent_brief="A story about gold...",
        )
        assert "Polished chapter 1..." in ctx["CONTENT"]


# ---------------------------------------------------------------------------
# Forward outline extraction
# ---------------------------------------------------------------------------


class TestForwardOutlines:
    """Test extracting outline sketches for forward chapters."""

    def test_extract_forward_outlines(self):
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        structure_text = """## Segment 1: The Setup
## Segment 2: The Training
## Segment 3: The Heist
## Segment 4: The Escape
## Segment 5: The Retirement"""
        outlines = orch._extract_forward_outlines(structure_text, current_index=1, lookahead=2)
        assert len(outlines) == 2
        assert "The Heist" in outlines[0]
        assert "The Escape" in outlines[1]

    def test_extract_near_end(self):
        """Near the end, fewer forward outlines."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        structure_text = """## Segment 1: A
## Segment 2: B
## Segment 3: C"""
        outlines = orch._extract_forward_outlines(structure_text, current_index=2, lookahead=2)
        assert len(outlines) == 0  # no segments after index 2

    def test_extract_empty_structure(self):
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        outlines = orch._extract_forward_outlines("", current_index=0, lookahead=2)
        assert outlines == []
