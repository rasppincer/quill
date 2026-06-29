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


# ---------------------------------------------------------------------------
# Chapter extraction from structure output
# ---------------------------------------------------------------------------


class TestExtractChapters:
    """Test extracting chapter list from structure output."""

    def test_extract_segment_headers(self):
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        structure_text = """---
id: test-piece
---

## Segment 1: The Setup
## Segment 2: The Training
## Segment 3: The Heist"""
        chapters = orch._extract_chapters(structure_text)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "The Setup"
        assert chapters[1]["title"] == "The Training"
        assert chapters[2]["title"] == "The Heist"

    def test_extract_part_headers(self):
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        structure_text = """## Part 1: Beginning
## Part 2: Middle
## Part 3: End"""
        chapters = orch._extract_chapters(structure_text)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "Beginning"

    def test_extract_empty(self):
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        assert orch._extract_chapters("") == []
        assert orch._extract_chapters(None) == []

    def test_extract_with_frontmatter(self):
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        structure_text = """---
id: test
current_stage: structure
---

## Segment 1: Alpha
## Segment 2: Beta"""
        chapters = orch._extract_chapters(structure_text)
        assert len(chapters) == 2
        assert chapters[0]["title"] == "Alpha"


# ---------------------------------------------------------------------------
# has_chapters detection
# ---------------------------------------------------------------------------


class TestHasChapters:
    """Test detecting whether a piece has chapters."""

    def test_has_chapters_with_structure_file(self, tmp_path):
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        piece_dir = tmp_path / "test-piece"
        piece_dir.mkdir()
        # Write meta.yaml
        (piece_dir / "meta.yaml").write_text(
            "id: test-piece\ntitle: Test\ncurrent_stage: draft\n"
        )
        # Write structure file
        (piece_dir / "02_structure.md").write_text(
            "## Segment 1: A\n## Segment 2: B\n## Segment 3: C\n"
        )
        assert orch._has_chapters(piece_dir) is True

    def test_no_chapters_without_structure(self, tmp_path):
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        piece_dir = tmp_path / "test-piece"
        piece_dir.mkdir()
        (piece_dir / "meta.yaml").write_text(
            "id: test-piece\ntitle: Test\ncurrent_stage: draft\n"
        )
        assert orch._has_chapters(piece_dir) is False

    def test_no_chapters_single_segment(self, tmp_path):
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        piece_dir = tmp_path / "test-piece"
        piece_dir.mkdir()
        (piece_dir / "meta.yaml").write_text(
            "id: test-piece\ntitle: Test\ncurrent_stage: draft\n"
        )
        (piece_dir / "02_structure.md").write_text(
            "## Segment 1: The Only Chapter\n"
        )
        assert orch._has_chapters(piece_dir) is False  # single segment = not chaptered


# ---------------------------------------------------------------------------
# Orchestrator.run_stage — high-level flow
# ---------------------------------------------------------------------------


class TestOrchestratorRunStage:
    """Test the orchestrator's stage execution flow."""

    def test_returns_none_for_non_chaptered_piece(self, tmp_path):
        """Orchestrator should return None for single-chapter pieces."""
        from quill.orchestrator import Orchestrator
        from quill.piece import Piece
        orch = Orchestrator(agent_set="default")
        # Create a piece without structure file
        piece_dir = tmp_path / "single-piece"
        piece_dir.mkdir()
        (piece_dir / "meta.yaml").write_text(
            "id: single-piece\ntitle: Test\ncurrent_stage: draft\n"
        )
        result = orch.run_stage("single-piece", "draft", output_dir=tmp_path)
        assert result is None

    def test_returns_none_when_no_chapters_in_structure(self, tmp_path):
        """Orchestrator should return None when structure has only 1 segment."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator(agent_set="default")
        piece_dir = tmp_path / "single-seg"
        piece_dir.mkdir()
        (piece_dir / "meta.yaml").write_text(
            "id: single-seg\ntitle: Test\ncurrent_stage: draft\n"
        )
        (piece_dir / "02_structure.md").write_text(
            "## Segment 1: Only Chapter\n"
        )
        result = orch.run_stage("single-seg", "draft", output_dir=tmp_path)
        assert result is None

    def test_creates_child_pieces(self, tmp_path):
        """Orchestrator should create child pieces for each chapter."""
        from quill.orchestrator import Orchestrator
        from unittest.mock import patch, MagicMock
        orch = Orchestrator(agent_set="default")
        # Create parent piece with structure
        parent_dir = tmp_path / "parent-piece"
        parent_dir.mkdir()
        (parent_dir / "meta.yaml").write_text(
            "id: parent-piece\ntitle: Test Story\ngenre: fiction\ntype: story\n"
            "language: en\ncurrent_stage: draft\n"
        )
        (parent_dir / "02_structure.md").write_text(
            "## Segment 1: The Setup\n## Segment 2: The Conflict\n## Segment 3: The Resolution\n"
        )
        (parent_dir / "01_brief.md").write_text(
            "---\nid: parent-piece\n---\n\nA story about a heist gone wrong."
        )
        (parent_dir / "03_outline.md").write_text(
            "---\nid: parent-piece\n---\n\n## Part 1: The Setup\nThe team assembles.\n"
            "## Part 2: The Conflict\nThings go wrong.\n## Part 3: The Resolution\nEscape.\n"
        )
        # Mock _run_stage_on_child to avoid LLM calls for stage execution
        mock_result = MagicMock()
        mock_result.decision = "advance"
        with patch.object(orch, '_run_stage_on_child', return_value=mock_result):
            orch.run_stage("parent-piece", "draft", output_dir=tmp_path)
        # Verify children were created
        children = list(tmp_path.glob("parent-piece-chapter-*"))
        assert len(children) == 3
        # Verify child meta.yaml files
        for child_dir in children:
            meta_file = child_dir / "meta.yaml"
            assert meta_file.exists()
            import yaml
            meta = yaml.safe_load(meta_file.read_text())
            assert meta["parent"] == "parent-piece"
            assert meta["trigger"] == "auto"


# ---------------------------------------------------------------------------
# Assembly — concatenate per-chapter results into parent stage file
# ---------------------------------------------------------------------------


class TestAssembly:
    """Test concatenating per-chapter outputs into parent stage file."""

    def test_assemble_stage_outputs(self, tmp_path):
        """Should concatenate chapter outputs into parent's stage file."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)

        # Create 3 child directories with stage output
        for i in range(3):
            child_dir = tmp_path / f"parent-chapter-{i + 1}"
            child_dir.mkdir()
            (child_dir / "05_draft.md").write_text(
                f"---\nid: parent-chapter-{i + 1}\n---\n\nChapter {i + 1} draft content."
            )

        child_ids = ["parent-chapter-1", "parent-chapter-2", "parent-chapter-3"]
        orch._assemble_outputs(child_ids, "draft", tmp_path)

        # Verify parent's stage file (written to base/parent/)
        parent_file = tmp_path / "parent" / "05_draft.md"
        assert parent_file.exists()
        content = parent_file.read_text()
        assert "Chapter 1 draft content." in content
        assert "Chapter 2 draft content." in content
        assert "Chapter 3 draft content." in content

    def test_assemble_empty_children(self, tmp_path):
        """Assembly with no children should not create a file."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        orch._assemble_outputs([], "draft", tmp_path)
        assert not (tmp_path / "parent" / "05_draft.md").exists()

    def test_assemble_missing_child_file(self, tmp_path):
        """Assembly should skip children without the stage file."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)

        # Child 1 has output, child 2 does not
        child1 = tmp_path / "parent-chapter-1"
        child1.mkdir()
        (child1 / "05_draft.md").write_text("Chapter 1 content.")

        child2 = tmp_path / "parent-chapter-2"
        child2.mkdir()
        # No draft.md

        orch._assemble_outputs(
            ["parent-chapter-1", "parent-chapter-2"], "draft", tmp_path,
        )
        parent_file = tmp_path / "parent" / "05_draft.md"
        assert parent_file.exists()
        content = parent_file.read_text()
        assert "Chapter 1 content." in content


# ---------------------------------------------------------------------------
# Chapter brief generator
# ---------------------------------------------------------------------------


class TestChapterBriefGenerator:
    """Test auto-generating chapter briefs."""

    def test_generate_brief_writes_file(self, tmp_path):
        """Should write a brief.md file for a child piece."""
        from quill.orchestrator import Orchestrator
        from unittest.mock import patch, MagicMock

        orch = Orchestrator(agent_set="default")

        # Mock the LLM client to return a brief
        mock_brief = (
            "# Chapter 1: The Setup\n\n"
            "Dr. Aris arrives at the lab to find the anomaly data has changed. "
            "The readings show a pattern that shouldn't exist. Elena is missing "
            "from the morning shift — no one has heard from her since yesterday."
        )

        with patch("quill.llm.LLMClient") as MockLLM:
            mock_client = MagicMock()
            mock_client.chat.return_value = mock_brief
            MockLLM.return_value = mock_client

            orch._generate_chapter_brief(
                child_dir=tmp_path,
                chapter_index=0,
                total_chapters=3,
                chapter_title="The Setup",
                parent_outline="## Part 1: The Setup\nThe team assembles.\n## Part 2: The Conflict\nThings go wrong.",
                structure_text="## Segment 1: The Setup\n## Segment 2: The Conflict\n## Segment 3: The Resolution",
                prior_states=[],
                piece_title="Test Story",
                genre="fiction",
                type="story",
                language="en",
                segment_target=2000,
            )

        brief_file = tmp_path / "01_brief.md"
        assert brief_file.exists()
        content = brief_file.read_text()
        assert "Dr. Aris" in content

    def test_generate_brief_includes_prior_context(self, tmp_path):
        """Second chapter's brief should include NarrativeState from chapter 1."""
        from quill.orchestrator import Orchestrator
        from quill.narrative_state import NarrativeState
        from unittest.mock import patch, MagicMock

        orch = Orchestrator(agent_set="default")
        ns = NarrativeState(
            characters=[{"name": "Aris", "state": "suspicious"}],
            tone="tense",
            key_events=["Aris found the pattern"],
        )

        mock_brief = "Chapter 2 brief with Aris context."

        with patch("quill.llm.LLMClient") as MockLLM:
            mock_client = MagicMock()
            mock_client.chat.return_value = mock_brief
            MockLLM.return_value = mock_client

            orch._generate_chapter_brief(
                child_dir=tmp_path,
                chapter_index=1,
                total_chapters=3,
                chapter_title="The Conflict",
                parent_outline="## Part 1: Setup\n## Part 2: Conflict\n## Part 3: Resolution",
                structure_text="## Segment 1: Setup\n## Segment 2: Conflict\n## Segment 3: Resolution",
                prior_states=[ns],
                piece_title="Test Story",
                genre="fiction",
                type="story",
                language="en",
                segment_target=2000,
            )

        # Verify the LLM was called with prior context
        call_args = mock_client.chat.call_args
        prompt = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("prompt", "")
        assert "suspicious" in prompt or "Aris" in prompt

    def test_brief_prompt_template_exists(self):
        """All 3 flavors should have chapter_brief.prompt.md."""
        from pathlib import Path
        for flavor in ["default", "fiction", "non-fiction"]:
            path = Path(f"agents/{flavor}/chapter_brief.prompt.md")
            assert path.exists(), f"Missing {path}"
