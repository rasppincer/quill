"""Tests for agent.py — config loading, response parsing, model config."""

import json
import pytest
from pathlib import Path

import yaml

from quill.agent import (
    AgentConfig,
    AgentDecision,
    load_agent_config,
    load_model_config,
    save_model_config,
    list_agent_sets,
    list_agent_prompts,
    parse_agent_response,
    _strip_json_block,
)


# ---------------------------------------------------------------------------
# Response parsing — the most critical logic
# ---------------------------------------------------------------------------


class TestParseAgentResponse:
    """Test the LLM response parser with various formats."""

    def test_json_in_code_block(self):
        """Standard format: JSON inside ```json ... ``` block."""
        response = (
            "The draft has several issues.\n\n"
            "1. Opening is weak\n"
            "2. Pacing is off\n\n"
            '```json\n{"decision": "loop_back", "critique": "Needs stronger opening"}\n```'
        )
        result = parse_agent_response(response)
        assert result.decision == "loop_back"
        assert result.critique == "Needs stronger opening"
        assert result.body  # body should have the prose, not the JSON

    def test_bare_json_no_code_block(self):
        """JSON without code block wrapper."""
        response = (
            "Good draft overall.\n\n"
            '{"decision": "advance", "critique": "Well structured, proceed."}'
        )
        result = parse_agent_response(response)
        assert result.decision == "advance"
        assert "Well structured" in result.critique

    def test_json_with_extra_fields(self):
        """JSON with extra fields beyond decision/critique."""
        response = (
            '```json\n{"decision": "advance", "critique": "Solid work", "score": 8.5}\n```'
        )
        result = parse_agent_response(response)
        assert result.decision == "advance"
        assert result.critique == "Solid work"

    def test_heuristic_loop_back_keywords(self):
        """Falls back to heuristic when no JSON found."""
        for keyword in ["loop_back", "loop back", "needs revision", "needs work", "reject"]:
            response = f"The text {keyword} because of issues."
            result = parse_agent_response(response)
            assert result.decision == "loop_back", f"Keyword '{keyword}' should trigger loop_back"

    def test_heuristic_advance_default(self):
        """Defaults to advance when no JSON and no loop keywords."""
        response = "The text is good. Everything looks fine."
        result = parse_agent_response(response)
        assert result.decision == "advance"

    def test_body_strips_json(self):
        """Body field should contain prose without JSON metadata."""
        response = (
            "Here is the revised text.\n\nIt is much better now.\n\n"
            '```json\n{"decision": "advance", "critique": "Good"}\n```'
        )
        result = parse_agent_response(response)
        assert "revised text" in result.body
        assert "decision" not in result.body
        assert "```" not in result.body

    def test_body_strips_example_markers(self):
        """Body should strip '(revised text starts here)' style markers."""
        response = (
            "(revised text starts here)\n\n"
            "The actual content.\n\n"
            "(revised text ends here)\n\n"
            '```json\n{"decision": "advance", "critique": "ok"}\n```'
        )
        result = parse_agent_response(response)
        assert "starts here" not in result.body
        assert "ends here" not in result.body
        assert "actual content" in result.body

    def test_empty_response(self):
        """Handle empty or whitespace-only response."""
        result = parse_agent_response("")
        assert result.decision == "advance"  # defaults to advance

    def test_malformed_json_in_code_block(self):
        """Handle malformed JSON inside code block gracefully."""
        response = '```json\n{"decision": advance, broken}\n```'
        result = parse_agent_response(response)
        # Should fall back to heuristic
        assert result.decision in ("advance", "loop_back")

    def test_multiple_json_blocks_uses_first(self):
        """When multiple JSON blocks exist, uses the first valid one."""
        response = (
            '```json\n{"decision": "loop_back", "critique": "first"}\n```\n'
            'Some text\n\n'
            '```json\n{"decision": "advance", "critique": "second"}\n```'
        )
        result = parse_agent_response(response)
        assert result.decision == "loop_back"
        assert result.critique == "first"

    def test_output_preserves_full_response(self):
        """Output field should contain the complete raw response."""
        response = "Some text\n\n```json\n{\"decision\": \"advance\", \"critique\": \"ok\"}\n```"
        result = parse_agent_response(response)
        assert result.output == response


# ---------------------------------------------------------------------------
# Strip JSON block
# ---------------------------------------------------------------------------


class TestStripJsonBlock:
    """Test the JSON stripping utility."""

    def test_strips_code_block_json(self):
        text = 'Review text.\n\n```json\n{"decision": "advance"}\n```\n'
        result = _strip_json_block(text)
        assert "decision" not in result
        assert "Review text" in result

    def test_strips_bare_json(self):
        text = 'Review text.\n\n{"decision": "advance", "critique": "ok"}\n'
        result = _strip_json_block(text)
        assert "decision" not in result
        assert "Review text" in result

    def test_preserves_non_decision_json(self):
        """JSON without 'decision' key should be preserved."""
        text = 'Here is code: {"name": "test", "value": 42}\n'
        result = _strip_json_block(text)
        assert '{"name": "test"' in result


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


class TestLoadAgentConfig:
    """Test agent config loading from YAML + prompt files."""

    def test_loads_existing_set(self, tmp_agents, monkeypatch):
        """Load config for an existing agent set."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

        cfg = load_agent_config("default", "review")
        assert cfg is not None
        assert cfg.stage == "review"
        assert cfg.name == "Review Agent"
        assert cfg.temperature == 0.5  # stage override
        assert cfg.max_loops == 3
        assert "Review Agent" in cfg.prompt_template

    def test_uses_global_model_config(self, tmp_agents, monkeypatch):
        """Model/api_base comes from global model.yaml."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

        cfg = load_agent_config("default", "review")
        assert cfg.model == "test-model"
        assert cfg.api_base == "http://localhost:9999/v1"

    def test_agent_set_overrides_global(self, tmp_agents, monkeypatch):
        """Agent set config can override global model settings."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

        # Add model override to agent set
        cfg_path = tmp_agents / "default" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["model"] = "override-model"
        cfg_path.write_text(yaml.dump(cfg, default_flow_style=False))

        result = load_agent_config("default", "review")
        assert result.model == "override-model"

    def test_missing_set_returns_none(self, tmp_agents, monkeypatch):
        """Non-existent agent set returns None."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

        cfg = load_agent_config("nonexistent", "review")
        assert cfg is None

    def test_missing_prompt_still_loads(self, tmp_agents, monkeypatch):
        """Config loads even if prompt file is missing (empty template)."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

        cfg = load_agent_config("default", "humanize")  # no humanize.prompt.md
        assert cfg is not None
        assert cfg.prompt_template == ""

    def test_stage_temperature_override(self, tmp_agents, monkeypatch):
        """Stage-specific temperature overrides set-level default."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

        cfg = load_agent_config("default", "review")
        assert cfg.temperature == 0.5  # stage override, not 0.7 default


# ---------------------------------------------------------------------------
# Model config CRUD
# ---------------------------------------------------------------------------


class TestModelConfig:
    """Test global model config load/save."""

    def test_load_model_config(self, tmp_agents, monkeypatch):
        """Load model config from model.yaml."""
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

        cfg = load_model_config()
        assert cfg["model"] == "test-model"
        assert cfg["api_base"] == "http://localhost:9999/v1"

    def test_save_model_config(self, tmp_path, monkeypatch):
        """Save model config to model.yaml."""
        cfg_file = tmp_path / "model.yaml"
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", cfg_file)

        save_model_config({"model": "new-model", "api_base": "http://test/v1"})

        loaded = yaml.safe_load(cfg_file.read_text())
        assert loaded["model"] == "new-model"
        assert loaded["api_base"] == "http://test/v1"

    def test_load_missing_returns_empty(self, tmp_path, monkeypatch):
        """Loading non-existent model.yaml returns empty dict."""
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_path / "nope.yaml")

        cfg = load_model_config()
        assert cfg == {}


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


class TestListAgents:
    """Test agent set and prompt listing."""

    def test_list_agent_sets(self, tmp_agents, monkeypatch):
        """List available agent sets."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)

        sets = list_agent_sets()
        names = [s["name"] for s in sets]
        assert "default" in names
        assert sets[0]["description"] == "Test agents"

    def test_list_agent_prompts(self, tmp_agents, monkeypatch):
        """List prompt templates in a set."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)

        prompts = list_agent_prompts("default")
        stages = [p["stage"] for p in prompts]
        assert "review" in stages
        assert "revise" in stages

    def test_list_prompts_nonexistent_set(self, tmp_agents, monkeypatch):
        """Listing prompts for non-existent set returns empty."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)

        prompts = list_agent_prompts("nonexistent")
        assert prompts == []
