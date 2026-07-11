"""Agent — LLM-powered critique and decision engine for pipeline stages.

Each stage can have an agent that:
1. Reads input files (previous stage output)
2. Runs a prompt template with the content
3. Parses the LLM response for critique + decision
4. Returns advance or loop-back with feedback

Agents are configured via YAML and use OpenAI-compatible APIs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"
MODEL_CONFIG_FILE = AGENTS_DIR / "model.yaml"


_model_config_cache: tuple[float, dict] | None = None


def load_model_config() -> dict:
    """Load global model configuration from agents/model.yaml.

    Cached by file mtime -- re-parsed only when the file changes.
    """
    global _model_config_cache
    if not MODEL_CONFIG_FILE.exists():
        cfg = {}
    else:
        mtime = MODEL_CONFIG_FILE.stat().st_mtime
        if _model_config_cache and _model_config_cache[0] == mtime:
            cfg = _model_config_cache[1]
        else:
            with open(MODEL_CONFIG_FILE) as f:
                cfg = yaml.safe_load(f) or {}
            _model_config_cache = (mtime, cfg)
            # Validate on cache miss (warnings only, never blocks)
            try:
                from .config_validation import validate_config, MODEL_SCHEMA
                validate_config(cfg, MODEL_SCHEMA, context="model.yaml")
            except Exception:
                pass

    # Apply environment variable overrides if present (only when not in unit tests)
    result = cfg.copy()
    if os.environ.get("QUILL_TESTING") != "1":
        if os.environ.get("QUILL_API_BASE"):
            result["api_base"] = os.environ.get("QUILL_API_BASE")
        if os.environ.get("QUILL_API_KEY"):
            result["api_key"] = os.environ.get("QUILL_API_KEY")
        
        model_env = os.environ.get("QUILL_API_MODEL") or os.environ.get("QUILL_TEST_LLM_MODEL")
        if model_env:
            result["model"] = model_env
    return result





@dataclass
class AgentConfig:
    """Configuration for a stage agent."""
    stage: str
    name: str = ""
    description: str = ""

    # LLM settings
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096

    # Pipeline settings
    max_loops: int = 3
    trigger: str = "on_advance"  # on_advance | auto

    # Prompt template (loaded from .prompt.md file)
    prompt_template: str = ""

    # Output parsing
    decision_key: str = "decision"  # JSON key to look for
    critique_key: str = "critique"


@dataclass
class AgentDecision:
    """Result of an agent run."""
    decision: str  # "advance" | "loop_back"
    critique: str  # feedback text
    output: str  # full LLM response
    body: str = ""  # response text with JSON metadata stripped (for file output)
    loop_count: int = 0
    stage: str = ""
    error: str = ""


def load_agent_config(agent_set: str, stage: str) -> AgentConfig | None:
    """Load agent config for a stage from an agent set.

    Args:
        agent_set: Name of the agent set directory (e.g. "default", "editorial").
        stage: Stage key (e.g. "review", "revise").
    """
    config_dir = AGENTS_DIR / agent_set
    config_file = config_dir / "config.yaml"
    prompt_file = config_dir / f"{stage}.prompt.md"

    if not config_file.exists():
        logger.warning("Agent config not found: %s", config_file)
        return None

    # Load global config
    with open(config_file) as f:
        cfg = yaml.safe_load(f) or {}

    # Validate (warnings only, never blocks)
    try:
        from .config_validation import validate_config, AGENT_SET_SCHEMA
        validate_config(cfg, AGENT_SET_SCHEMA, context=f"agents/{agent_set}/config.yaml")
    except Exception:
        pass

    # Load global model config first, then overlay agent set config
    global_cfg = load_model_config()

    # Load prompt template
    prompt_template = ""
    if prompt_file.exists():
        prompt_template = prompt_file.read_text(encoding="utf-8")

    # Build config — global model.yaml is base, agent set can override
    stage_cfg = cfg.get("stages", {}).get(stage, {})
    if os.environ.get("QUILL_TESTING") != "1":
        api_base = os.environ.get("QUILL_API_BASE") or cfg.get("api_base", global_cfg.get("api_base", "https://api.openai.com/v1"))
        api_key = os.environ.get("QUILL_API_KEY") or cfg.get("api_key", global_cfg.get("api_key", ""))
        model = os.environ.get("QUILL_API_MODEL") or cfg.get("model", global_cfg.get("model", "gpt-4o"))
    else:
        api_base = cfg.get("api_base", global_cfg.get("api_base", "https://api.openai.com/v1"))
        api_key = os.environ.get("QUILL_API_KEY") or cfg.get("api_key", global_cfg.get("api_key", ""))
        model = cfg.get("model", global_cfg.get("model", "gpt-4o"))

    return AgentConfig(
        stage=stage,
        name=stage_cfg.get("name", f"{stage} agent"),
        description=stage_cfg.get("description", ""),
        api_base=api_base,
        api_key=api_key,
        model=model,
        temperature=stage_cfg.get("temperature", cfg.get("temperature", global_cfg.get("temperature", 0.7))),
        max_tokens=stage_cfg.get("max_tokens", cfg.get("max_tokens", global_cfg.get("max_tokens", 4096))),
        max_loops=stage_cfg.get("max_loops", cfg.get("max_loops", 3)),
        trigger=stage_cfg.get("trigger", cfg.get("trigger", "on_advance")),
        prompt_template=prompt_template,
    )


def load_research_config(agent_set: str) -> dict:
    """Load research configuration for an agent set.

    Returns dict with 'enabled' (bool) and 'required' (bool).
    Defaults to enabled=False if not configured.
    """
    config_file = AGENTS_DIR / agent_set / "config.yaml"
    if not config_file.exists():
        return {"enabled": False, "required": False}
    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    research = cfg.get("research", {})
    return {
        "enabled": research.get("enabled", False),
        "required": research.get("required", False),
    }


def list_agent_sets() -> list[dict]:
    """List available agent sets."""
    sets = []
    if not AGENTS_DIR.exists():
        return sets
    for d in sorted(AGENTS_DIR.iterdir()):
        if d.is_dir() and (d / "config.yaml").exists():
            cfg = yaml.safe_load((d / "config.yaml").read_text()) or {}
            stages = list(cfg.get("stages", {}).keys())
            sets.append({
                "name": d.name,
                "description": cfg.get("description", ""),
                "stages": stages,
            })
    return sets


def list_agent_prompts(agent_set: str) -> list[dict]:
    """List prompt templates in an agent set."""
    config_dir = AGENTS_DIR / agent_set
    if not config_dir.exists():
        return []
    prompts = []
    for f in sorted(config_dir.glob("*.prompt.md")):
        stage = f.stem.replace(".prompt", "")
        content = f.read_text(encoding="utf-8")
        # Extract first line as title
        title = content.split("\n")[0].lstrip("# ").strip() if content else stage
        prompts.append({
            "stage": stage,
            "file": str(f),
            "title": title,
            "length": len(content),
        })
    return prompts


from pydantic import BaseModel, Field

class ContentStageOutput(BaseModel):
    """Output schema for content generation stages."""
    content: str = Field(description="The primary markdown text generated by the stage")

class FeedbackStageOutput(BaseModel):
    """Output schema for feedback, critique, and validation stages."""
    critique: str = Field(description="Detailed feedback, annotations, and suggestions")
