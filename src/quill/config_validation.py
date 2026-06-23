"""Config validation — lightweight key checking for YAML configs.

Warns about unknown keys and missing required keys without adding
heavy dependencies like pydantic or marshmallow.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Known keys for model.yaml
MODEL_SCHEMA = {
    "required": [],
    "optional": [
        "api_base", "api_key", "model", "temperature", "max_tokens",
        "max_loops", "trigger", "debug_prompts", "structured_output",
        "context_window", "chain_retry", "research",
    ],
}

# Known keys for agent set config.yaml
AGENT_SET_SCHEMA = {
    "required": [],
    "optional": [
        "description", "temperature", "max_tokens", "max_loops",
        "trigger", "research", "stages", "chain_retry",
    ],
}

# Known keys for per-stage config inside agent set
STAGE_CONFIG_SCHEMA = {
    "required": [],
    "optional": [
        "name", "description", "temperature", "max_tokens",
        "max_loops", "trigger",
    ],
}


def validate_config(data: dict[str, Any], schema: dict, context: str = "") -> list[str]:
    """Validate a config dict against a schema.

    Returns list of warning messages. Empty list means valid.
    """
    warnings = []
    if not isinstance(data, dict):
        return [f"{context}: expected dict, got {type(data).__name__}"]

    known = set(schema["required"] + schema["optional"])
    for key in data:
        if key not in known:
            warnings.append(f"{context}: unknown key '{key}' (typo? check spelling)")

    for key in schema["required"]:
        if key not in data:
            warnings.append(f"{context}: missing required key '{key}'")

    for w in warnings:
        logger.warning(w)

    return warnings
