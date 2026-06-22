"""Tests for runner.py — stage execution, loop logic, input assembly."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import yaml

from quill.runner import StageRunner
from quill.prompt_builder import render_prompt
from quill.piece import _stage_filename
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
        (d / _stage_filename("revise")).write_text("The revised text here.")

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
        inputs = runner._read_inputs(piece, "brief", pipeline, loop_count=1)
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
        review_file = sample_piece / _stage_filename("review")
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
        revise_file = sample_piece_with_review / _stage_filename("revise")
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
        (piece_dir / _stage_filename("draft")).write_text("The draft content for chain test.")

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
        review_file = sample_piece / _stage_filename("review")
        content = review_file.read_text()
        # Should NOT contain JSON formatting
        assert "```" not in content
        assert '"decision"' not in content
        # Should contain the clean critique text
        assert "Good structure" in content


# ---------------------------------------------------------------------------
# Jinja2 prompt rendering
# ---------------------------------------------------------------------------


class TestRenderPrompt:
    """Test the Jinja2 prompt renderer."""

    def test_replaces_standard_vars(self):
        """Basic {{VAR}} replacement works."""
        template = "Title: {{TITLE}}, Genre: {{GENRE}}"
        ctx = {"TITLE": "My Post", "GENRE": "fiction"}
        result = render_prompt(template, ctx)
        assert result == "Title: My Post, Genre: fiction"

    def test_jinja2_conditional_true(self):
        """Jinja2 conditionals render when condition is true."""
        template = "Write content.{% if is_looping %}\nPrevious attempt:\n{{CONTENT}}{% endif %}"
        ctx = {"is_looping": True, "CONTENT": "Old draft here."}
        result = render_prompt(template, ctx)
        assert "Previous attempt" in result
        assert "Old draft" in result

    def test_jinja2_conditional_false(self):
        """Conditional block excluded when condition is false."""
        template = "Write content.{% if is_looping %}\nPrevious:\n{{CONTENT}}{% endif %}"
        ctx = {"is_looping": False, "CONTENT": "Old draft."}
        result = render_prompt(template, ctx)
        assert "Previous" not in result
        assert "Write content" in result

    def test_fallback_on_invalid_jinja(self):
        """Falls back to .replace() when template has invalid Jinja2."""
        template = "Code: {x = 5} and title: {{TITLE}}"
        ctx = {"TITLE": "Test"}
        result = render_prompt(template, ctx)
        assert "Test" in result

    def test_multiline_content_no_corruption(self):
        """Content with markdown, code blocks, special chars renders cleanly."""
        template = "## Input\n{{CONTENT}}\n## Stage: {{STAGE}}"
        content = "# Heading\n\n```python\ndef foo():\n    return {1: 2}\n```\n\n*bold* **italic**"
        ctx = {"CONTENT": content, "STAGE": "draft"}
        result = render_prompt(template, ctx)
        assert "# Heading" in result
        assert "def foo" in result
        assert "Stage: draft" in result

    def test_undefined_vars_silent(self):
        """Undefined template vars are silently ignored."""
        template = "Title: {{TITLE}}, Missing: {{MISSING_VAR}}"
        ctx = {"TITLE": "Test"}
        result = render_prompt(template, ctx)
        assert "Title: Test" in result


class TestBuildRenderContext:
    """Test _build_render_context()."""

    def test_context_has_all_vars(self, runner, sample_piece, tmp_output, monkeypatch):
        """Context dict has all standard vars plus loop state."""
        from quill.piece import load_piece
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        piece = load_piece(sample_piece)
        ctx = runner._build_render_context(piece, "review", "test content", "metrics here")
        assert ctx["TITLE"] == "Test Piece"
        assert ctx["GENRE"] == "fiction"
        assert ctx["TYPE"] == "story"
        assert ctx["LANGUAGE"] == "en"
        assert ctx["STAGE"] == "review"
        assert ctx["CONTENT"] == "test content"
        assert ctx["METRICS"] == "metrics here"
        assert ctx["PIECE_ID"] == "test-piece"
        assert ctx["loop_count"] == 0
        assert ctx["is_looping"] is False

    def test_context_looping(self, runner, sample_piece, tmp_output, monkeypatch):
        """Context shows is_looping=True when loop_count > 0."""
        from quill.piece import load_piece
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        piece = load_piece(sample_piece)
        runner.set_loop_count(piece, "review", 2)
        ctx = runner._build_render_context(piece, "review", "content", "metrics")
        assert ctx["loop_count"] == 2
        assert ctx["is_looping"] is True

    def test_context_extra_vars(self, runner, sample_piece, tmp_output, monkeypatch):
        """Extra vars are merged into context."""
        from quill.piece import load_piece
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        piece = load_piece(sample_piece)
        ctx = runner._build_render_context(
            piece, "draft", "input", "metrics",
            extra={"GENERATED": "some text", "INPUT_CONTENT": "full input"},
        )
        assert ctx["GENERATED"] == "some text"
        assert ctx["INPUT_CONTENT"] == "full input"


# ---------------------------------------------------------------------------
# Loop guardrails
# ---------------------------------------------------------------------------


class TestLoopGuardrails:
    """Test metric degradation detection across loop iterations."""

    def test_guardrail_no_baseline(self, runner, sample_piece, tmp_output, monkeypatch):
        """No baseline snapshot → no guardrail trigger."""
        from quill.piece import load_piece
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        piece = load_piece(sample_piece)

        result = runner.metrics_svc.check_guardrail(piece, "review", 1)
        assert result == ""

    def test_guardrail_triggers_on_word_count_drop(self, runner, sample_piece, tmp_output, monkeypatch):
        """Word count drop >30% triggers guardrail."""
        from quill.piece import load_piece
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        piece = load_piece(sample_piece)
        stage_dir = sample_piece

        # Save baseline with high word count
        baseline = {"word_count": 1000, "flesch_ease": 50, "type_token_ratio": 0.5, "passive_voice_pct": 5}
        baseline_file = stage_dir / _stage_filename("review", ".guardrail-metrics.yaml")
        import yaml
        baseline_file.write_text(yaml.dump(baseline))

        # Write current metrics with much lower word count
        current = {"word_count": 600, "flesch_ease": 50, "type_token_ratio": 0.5, "passive_voice_pct": 5}
        current_file = stage_dir / _stage_filename("review", ".metrics.yaml")
        current_file.write_text(yaml.dump(current))

        result = runner.metrics_svc.check_guardrail(piece, "review", 1)
        assert "word count dropped" in result

    def test_guardrail_no_trigger_when_stable(self, runner, sample_piece, tmp_output, monkeypatch):
        """No trigger when metrics are stable."""
        from quill.piece import load_piece
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        piece = load_piece(sample_piece)
        stage_dir = sample_piece

        baseline = {"word_count": 1000, "flesch_ease": 50, "type_token_ratio": 0.5, "passive_voice_pct": 5}
        baseline_file = stage_dir / _stage_filename("review", ".guardrail-metrics.yaml")
        import yaml
        baseline_file.write_text(yaml.dump(baseline))

        current = {"word_count": 950, "flesch_ease": 48, "type_token_ratio": 0.48, "passive_voice_pct": 6}
        current_file = stage_dir / _stage_filename("review", ".metrics.yaml")
        current_file.write_text(yaml.dump(current))

        result = runner.metrics_svc.check_guardrail(piece, "review", 1)
        assert result == ""

    def test_snapshot_save_and_cleanup(self, runner, sample_piece, tmp_output, monkeypatch):
        """Snapshot is saved on first loop and cleaned up on advance."""
        from quill.piece import load_piece
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        piece = load_piece(sample_piece)
        stage_dir = sample_piece

        # Write metrics so snapshot has something to save
        import yaml
        current = {"word_count": 500, "flesch_ease": 45}
        (stage_dir / _stage_filename("review", ".metrics.yaml")).write_text(yaml.dump(current))

        # Save snapshot
        runner.metrics_svc.save_guardrail_snapshot(piece, "review")
        snapshot = stage_dir / _stage_filename("review", ".guardrail-metrics.yaml")
        assert snapshot.exists()

        # Cleanup
        runner.metrics_svc.cleanup_guardrail_snapshot(piece, "review")
        assert not snapshot.exists()


# ---------------------------------------------------------------------------
# Debug prompt dump
# ---------------------------------------------------------------------------


class TestRunLog:
    """Test the unified run log (JSONL)."""

    def test_log_run_entry_creates_file(self, runner, sample_piece, monkeypatch):
        """_log_run_entry appends a JSONL entry to run-log.jsonl."""
        from quill.piece import load_piece
        import json

        monkeypatch.setattr("quill.agent.load_model_config", lambda: {"model": "test-model"})
        piece = load_piece(sample_piece)

        runner.run_logger.log(piece, "review", "agent", "system prompt", "user prompt", {
            "decision": "advance", "critique": "Good work.",
        })

        log_file = sample_piece / "run-log.jsonl"
        assert log_file.exists()
        entries = [json.loads(line) for line in log_file.read_text().strip().split("\n")]
        assert len(entries) == 1
        assert entries[0]["stage"] == "review"
        assert entries[0]["call"] == "agent"
        assert entries[0]["decision"] == "advance"
        assert entries[0]["system_chars"] == len("system prompt")

    def test_log_run_entry_appends(self, runner, sample_piece, monkeypatch):
        """Multiple calls append entries, not overwrite."""
        from quill.piece import load_piece
        import json

        monkeypatch.setattr("quill.agent.load_model_config", lambda: {"model": "test-model"})
        piece = load_piece(sample_piece)

        runner.run_logger.log(piece, "review", "agent", "sys1", "user1")
        runner.run_logger.log(piece, "review", "agent", "sys2", "user2", {"decision": "loop_back"})
        runner.run_logger.log(piece, "draft", "generate", "sys3", "user3")

        log_file = sample_piece / "run-log.jsonl"
        entries = [json.loads(line) for line in log_file.read_text().strip().split("\n")]
        assert len(entries) == 3
        assert entries[0]["call"] == "agent"
        assert entries[1]["decision"] == "loop_back"
        assert entries[2]["stage"] == "draft"


# ---------------------------------------------------------------------------
# Two-file output (content stages)
# ---------------------------------------------------------------------------


class TestEvaluatePromptContent:
    """Verify evaluate prompts include generated text, not just inputs."""

    @patch("quill.runner.LLMClient")
    def test_evaluate_prompt_includes_generated_text(self, mock_llm_cls, runner, sample_piece_with_review, tmp_output, monkeypatch):
        """The evaluate prompt must contain the generated text, not just inputs."""
        from quill.piece import load_piece
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        mock_client = MagicMock()
        mock_llm_cls.return_value = mock_client

        mock_client.chat.side_effect = [
            "The revised draft is much stronger now.",
            '{"decision": "advance", "critique": "Well done."}',
        ]

        runner.run_stage("test-piece", "revise", output_dir=tmp_output)

        # Check the evaluate prompt (second call) includes generated text
        calls = mock_client.chat.call_args_list
        assert len(calls) == 2
        eval_user_prompt = calls[1][0][1]  # second call, user prompt
        assert "The revised draft is much stronger now" in eval_user_prompt, (
            "Evaluate prompt must contain the generated text"
        )

    @patch("quill.runner.LLMClient")
    def test_evaluate_prompt_includes_input_content(self, mock_llm_cls, runner, sample_piece_with_review, tmp_output, monkeypatch):
        """The evaluate prompt must contain the input content (draft + review)."""
        from quill.piece import load_piece
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        mock_client = MagicMock()
        mock_llm_cls.return_value = mock_client

        mock_client.chat.side_effect = [
            "Revised text here.",
            '{"decision": "advance", "critique": "Good."}',
        ]

        runner.run_stage("test-piece", "revise", output_dir=tmp_output)

        calls = mock_client.chat.call_args_list
        eval_user_prompt = calls[1][0][1]
        # Should contain the input content markers
        assert "draft" in eval_user_prompt.lower() or "outline" in eval_user_prompt.lower(), (
            "Evaluate prompt must contain input content"
        )

    @patch("quill.runner.LLMClient")
    def test_evaluate_prompt_has_both_sections(self, mock_llm_cls, runner, sample_piece_with_review, tmp_output, monkeypatch):
        """Evaluate prompt has both Input and Generated sections clearly labeled."""
        from quill.piece import load_piece
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        mock_client = MagicMock()
        mock_llm_cls.return_value = mock_client

        mock_client.chat.side_effect = [
            "Generated revise content.",
            '{"decision": "advance", "critique": "OK."}',
        ]

        runner.run_stage("test-piece", "revise", output_dir=tmp_output)

        calls = mock_client.chat.call_args_list
        eval_user_prompt = calls[1][0][1]
        # Check that both sections exist in the prompt
        assert "Generated" in eval_user_prompt, "Evaluate prompt needs 'Generated' section"
        assert "Input" in eval_user_prompt, "Evaluate prompt needs 'Input' section"


class TestTwoFileOutput:
    """Content stages write .md (generated text) + .decision.md (evaluation)."""

    def test_compose_prompt_returns_filled_template(self, runner, sample_piece_with_review, tmp_output, monkeypatch):
        """compose_prompt returns the filled prompt template without calling LLM."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        result = runner.compose_prompt("test-piece", "review", output_dir=tmp_output)

        assert "error" not in result
        assert result["stage"] == "review"
        assert result["is_content_stage"] is False
        assert "single_call" in result
        assert "draft content" in result["single_call"]["user"]
        assert result["single_call"]["char_count"] > 0
        assert result["template_vars"]["TITLE"] == "Test Piece"

    def test_compose_prompt_content_stage_two_calls(self, runner, sample_piece_with_review, tmp_output, monkeypatch):
        """Content stage compose_prompt returns both generate and evaluate prompts."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        result = runner.compose_prompt("test-piece", "revise", output_dir=tmp_output)

        assert "error" not in result
        assert result["is_content_stage"] is True
        assert "generate" in result
        assert "evaluate" in result
        assert "Do NOT include any JSON" in result["generate"]["system"]
        assert result["generate"]["char_count"] > 0
        assert result["evaluate"]["char_count"] > 0

    def test_compose_prompt_nonexistent_piece(self, runner, tmp_output):
        """compose_prompt returns error for missing piece."""
        result = runner.compose_prompt("nope", "review", output_dir=tmp_output)
        assert "error" in result
        assert "not found" in result["error"]

    @patch("quill.runner.LLMClient")
    def test_content_stage_writes_decision_file(self, mock_llm_cls, runner, sample_piece_with_review, tmp_output, monkeypatch):
        """Content stage writes both stage.md and stage.decision.md."""
        from quill.piece import load_piece

        mock_client = MagicMock()
        mock_client.chat.side_effect = [
            "The revised draft is much stronger now.",  # generate
            _mock_llm_response(decision="advance", critique="Much improved."),  # evaluate
        ]
        mock_llm_cls.return_value = mock_client

        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        piece = load_piece(sample_piece_with_review)
        piece.current_stage = "revise"
        piece.save()

        result = runner.run_stage("test-piece", "revise", output_dir=tmp_output)

        assert result.decision == "advance"

        # Stage file has generated text
        revise_file = sample_piece_with_review / _stage_filename("revise")
        assert revise_file.exists()
        assert "revised draft" in revise_file.read_text()

        # Decision file has evaluation
        decision_file = sample_piece_with_review / _stage_filename("revise", ".decision.md")
        assert decision_file.exists()
        decision_content = decision_file.read_text()
        assert "Decision: advance" in decision_content
        assert "Much improved" in decision_content

    @patch("quill.runner.LLMClient")
    def test_loop_back_preserves_generated_text(self, mock_llm_cls, runner, sample_piece_with_review, tmp_output, monkeypatch):
        """On loop_back, stage.md retains the generated text (not critique)."""
        from quill.piece import load_piece

        mock_client = MagicMock()
        mock_client.chat.side_effect = [
            "First attempt at revision.",  # generate
            _mock_llm_response(decision="loop_back", critique="Needs more depth."),  # evaluate
        ]
        mock_llm_cls.return_value = mock_client

        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        piece = load_piece(sample_piece_with_review)
        piece.current_stage = "revise"
        piece.save()

        result = runner.run_stage("test-piece", "revise", output_dir=tmp_output)

        assert result.decision == "loop_back"

        # Stage file still has the generated text
        revise_file = sample_piece_with_review / _stage_filename("revise")
        assert "First attempt" in revise_file.read_text()

        # Decision file has the critique
        decision_file = sample_piece_with_review / _stage_filename("revise", ".decision.md")
        assert "Needs more depth" in decision_file.read_text()

    @patch("quill.runner.LLMClient")
    def test_decision_file_not_in_body_fallback(self, mock_llm_cls, runner, tmp_output, monkeypatch):
        """Piece detail should not use .decision.md as fallback body."""
        from quill.piece import load_piece
        from quill.app import app as flask_app

        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        # Create a piece at draft stage with only a decision file (no draft.md)
        piece_dir = tmp_output / "decision-only"
        piece_dir.mkdir()
        meta = {
            "id": "decision-only", "title": "Decision Test",
            "current_stage": "draft", "genre": "fiction",
            "created": "2026-01-01", "updated": "2026-01-01",
        }
        (piece_dir / "meta.yaml").write_text(yaml.dump(meta, default_flow_style=False))
        (piece_dir / _stage_filename("draft", ".decision.md")).write_text("## Decision: advance\n\n## Critique\nLooks good.\n")
        # A brief.md with actual content so the fallback has something to find
        (piece_dir / _stage_filename("brief")).write_text("The brief content for the piece.")

        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            resp = client.get("/api/pieces/decision-only")
            assert resp.status_code == 200
            data = resp.get_json()
            # Body should come from brief.md, not draft.decision.md
            assert "brief content" in data["body"]
            assert "Decision: advance" not in data["body"]

    def test_write_decision_format(self, runner, sample_piece):
        """_write_decision creates a well-structured .decision.md file."""
        from quill.piece import load_piece

        piece = load_piece(sample_piece)
        decision = AgentDecision(
            decision="loop_back",
            critique="Opening is weak. Need a stronger hook.",
            output="",
        )
        runner._write_decision(piece, "draft", decision)

        decision_file = sample_piece / _stage_filename("draft", ".decision.md")
        assert decision_file.exists()
        content = decision_file.read_text()
        assert "Decision: loop_back" in content
        assert "Opening is weak" in content
        assert "## Critique" in content

    def test_read_inputs_includes_decision_file(self, runner, tmp_output):
        """_read_inputs includes .decision.md when it exists (loop context)."""
        from quill.piece import load_piece, Piece

        d = tmp_output / "loop-piece"
        d.mkdir()
        meta = {"id": "loop-piece", "title": "T", "current_stage": "draft"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("The brief.")
        (d / _stage_filename("draft")).write_text("Previous draft attempt here.")
        (d / _stage_filename("draft", ".decision.md")).write_text("## Decision: loop_back\n\n## Critique\nNeeds more evidence.\n")

        piece = load_piece(d)
        inputs = runner._read_inputs(piece, "draft", None, loop_count=1)

        assert "Previous draft attempt" in inputs
        assert "Needs more evidence" in inputs
        assert "evaluation feedback" in inputs

    def test_read_inputs_excludes_decision_on_first_run(self, runner, tmp_output):
        """First run (loop_count=0) does NOT include previous attempt or decision."""
        from quill.piece import load_piece, Piece

        d = tmp_output / "first-run-piece"
        d.mkdir()
        meta = {"id": "first-run-piece", "title": "T", "current_stage": "draft"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("The brief.")
        (d / _stage_filename("draft")).write_text("Previous draft attempt here.")
        (d / _stage_filename("draft", ".decision.md")).write_text("## Decision: loop_back\n\n## Critique\nNeeds more evidence.\n")

        piece = load_piece(d)
        inputs = runner._read_inputs(piece, "draft", None, loop_count=0)

        assert "Previous draft attempt" not in inputs
        assert "evaluation feedback" not in inputs
        assert "brief" in inputs.lower()
