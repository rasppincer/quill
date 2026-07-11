"""Tests for decision stage prompting, parsing, and LLM execution."""

import json
import pytest
from unittest.mock import MagicMock, patch

from quill.agent import AgentDecision
from quill.piece import Piece, _stage_filename
from quill.pipeline import load_pipeline
from quill.prompt_builder import PromptBuilder
from quill.stage_runner import extract_json, DecisionStageOutput


def test_extract_json_fenced():
    """extract_json extracts JSON string from markdown code blocks."""
    fenced_1 = '```json\n{"decision": "advance", "reason": "Good."}\n```'
    assert json.loads(extract_json(fenced_1)) == {"decision": "advance", "reason": "Good."}

    fenced_2 = '```\n{"decision": "reject", "reason": "Bad."}\n```'
    assert json.loads(extract_json(fenced_2)) == {"decision": "reject", "reason": "Bad."}


def test_extract_json_with_surrounding_chatter():
    """extract_json extracts JSON even when surrounded by descriptive text."""
    chatter = 'Here is the response:\n```json\n{"decision": "advance", "reason": "All set."}\n```\nHope that helps!'
    assert json.loads(extract_json(chatter)) == {"decision": "advance", "reason": "All set."}

    plain_chatter = 'Some text before {"decision": "reject", "reason": "No evidence"} and after.'
    assert json.loads(extract_json(plain_chatter)) == {"decision": "reject", "reason": "No evidence"}


def test_prompt_builder_decision_system_prompt():
    """PromptBuilder.system_prompt formats decision mode appropriately."""
    piece = Piece(id="test-p", title="T", genre="creative", type="poem", language="en")

    # 1. Unstructured decision prompt (default)
    prompt_unstructured = PromptBuilder.system_prompt("review_decision", piece, "decision", use_structured=False)
    assert "MUST respond with a JSON object" in prompt_unstructured

    # 2. Structured decision prompt
    prompt_structured = PromptBuilder.system_prompt("review_decision", piece, "decision", use_structured=True)
    assert "return a JSON object with your decision and reason" in prompt_structured
    assert "MUST respond with a JSON object" not in prompt_structured


class TestLLMCallerDecisionStage:
    """Test LLMCaller running a decision stage."""

    @patch("quill.runner.LLMClient")
    def test_run_decision_stage_unstructured_success(self, mock_llm_cls, tmp_output):
        """Decision stage successfully executes and parses unstructured JSON."""
        # Setup piece
        piece_dir = tmp_output / "dec-piece"
        piece_dir.mkdir()
        meta = {
            "id": "dec-piece", "title": "T", "genre": "fiction", "type": "story",
            "current_stage": "review_decision", "agent_set": "default",
        }
        import yaml
        (piece_dir / "meta.yaml").write_text(yaml.dump(meta))
        (piece_dir / _stage_filename("review")).write_text("Review comments here.")

        from quill.piece import load_piece
        piece = load_piece(piece_dir)

        # Mock LLM Client
        mock_client = MagicMock()
        mock_client.api_base = "https://api.openai.com/v1"
        mock_client.chat.return_value = '```json\n{"decision": "advance", "reason": "Critique is clean."}\n```'
        mock_llm_cls.return_value = mock_client

        # Mock StageContext
        pipeline = load_pipeline("default")
        stage_def = pipeline.get_stage("review_decision")

        from quill.runner import StageRunner
        runner = StageRunner(agent_set="default")
        sc = runner.assembler.prepare_stage("dec-piece", "review_decision", output_dir=tmp_output)

        decision = runner.llm.run_stage(mock_client, "review_decision", piece, sc)

        assert decision.decision == "advance"
        assert decision.critique == "Critique is clean."

        # Check decision and JSON outputs are written to disk
        dec_file = piece_dir / _stage_filename("review_decision", ".decision.md")
        assert dec_file.exists()
        assert "Decision: advance" in dec_file.read_text(encoding="utf-8")

        json_file = piece_dir / _stage_filename("review_decision", ".json")
        assert json_file.exists()
        assert "Critique is clean." in json_file.read_text(encoding="utf-8")

    @patch("quill.runner.LLMClient")
    def test_run_decision_stage_invalid_fallback(self, mock_llm_cls, tmp_output):
        """Decision stage defaults to reject if parsing fails."""
        piece_dir = tmp_output / "dec-piece-err"
        piece_dir.mkdir()
        meta = {
            "id": "dec-piece-err", "title": "T", "genre": "fiction", "type": "story",
            "current_stage": "review_decision", "agent_set": "default",
        }
        import yaml
        (piece_dir / "meta.yaml").write_text(yaml.dump(meta))
        (piece_dir / _stage_filename("review")).write_text("Review comments here.")

        from quill.piece import load_piece
        piece = load_piece(piece_dir)

        mock_client = MagicMock()
        mock_client.api_base = "https://api.openai.com/v1"
        mock_client.chat.return_value = "Garbage response from LLM."
        mock_llm_cls.return_value = mock_client

        pipeline = load_pipeline("default")
        from quill.runner import StageRunner
        runner = StageRunner(agent_set="default")
        sc = runner.assembler.prepare_stage("dec-piece-err", "review_decision", output_dir=tmp_output)

        decision = runner.llm.run_stage(mock_client, "review_decision", piece, sc)

        assert decision.decision == "reject"
        assert "Failed to parse decision" in decision.critique

    @patch("quill.runner.LLMClient")
    def test_run_decision_stage_bypass_on_limit(self, mock_llm_cls, tmp_output):
        """Decision stage bypasses LLM call when max_loops is reached."""
        piece_dir = tmp_output / "dec-piece-bypass"
        piece_dir.mkdir()
        meta = {
            "id": "dec-piece-bypass", "title": "T", "genre": "fiction", "type": "story",
            "current_stage": "review_decision", "agent_set": "default",
        }
        import yaml
        (piece_dir / "meta.yaml").write_text(yaml.dump(meta))

        # Set loop count of review to max_loops (3)
        from quill.piece import load_piece
        piece = load_piece(piece_dir)
        piece.set_loop_count("review", 3)

        mock_client = MagicMock()
        mock_llm_cls.return_value = mock_client

        from quill.runner import StageRunner
        runner = StageRunner(agent_set="default")

        decision = runner.run_stage("dec-piece-bypass", "review_decision", output_dir=tmp_output)

        assert decision.decision == "advance"
        assert "Loop limit reached" in decision.critique
        mock_client.chat.assert_not_called()

    @patch("quill.runner.LLMClient")
    def test_run_decision_stage_reject_increments_counts(self, mock_llm_cls, tmp_output):
        """Decision stage rejection increments the loop counts of review and revise."""
        piece_dir = tmp_output / "dec-piece-reject"
        piece_dir.mkdir()
        meta = {
            "id": "dec-piece-reject", "title": "T", "genre": "fiction", "type": "story",
            "current_stage": "review_decision", "agent_set": "default",
        }
        import yaml
        (piece_dir / "meta.yaml").write_text(yaml.dump(meta))

        from quill.piece import load_piece
        piece = load_piece(piece_dir)
        piece.set_loop_count("review", 1)
        piece.set_loop_count("revise", 1)

        mock_client = MagicMock()
        mock_client.api_base = "https://api.openai.com/v1"
        mock_client.chat.return_value = '```json\n{"decision": "reject", "reason": "Weak opening"}\n```'
        mock_llm_cls.return_value = mock_client

        from quill.runner import StageRunner
        runner = StageRunner(agent_set="default")

        # Force piece trigger to auto to check advance to revise
        piece.trigger = "auto"
        piece.save()

        decision = runner.run_stage("dec-piece-reject", "review_decision", output_dir=tmp_output)

        assert decision.decision == "reject"

        # Verify piece advanced to revise and loop counts incremented to 2
        piece = load_piece(piece_dir)
        assert piece.current_stage == "revise"
        assert piece.get_loop_count("review") == 2
        assert piece.get_loop_count("revise") == 2
