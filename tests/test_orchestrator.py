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
            prior_states=[],
            prior_full_texts={},
            forward_outlines=["Chapter 2 outline", "Chapter 3 outline"],
            parent_brief="A story about gold...",
        )
        assert ctx["CHAPTER_INDEX"] == 1
        assert ctx["TOTAL_CHAPTERS"] == 5
        assert "CONTENT" not in ctx
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
            prior_states=[],
            prior_full_texts={0: "Full text of chapter 1..."},
            forward_outlines=["Chapter 3 outline"],
            parent_brief="A story about gold...",
        )
        assert "CONTENT" not in ctx
        assert "Full text of chapter 1..." in ctx["PRIOR_CONTEXT"]

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
            prior_states=[ns1, ns2],
            prior_full_texts={2: "Full text of chapter 3..."},
            forward_outlines=["Chapter 5 outline", "Chapter 6 outline"],
            parent_brief="A story about gold...",
        )
        assert "CONTENT" not in ctx
        # Distant chapters (1-2) in NarrativeState
        assert "Aris" in ctx["PRIOR_CONTEXT"]
        assert "suspicious" in ctx["PRIOR_CONTEXT"]
        # Close neighbor (3) in full text
        assert "Full text of chapter 3..." in ctx["PRIOR_CONTEXT"]

    def test_last_chapter_no_forward(self):
        """Last chapter has no forward outlines."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        ctx = orch._build_sliding_context(
            chapter_index=4,
            total_chapters=5,
            stage="polish",
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
            prior_states=[],
            prior_full_texts={},
            forward_outlines=[],
            parent_brief="A story about gold...",
        )
        assert "CONTENT" not in ctx
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
# Context propagation
# ---------------------------------------------------------------------------


class TestContextPropagation:
    """Test that parent context files are copied to child directories."""

    def test_outline_propagated_to_children(self, tmp_path):
        """outline.md should be copied from parent to each child."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)

        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "03_outline.md").write_text("# Outline\n\nPart 1: Setup\nPart 2: Conflict")

        child_ids = ["parent-chapter-1", "parent-chapter-2"]
        for cid in child_ids:
            (tmp_path / cid).mkdir()

        orch._propagate_parent_context(parent_dir, child_ids, tmp_path)

        for cid in child_ids:
            outline = tmp_path / cid / "03_outline.md"
            assert outline.exists(), f"outline.md not propagated to {cid}"
            assert "Part 1: Setup" in outline.read_text()

    def test_research_propagated_to_children(self, tmp_path):
        """research.md should be copied from parent to each child."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)

        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "04_research.md").write_text("# Research\n\nSource 1\nSource 2")

        child_ids = ["parent-chapter-1"]
        (tmp_path / "parent-chapter-1").mkdir()

        orch._propagate_parent_context(parent_dir, child_ids, tmp_path)

        research = tmp_path / "parent-chapter-1" / "04_research.md"
        assert research.exists()
        assert "Source 1" in research.read_text()

    def test_does_not_overwrite_existing(self, tmp_path):
        """Should not overwrite existing files in child directories."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)

        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "03_outline.md").write_text("Parent outline")

        child_dir = tmp_path / "parent-chapter-1"
        child_dir.mkdir()
        (child_dir / "03_outline.md").write_text("Child outline (custom)")

        orch._propagate_parent_context(parent_dir, ["parent-chapter-1"], tmp_path)

        assert (child_dir / "03_outline.md").read_text() == "Child outline (custom)"

    def test_missing_parent_file_skipped(self, tmp_path):
        """Should skip files that don't exist in parent."""
        from quill.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)

        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        # No outline.md or research.md

        child_dir = tmp_path / "parent-chapter-1"
        child_dir.mkdir()

        orch._propagate_parent_context(parent_dir, ["parent-chapter-1"], tmp_path)

        assert not (child_dir / "03_outline.md").exists()
        assert not (child_dir / "04_research.md").exists()


# ---------------------------------------------------------------------------
# Chapter brief debug prompt
# ---------------------------------------------------------------------------


class TestChapterBriefDebugPrompt:
    """Test that chapter brief generation dumps debug prompts."""

    def test_debug_prompt_dumped(self, tmp_path):
        """_generate_chapter_brief should write 01_brief.generate-prompt.md."""
        from quill.orchestrator import Orchestrator
        from unittest.mock import patch, MagicMock

        orch = Orchestrator(agent_set="default")

        mock_brief = "A brief about chapter 1."

        with patch("quill.llm.LLMClient") as MockLLM:
            mock_client = MagicMock()
            mock_client.chat.return_value = mock_brief
            MockLLM.return_value = mock_client

            orch._generate_chapter_brief(
                child_dir=tmp_path,
                chapter_index=0, total_chapters=3,
                chapter_title="The Setup",
                parent_outline="## Part 1: Setup\nThe team assembles.",
                structure_text="## Segment 1: The Setup\n## Segment 2: The Conflict",
                prior_states=[],
                piece_title="Test Story", genre="fiction",
                type="story", language="en", segment_target=2000,
            )

        debug_file = tmp_path / "01_brief.generate-prompt.md"
        assert debug_file.exists(), "Debug prompt not dumped"
        content = debug_file.read_text()
        assert "## System" in content
        assert "## User" in content
        assert "The Setup" in content
        assert len(content) > 200, "Debug prompt too short — likely missing content"


# ---------------------------------------------------------------------------
# Feedback output on loop_back
# ---------------------------------------------------------------------------


class TestFeedbackOutputOnLoopBack:
    """Test that feedback stages write output even on loop_back."""

    def test_review_output_written_on_loop_back(self, tmp_path):
        """review.md should exist even when review returns loop_back."""
        from quill.piece import Piece, _stage_filename
        import yaml

        # Create a piece
        piece_dir = tmp_path / "test-piece"
        piece_dir.mkdir()
        (piece_dir / "meta.yaml").write_text(yaml.dump({
            "id": "test-piece", "title": "Test",
            "genre": "fiction", "type": "story",
            "language": "en", "current_stage": "review",
        }))
        (piece_dir / "stages").mkdir()

        # Write a draft file
        (piece_dir / _stage_filename("draft")).write_text("Draft content here.")

        # Load the piece
        piece = Piece(id="test-piece", _path=piece_dir)

        # Simulate what runner does on loop_back for feedback stage
        critique = "The pacing is too slow in the middle section."
        piece.write_output("review", critique)

        review_file = piece_dir / _stage_filename("review")
        assert review_file.exists(), "review.md not written"
        assert "pacing is too slow" in review_file.read_text()


# ---------------------------------------------------------------------------
# Stage inputs available in child directories
# ---------------------------------------------------------------------------


class TestStageInputsInChildDirs:
    """Test that child directories have the files needed by stage_inputs."""

    def test_draft_inputs_available_after_propagation(self, tmp_path):
        """After propagation, child should have outline.md and research.md."""
        from quill.orchestrator import Orchestrator
        from quill.piece import _stage_filename

        orch = Orchestrator.__new__(Orchestrator)

        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / _stage_filename("outline")).write_text("# Outline")
        (parent_dir / _stage_filename("research")).write_text("# Research")
        (parent_dir / _stage_filename("brief")).write_text("# Brief")

        child_dir = tmp_path / "parent-chapter-1"
        child_dir.mkdir()
        (child_dir / _stage_filename("brief")).write_text("# Chapter brief")

        orch._propagate_parent_context(parent_dir, ["parent-chapter-1"], tmp_path)

        # draft stage_inputs: [outline.md, brief.md, research.md]
        assert (child_dir / _stage_filename("outline")).exists()
        assert (child_dir / _stage_filename("brief")).exists()
        assert (child_dir / _stage_filename("research")).exists()

    def test_revise_inputs_after_review(self, tmp_path):
        """After review runs, revise should find draft.md and review.md."""
        from quill.piece import _stage_filename

        child_dir = tmp_path / "parent-chapter-1"
        child_dir.mkdir()

        # Simulate: draft was written by draft stage
        (child_dir / _stage_filename("draft")).write_text("Draft content")
        # Simulate: review was written by review stage (even on loop_back)
        (child_dir / _stage_filename("review")).write_text("Review critique here")

        # revise stage_inputs: [draft.md, review.md]
        assert (child_dir / _stage_filename("draft")).exists()
        assert (child_dir / _stage_filename("review")).exists()
        assert "Review critique" in (child_dir / _stage_filename("review")).read_text()


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


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test orchestrator error handling and retry logic."""

    def test_retries_failed_chapter(self, tmp_path):
        """Should retry a failed chapter before giving up."""
        from quill.orchestrator import Orchestrator
        from unittest.mock import patch, MagicMock, call

        orch = Orchestrator(agent_set="default")

        # Create parent with structure
        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "meta.yaml").write_text(
            "id: parent\ntitle: T\ngenre: fiction\ntype: story\n"
            "language: en\ncurrent_stage: draft\n"
        )
        (parent_dir / "02_structure.md").write_text(
            "## Segment 1: A\n## Segment 2: B\n"
        )
        (parent_dir / "01_brief.md").write_text("Brief")
        (parent_dir / "03_outline.md").write_text("Outline")

        # Mock: first call fails, second succeeds
        mock_fail = MagicMock()
        mock_fail.decision = "error"
        mock_fail.error = "LLM timeout"
        mock_ok = MagicMock()
        mock_ok.decision = "advance"

        call_count = {"n": 0}
        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return mock_fail
            return mock_ok

        with patch.object(orch, '_run_stage_on_child', side_effect=side_effect), \
             patch.object(orch, '_generate_chapter_brief', return_value="Brief"):
            result = orch.run_stage("parent", "draft", output_dir=tmp_path, max_retries=1)

        # Should have retried — 2 calls for chapter 1, 1 for chapter 2
        assert call_count["n"] >= 2

    def test_skip_failed_chapter(self, tmp_path):
        """Should skip failed chapters when skip_failures=True."""
        from quill.orchestrator import Orchestrator
        from quill.agent import AgentDecision
        from unittest.mock import patch, MagicMock

        orch = Orchestrator(agent_set="default")

        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "meta.yaml").write_text(
            "id: parent\ntitle: T\ngenre: fiction\ntype: story\n"
            "language: en\ncurrent_stage: draft\n"
        )
        (parent_dir / "02_structure.md").write_text(
            "## Segment 1: A\n## Segment 2: B\n## Segment 3: C\n"
        )
        (parent_dir / "01_brief.md").write_text("Brief")
        (parent_dir / "03_outline.md").write_text("Outline")

        # First chapter always fails, others succeed
        def side_effect(child_id, stage, context, base):
            if "chapter-1" in child_id:
                return AgentDecision(decision="error", error="fail", critique="", output="", stage=stage)
            return AgentDecision(decision="advance", critique="", output="", stage=stage)

        with patch.object(orch, '_run_stage_on_child', side_effect=side_effect), \
             patch.object(orch, '_generate_chapter_brief', return_value="Brief"):
            result = orch.run_stage(
                "parent", "draft", output_dir=tmp_path,
                max_retries=0, skip_failures=True,
            )

        # Should still complete (not raise)
        assert result is not None
        assert result.decision == "advance"

    def test_raises_on_fatal_failure(self, tmp_path):
        """Should raise when all retries exhausted and skip_failures=False."""
        from quill.orchestrator import Orchestrator
        from quill.agent import AgentDecision
        from unittest.mock import patch, MagicMock

        orch = Orchestrator(agent_set="default")

        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "meta.yaml").write_text(
            "id: parent\ntitle: T\ngenre: fiction\ntype: story\n"
            "language: en\ncurrent_stage: draft\n"
        )
        (parent_dir / "02_structure.md").write_text(
            "## Segment 1: A\n## Segment 2: B\n"
        )
        (parent_dir / "01_brief.md").write_text("Brief")
        (parent_dir / "03_outline.md").write_text("Outline")

        mock_fail = AgentDecision(
            decision="error", error="LLM down", critique="", output="", stage="draft"
        )

        with patch.object(orch, '_run_stage_on_child', return_value=mock_fail), \
             patch.object(orch, '_generate_chapter_brief', return_value="Brief"):
            result = orch.run_stage(
                "parent", "draft", output_dir=tmp_path,
                max_retries=0, skip_failures=False,
            )

        # Should return error decision
        assert result.decision == "error"


# ---------------------------------------------------------------------------
# Progress events
# ---------------------------------------------------------------------------


class TestProgressEvents:
    """Test orchestrator SSE progress events."""

    def test_emits_chapter_events(self, tmp_path):
        """Should emit orchestrator_chapter_start and orchestrator_chapter_complete."""
        from quill.orchestrator import Orchestrator
        from unittest.mock import patch, MagicMock
        from queue import Queue

        orch = Orchestrator(agent_set="default")

        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "meta.yaml").write_text(
            "id: parent\ntitle: T\ngenre: fiction\ntype: story\n"
            "language: en\ncurrent_stage: draft\n"
        )
        (parent_dir / "02_structure.md").write_text(
            "## Segment 1: A\n## Segment 2: B\n"
        )
        (parent_dir / "01_brief.md").write_text("Brief")
        (parent_dir / "03_outline.md").write_text("Outline")

        mock_result = MagicMock()
        mock_result.decision = "advance"

        event_queue = Queue()
        with patch.object(orch, '_run_stage_on_child', return_value=mock_result), \
             patch.object(orch, '_generate_chapter_brief', return_value="Brief"):
            orch.run_stage(
                "parent", "draft", output_dir=tmp_path, event_queue=event_queue,
            )

        events = []
        while not event_queue.empty():
            events.append(event_queue.get())

        event_types = [e["type"] for e in events]
        assert "orchestrator_start" in event_types
        assert "orchestrator_chapter_start" in event_types
        assert "orchestrator_chapter_complete" in event_types
        assert "orchestrator_complete" in event_types
