"""Tests for agent.py — config loading, response parsing, model config."""

import json
import pytest
from pathlib import Path
from pydantic import ValidationError

import yaml

from quill.agent import (
    AgentConfig,
    AgentDecision,
    load_agent_config,
    load_model_config,
    list_agent_sets,
    list_agent_prompts,
    ContentStageOutput,
    FeedbackStageOutput,
)


# ---------------------------------------------------------------------------
# Pydantic schemas validation tests
# ---------------------------------------------------------------------------


def test_content_stage_output_validation():
    # Valid model validation
    valid_data = '{"content": "This is generated content."}'
    obj = ContentStageOutput.model_validate_json(valid_data)
    assert obj.content == "This is generated content."

    # Missing field should raise ValidationError
    with pytest.raises(ValidationError):
        ContentStageOutput.model_validate_json('{}')

def test_feedback_stage_output_validation():
    # Valid model validation
    valid_data = '{"critique": "The pacing was a bit slow in chapter 2."}'
    obj = FeedbackStageOutput.model_validate_json(valid_data)
    assert obj.critique == "The pacing was a bit slow in chapter 2."

    # Missing field should raise ValidationError
    with pytest.raises(ValidationError):
        FeedbackStageOutput.model_validate_json('{}')


def test_legacy_parsers_removed():
    import quill.agent as agent
    assert not hasattr(agent, "parse_agent_response")
    assert not hasattr(agent, "_strip_json_block")


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


# ---------------------------------------------------------------------------
# For-stage filtering (the flavor visibility logic)
# ---------------------------------------------------------------------------


class TestAgentsForStage:
    """Test that /api/agents/for-stage filters by prompt file existence."""

    def test_all_flavors_for_stage_with_all_prompts(self, tmp_agents, monkeypatch):
        """Stage where all flavors have a prompt returns all."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)

        # All three fixtures have review.prompt.md
        result = []
        for d in sorted(tmp_agents.iterdir()):
            if d.is_dir() and (d / "config.yaml").exists() and d.name != "__pycache__":
                prompt_file = d / "review.prompt.md"
                if prompt_file.exists():
                    result.append(d.name)

        assert "default" in result
        assert "fiction" in result
        assert "non-fiction" in result

    def test_flavor_excluded_when_prompt_missing(self, tmp_agents, monkeypatch):
        """Flavor without a prompt for the requested stage is excluded."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)

        # non-fiction has no outline.prompt.md — must not appear
        # default also has no outline.prompt.md in the fixture
        result = []
        for d in sorted(tmp_agents.iterdir()):
            if d.is_dir() and (d / "config.yaml").exists() and d.name != "__pycache__":
                prompt_file = d / "outline.prompt.md"
                if prompt_file.exists():
                    result.append(d.name)

        assert "fiction" in result
        assert "default" not in result  # fixture has no outline prompt
        assert "non-fiction" not in result

    def test_flavor_excluded_for_draft(self, tmp_agents, monkeypatch):
        """non-fiction without draft.prompt.md is excluded from draft stage."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)

        result = []
        for d in sorted(tmp_agents.iterdir()):
            if d.is_dir() and (d / "config.yaml").exists() and d.name != "__pycache__":
                prompt_file = d / "draft.prompt.md"
                if prompt_file.exists():
                    result.append(d.name)

        assert "fiction" in result
        assert "default" not in result  # fixture has no draft prompt
        assert "non-fiction" not in result

    def test_newly_added_prompt_makes_flavor_visible(self, tmp_agents, monkeypatch):
        """Adding a missing prompt file makes the flavor appear for that stage."""
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)

        # Verify non-fiction is NOT visible for outline
        prompt_file = tmp_agents / "non-fiction" / "outline.prompt.md"
        assert not prompt_file.exists()

        # Add the prompt
        prompt_file.write_text("# Outline Agent\n\n{{CONTENT}}\n", encoding="utf-8")

        # Now it should be visible
        result = []
        for d in sorted(tmp_agents.iterdir()):
            if d.is_dir() and (d / "config.yaml").exists() and d.name != "__pycache__":
                if (d / "outline.prompt.md").exists():
                    result.append(d.name)

        assert "non-fiction" in result
