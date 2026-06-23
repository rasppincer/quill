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
        return {}
    mtime = MODEL_CONFIG_FILE.stat().st_mtime
    if _model_config_cache and _model_config_cache[0] == mtime:
        return _model_config_cache[1]
    with open(MODEL_CONFIG_FILE) as f:
        cfg = yaml.safe_load(f) or {}
    _model_config_cache = (mtime, cfg)
    # Validate on cache miss (warnings only, never blocks)
    try:
        from .config_validation import validate_config, MODEL_SCHEMA
        validate_config(cfg, MODEL_SCHEMA, context="model.yaml")
    except Exception:
        pass
    return cfg


def save_model_config(cfg: dict):
    """Save global model configuration to agents/model.yaml."""
    MODEL_CONFIG_FILE.write_text(
        yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


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
    return AgentConfig(
        stage=stage,
        name=stage_cfg.get("name", f"{stage} agent"),
        description=stage_cfg.get("description", ""),
        api_base=cfg.get("api_base", global_cfg.get("api_base", "https://api.openai.com/v1")),
        api_key=os.environ.get("QUILL_API_KEY") or cfg.get("api_key", global_cfg.get("api_key", "")),
        model=cfg.get("model", global_cfg.get("model", "gpt-4o")),
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


def _strip_json_block(response: str) -> str:
    """Remove trailing JSON decision block from the response, leaving content.

    Only strips JSON that appears at or near the END of the response
    (the decision block). JSON code examples in the middle of content
    (e.g., API tutorials, programming blogs) are preserved.
    """
    cleaned = response

    # Strip trailing ```json ... ``` block (decision block at end)
    # Find the last ```json and check if it's a decision block
    last_json_marker = cleaned.rfind('```json\n')
    if last_json_marker != -1:
        after_marker = cleaned[last_json_marker + 8:]  # len('```json\n') = 8
        end_fence = after_marker.rfind('```')
        if end_fence != -1:
            json_str = after_marker[:end_fence].strip()
            try:
                data = json.loads(json_str)
                if "decision" in data:
                    cleaned = cleaned[:last_json_marker].strip()
            except json.JSONDecodeError:
                pass

    # Strip trailing bare JSON decision block
    trailing_bare = re.search(r'\n\{[^{}]*"decision"\s*:\s*"[^"]*"[^{}]*\}\s*$', cleaned)
    if trailing_bare:
        cleaned = cleaned[:trailing_bare.start()].strip()

    # Strip example markers the agent may have copied from prompts
    cleaned = re.sub(r'\(?\w+ text (?:starts|ends) here\)?\s*', '', cleaned)
    return cleaned.strip()


def parse_agent_response(response: str) -> AgentDecision:
    """Parse an LLM response into an AgentDecision.

    Expects the response to contain a JSON block with:
    {
        "decision": "advance" | "loop_back",
        "critique": "feedback text..."
    }

    Falls back to heuristic parsing if JSON not found.
    """
    body = _strip_json_block(response)

    # Try to extract JSON block
    json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            return AgentDecision(
                decision=data.get("decision", "advance"),
                critique=data.get("critique", ""),
                output=response,
                body=body,
            )
        except json.JSONDecodeError:
            pass

    # Try bare JSON (no code block)
    json_match = re.search(r'\{[^{}]*"decision"\s*:\s*"[^"]*"[^{}]*\}', response)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            return AgentDecision(
                decision=data.get("decision", "advance"),
                critique=data.get("critique", ""),
                output=response,
                body=body,
            )
        except json.JSONDecodeError:
            pass

    # Heuristic: look for decision keywords (be conservative — avoid matching
    # instructional text like "use loop_back if..." in prompts echoed by the LLM)
    decision = "advance"
    lower = response.lower()
    # Only match loop_back if it appears as a standalone decision, not in instructional context
    if re.search(r'(?<!\w)loop[_\s]back(?!\w)', lower) and not re.search(r'(use|choose|if|option|type)\s+loop[_\s]back', lower):
        decision = "loop_back"
    elif re.search(r'\bdecision\s*[:=]\s*["\']?loop', lower):
        decision = "loop_back"
    elif "needs revision" in lower or "needs work" in lower or "reject" in lower:
        decision = "loop_back"

    return AgentDecision(
        decision=decision,
        critique=response,
        output=response,
        body=body,
    )
