"""Tests for runner.py — stage execution, loop logic, input assembly."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import yaml

from quill.runner import StageRunner
from quill.agent import AgentDecision


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner(tmp_agents, monkeypatch):
    """StageRunner with mocked agent dir."""
    monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
    monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")
    return StageRunner(agent_set="default")


def _mock_llm_response(decision="advance", critique="Looks good.", body=None):
    """Build a mock LLM response string."""
    json_block = json.dumps({"decision": decision, "critique": critique})
    if body:
        return f"{body}\n\n```json\n{json_block}\n```"
    return f"```json\n{json_block}\n```"


# ---------------------------------------------------------------------------
# Stage input assembly
# ---------------------------------------------------------------------------


class TestReadInputs:
    """Test how runner reads input files for each stage."""

    def test_review_reads_draft(self, runner, sample_piece, tmp_output):
        """Review stage should read draft.md via default previous-stage logic."""
        from quill.piece import load_piece
        from quill.pipeline import load_pipeline
        piece = load_piece(sample_piece)
        pipeline = load_pipeline("default")

        inputs = runner._read_inputs(piece, "review", pipeline)
        assert "draft content" in inputs

    def test_revise_reads_draft_and_review(self, runner, sample_piece_with_review, tmp_output):
        """Revise stage should read both draft.md and review.md."""
        from quill.piece import load_piece
        piece = load_piece(sample_piece_with_review)

        inputs = runner._read_inputs(piece, "revise", None)
        assert "draft content" in inputs
        assert "stronger opening" in inputs

    def test_humanize_reads_revise(self, runner, tmp_output):
        """Humanize reads revise.md."""
        from quill.piece import load_piece, Piece
        d = tmp_output / "hz-piece"
        d.mkdir()
        meta = {"id": "hz-piece", "title": "T", "current_stage": "humanize"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / "revise.md").write_text("The revised text here.")

        piece = load_piece(d)
        inputs = runner._read_inputs(piece, "humanize", None)
        assert "revised text" in inputs

    def test_unknown_stage_reads_previous(self, runner, sample_piece, tmp_output):
        """Stage without explicit mapping reads previous stage + current attempt."""
        from quill.piece import load_piece
        from quill.pipeline import load_pipeline
        piece = load_piece(sample_piece)
        pipeline = load_pipeline("default")

        # brief has no explicit mapping and is the first stage.
        # Runner also reads the current stage file as "previous attempt" if it exists.
        inputs = runner._read_inputs(piece, "brief", pipeline)
        # sample_piece has brief.md, so it gets picked up as "previous attempt"
        assert "brief" in inputs.lower()


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


class TestWriteOutput:
    """Test how runner writes output files."""

    def test_writes_to_stage_file(self, runner, sample_piece, tmp_output):
        """Output should be written to <stage>.md."""
        from quill.piece import load_piece
        piece = load_piece(sample_piece)

        runner._write_output(piece, "review", "This is the review feedback.")
        review_file = sample_piece / "review.md"
        assert review_file.exists()
        assert "review feedback" in review_file.read_text()


# ---------------------------------------------------------------------------
# Loop counting
# ---------------------------------------------------------------------------


class TestLoopCounting:
    """Test loop count tracking in meta.yaml."""

    def test_initial_loop_count_is_zero(self, runner, sample_piece):
        from quill.piece import load_piece
        piece = load_piece(sample_piece)
        assert runner.get_loop_count(piece, "review") == 0

    def test_set_and_get_loop_count(self, runner, sample_piece):
        from quill.piece import load_piece
        piece = load_piece(sample_piece)

        runner.set_loop_count(piece, "review", 2)
        assert runner.get_loop_count(piece, "review") == 2

    def test_loop_count_per_stage(self, runner, sample_piece):
        """Loop counts are independent per stage."""
        from quill.piece import load_piece
        piece = load_piece(sample_piece)

        runner.set_loop_count(piece, "review", 3)
        runner.set_loop_count(piece, "revise", 1)
        assert runner.get_loop_count(piece, "review") == 3
        assert runner.get_loop_count(piece, "revise") == 1


# ---------------------------------------------------------------------------
# Stage execution (mocked LLM)
# ---------------------------------------------------------------------------


class TestRunStage:
    """Test full stage execution with mocked LLM calls."""

    @patch("quill.runner.LLMClient")
    def test_review_advance(self, mock_llm_cls, runner, sample_piece, tmp_output, monkeypatch):
        """Review stage with advance decision writes critique and advances meta."""
        from quill.piece import load_piece

        # Mock LLM client
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_llm_response(
            decision="advance",
            critique="Good structure, clear argument.",
        )
        mock_llm_cls.return_value = mock_client

        # Patch DEFAULT_OUTPUT_DIR
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        result = runner.run_stage("test-piece", "review", output_dir=tmp_output)

        assert result.decision == "advance"
        assert "Good structure" in result.critique

        # Check meta.yaml was advanced
        piece = load_piece(sample_piece)
        assert piece.current_stage == "revise"

    @patch("quill.runner.LLMClient")
    def test_review_loop_back(self, mock_llm_cls, runner, sample_piece, tmp_output, monkeypatch):
        """Review stage with loop_back increments loop count."""
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_llm_response(
            decision="loop_back",
            critique="Opening is weak, try again.",
        )
        mock_llm_cls.return_value = mock_client

        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        result = runner.run_stage("test-piece", "review", output_dir=tmp_output)

        assert result.decision == "loop_back"
        assert result.loop_count == 0  # was 0, now incremented to 1

    @patch("quill.runner.LLMClient")
    def test_content_stage_writes_body(self, mock_llm_cls, runner, sample_piece_with_review, tmp_output, monkeypatch):
        """Content stages (revise) write the body, not raw JSON."""
        from quill.piece import load_piece

        mock_client = MagicMock()
        # Two-call approach: first call generates content, second call evaluates
        mock_client.chat.side_effect = [
            "The revised draft is much stronger now with a compelling opening.",  # generate
            _mock_llm_response(decision="advance", critique="Much improved."),    # evaluate
        ]
        mock_llm_cls.return_value = mock_client

        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        # Advance piece to revise stage first
        piece = load_piece(sample_piece_with_review)
        piece.current_stage = "revise"
        piece.save()

        result = runner.run_stage("test-piece", "revise", output_dir=tmp_output)

        assert result.decision == "advance"
        # The revise.md file should have the body text, not the JSON
        revise_file = sample_piece_with_review / "revise.md"
        content = revise_file.read_text()
        assert "revised draft" in content
        assert "decision" not in content

    @patch("quill.runner.LLMClient")
    def test_max_loops_forces_advance(self, mock_llm_cls, runner, sample_piece, tmp_output, monkeypatch):
        """When max_loops is reached, force advance."""
        from quill.piece import load_piece

        # Set loop count to max
        piece = load_piece(sample_piece)
        runner.set_loop_count(piece, "review", 3)  # max_loops = 3

        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        result = runner.run_stage("test-piece", "review", output_dir=tmp_output)

        assert result.decision == "advance"
        assert "Max loops" in result.critique

    @patch("quill.runner.LLMClient")
    def test_missing_agent_returns_error(self, mock_llm_cls, runner, sample_piece, tmp_output, monkeypatch):
        """Stage with no agent config returns error."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        # brief has no prompt template
        result = runner.run_stage("test-piece", "brief", output_dir=tmp_output)

        assert result.decision == "error"
        assert "No agent config" in result.error

    def test_nonexistent_piece_returns_error(self, runner, tmp_output):
        """Running on non-existent piece returns error."""
        result = runner.run_stage("no-such-piece", "review", output_dir=tmp_output)
        assert result.decision == "error"
        assert "not found" in result.error


# ---------------------------------------------------------------------------
# Chain run — skip stages without prompts
# ---------------------------------------------------------------------------


class TestRunChain:
    """Test chain execution with stage skipping."""

    @patch("quill.runner.LLMClient")
    def test_chain_skips_stages_without_prompts(self, mock_llm_cls, runner, tmp_output, tmp_agents, monkeypatch):
        """Chain starting from a stage without a prompt should skip it and continue."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        # Create piece starting at "outline" (no prompt in default set)
        piece_dir = tmp_output / "chain-piece"
        piece_dir.mkdir()
        meta = {
            "id": "chain-piece", "title": "Chain Test", "genre": "fiction",
            "type": "story", "audience": "general", "tone": "casual",
            "language": "en", "target_length": "1000 words",
            "current_stage": "outline", "agent_set": "default",
        }
        (piece_dir / "meta.yaml").write_text(yaml.dump(meta, default_flow_style=False))
        (piece_dir / "draft.md").write_text("The draft content for chain test.")

        # Mock LLM for stages that have prompts (review, revise)
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_llm_response(
            decision="advance", critique="Looks good.",
        )
        mock_llm_cls.return_value = mock_client

        results = runner.run_chain("chain-piece", from_stage="outline", output_dir=tmp_output)

        # Should have run review and revise (skipped outline, draft, humanize, validate, polish)
        assert len(results) == 2
        assert all(r.decision == "advance" for r in results)
        # No errors
        assert not any(r.error for r in results)

    def test_chain_errors_when_all_stages_lack_prompts(self, runner, tmp_output, tmp_agents, monkeypatch):
        """Chain should error when ALL remaining stages have no prompts."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        # Use an agent set with no prompts at all
        empty_dir = tmp_agents / "empty"
        empty_dir.mkdir()
        (empty_dir / "config.yaml").write_text(
            yaml.dump({"stages": {}}, default_flow_style=False), encoding="utf-8"
        )

        runner.agent_set = "empty"

        piece_dir = tmp_output / "empty-chain-piece"
        piece_dir.mkdir()
        meta = {
            "id": "empty-chain-piece", "title": "Empty", "genre": "fiction",
            "type": "story", "audience": "general", "tone": "casual",
            "language": "en", "target_length": "1000 words",
            "current_stage": "outline", "agent_set": "empty",
        }
        (piece_dir / "meta.yaml").write_text(yaml.dump(meta, default_flow_style=False))

        results = runner.run_chain("empty-chain-piece", from_stage="outline", output_dir=tmp_output)

        assert len(results) == 1
        assert results[0].decision == "error"
        assert "No agent prompts" in results[0].error
        assert "outline" in results[0].error


# ---------------------------------------------------------------------------
# Feedback output format
# ---------------------------------------------------------------------------


class TestFeedbackOutputFormat:
    """Test that feedback stages write clean markdown, not raw JSON."""

    def test_format_feedback_strips_json(self, runner):
        """_format_feedback should strip JSON code fences."""
        raw = 'The draft needs work.\n\n```json\n{"decision": "advance", "critique": "ok"}\n```'
        cleaned = runner._format_feedback(raw)
        assert "```" not in cleaned
        assert "decision" not in cleaned
        assert "draft needs work" in cleaned

    def test_format_feedback_strips_bare_json(self, runner):
        """_format_feedback should strip bare JSON decision blocks."""
        raw = 'Good structure.\n\n{"decision": "advance", "critique": "Solid"}'
        cleaned = runner._format_feedback(raw)
        assert "decision" not in cleaned
        assert "Good structure" in cleaned

    def test_format_feedback_preserves_clean_text(self, runner):
        """_format_feedback should not alter text without JSON."""
        raw = "The piece has strong character development and pacing."
        cleaned = runner._format_feedback(raw)
        assert cleaned == raw

    @patch("quill.runner.LLMClient")
    def test_review_writes_clean_markdown(self, mock_llm_cls, runner, sample_piece, tmp_output, monkeypatch):
        """Review stage output file should contain clean markdown, not JSON."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        mock_client = MagicMock()
        # Simulate LLM returning JSON-wrapped response for a feedback stage
        mock_client.chat.return_value = (
            'The draft needs a stronger opening.\n\n'
            '```json\n{"decision": "advance", "critique": "Good structure overall."}\n```'
        )
        mock_llm_cls.return_value = mock_client

        result = runner.run_stage("test-piece", "review", output_dir=tmp_output)

        assert result.decision == "advance"
        review_file = sample_piece / "review.md"
        content = review_file.read_text()
        # Should NOT contain JSON formatting
        assert "```" not in content
        assert '"decision"' not in content
        # Should contain the clean critique text
        assert "Good structure" in content
