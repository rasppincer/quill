"""Agent sets, prompts, model config."""

from __future__ import annotations

import json
import logging
import re
import yaml

from flask import Blueprint, jsonify, request

from .shared import get_pipeline

logger = logging.getLogger(__name__)

bp = Blueprint("agents", __name__)


@bp.route("/api/agents")
def agents_list():
    """List available agent sets with prompts ordered by pipeline sequence."""
    from ..agent import list_agent_sets, list_agent_prompts
    pipeline = get_pipeline()
    sets = list_agent_sets()
    stage_order = pipeline.stage_order
    for s in sets:
        prompts = list_agent_prompts(s["name"])
        # Sort prompts by pipeline stage order
        def prompt_sort_key(p):
            try:
                return stage_order.index(p["stage"])
            except ValueError:
                return len(stage_order)
        prompts.sort(key=prompt_sort_key)
        s["prompts"] = prompts
    return jsonify({"sets": sets, "stage_order": stage_order})


@bp.route("/api/agents", methods=["POST"])
def agents_create():
    """Create a new flavor (agent set).

    JSON body:
        name (required): Flavor name (lowercase, hyphens).
        description: Flavor description.
        clone_from: Clone prompts from this flavor (default: "default").
    """
    from ..agent import AGENTS_DIR
    import shutil

    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip().lower()
    description = data.get("description", "").strip()
    clone_from = data.get("clone_from", "default").strip()

    if not name:
        return jsonify({"error": "Missing 'name'"}), 400

    # Validate name (alphanumeric + hyphens only)
    if not re.match(r"^[a-z0-9][a-z0-9\-]*$", name):
        return jsonify({"error": "Name must be lowercase alphanumeric with hyphens"}), 400

    target_dir = AGENTS_DIR / name
    if target_dir.exists():
        return jsonify({"error": f"Flavor '{name}' already exists"}), 409

    source_dir = AGENTS_DIR / clone_from
    if not source_dir.exists():
        return jsonify({"error": f"Source flavor '{clone_from}' not found"}), 404

    # Copy the source flavor
    shutil.copytree(source_dir, target_dir)

    # Update description in config.yaml
    config_file = target_dir / "config.yaml"
    if config_file.exists():
        cfg = yaml.safe_load(config_file.read_text()) or {}
        cfg["description"] = description or f"Custom flavor: {name}"
        config_file.write_text(
            yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return jsonify({
        "status": "created",
        "name": name,
        "description": description,
        "cloned_from": clone_from,
    }), 201


@bp.route("/api/agents/<flavor_name>", methods=["DELETE"])
def agents_delete(flavor_name: str):
    """Delete a flavor (agent set).

    Cannot delete 'default' — it's the base flavor.
    """
    from ..agent import AGENTS_DIR
    import shutil

    if flavor_name == "default":
        return jsonify({"error": "Cannot delete the 'default' flavor"}), 403

    target_dir = AGENTS_DIR / flavor_name
    if not target_dir.exists():
        return jsonify({"error": f"Flavor '{flavor_name}' not found"}), 404

    shutil.rmtree(target_dir)
    return jsonify({"status": "deleted", "name": flavor_name})


@bp.route("/api/model", methods=["GET"])
def model_get():
    """Get global model configuration."""
    from ..agent import load_model_config
    return jsonify(load_model_config())


@bp.route("/api/model", methods=["PUT"])
def model_put():
    """Update global model configuration.

    JSON body: any subset of api_base, model, temperature, max_tokens.
    api_key is not stored here — use QUILL_API_KEY env var instead.
    """
    from ..agent import load_model_config, save_model_config
    current = load_model_config()
    data = request.get_json(silent=True) or {}
    for key in ("api_base", "model", "temperature", "max_tokens"):
        if key in data:
            current[key] = data[key]
    # Strip api_key if sent — it belongs in env, not yaml
    current.pop("api_key", None)
    save_model_config(current)
    return jsonify({"status": "updated", "config": current})


@bp.route("/api/models", methods=["GET"])
def models_list():
    """List available models from the configured LLM API."""
    from ..agent import load_model_config
    import urllib.request
    cfg = load_model_config()
    api_base = cfg.get("api_base", "")
    if not api_base:
        return jsonify({"models": [], "error": "No api_base configured"})
    try:
        url = f"{api_base.rstrip('/')}/models"
        headers = {}
        if cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = sorted([m["id"] for m in data.get("data", []) if "embed" not in m["id"].lower()])
            return jsonify({"models": models})
    except Exception as e:
        return jsonify({"models": [], "error": str(e)})


@bp.route("/api/agents/for-stage/<stage>")
def agents_for_stage(stage: str):
    """List agent sets that have a prompt for the given stage."""
    from ..agent import AGENTS_DIR
    result = []
    for d in sorted(AGENTS_DIR.iterdir()):
        if d.is_dir() and (d / "config.yaml").exists() and d.name != "__pycache__":
            prompt_file = d / f"{stage}.prompt.md"
            if prompt_file.exists():
                cfg = yaml.safe_load((d / "config.yaml").read_text()) or {}
                result.append({
                    "name": d.name,
                    "description": cfg.get("description", ""),
                })
    return jsonify({"stage": stage, "agent_sets": result})


@bp.route("/api/agents/<agent_set>")
def agents_detail(agent_set: str):
    """Get agent set config and prompts sorted by pipeline order."""
    from ..agent import list_agent_prompts, AGENTS_DIR
    pipeline = get_pipeline()
    config_file = AGENTS_DIR / agent_set / "config.yaml"
    if not config_file.exists():
        return jsonify({"error": f"Agent set '{agent_set}' not found"}), 404

    cfg = yaml.safe_load(config_file.read_text()) or {}
    prompts = list_agent_prompts(agent_set)
    stage_order = pipeline.stage_order
    def prompt_sort_key(p):
        try:
            return stage_order.index(p["stage"])
        except ValueError:
            return len(stage_order)
    prompts.sort(key=prompt_sort_key)
    return jsonify({"config": cfg, "prompts": prompts})


@bp.route("/api/agents/<agent_set>", methods=["PUT"])
def agents_update_config(agent_set: str):
    """Update flavor config (max_loops, trigger, description, temperature).

    JSON body: any subset of max_loops, trigger, description, temperature, max_tokens.
    """
    from ..agent import AGENTS_DIR

    config_file = AGENTS_DIR / agent_set / "config.yaml"
    if not config_file.exists():
        return jsonify({"error": f"Agent set '{agent_set}' not found"}), 404

    data = request.get_json(silent=True) or {}
    cfg = yaml.safe_load(config_file.read_text()) or {}

    for key in ("max_loops", "trigger", "description", "temperature", "max_tokens"):
        if key in data:
            cfg[key] = data[key]

    config_file.write_text(
        yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return jsonify({"status": "updated", "config": cfg})


@bp.route("/api/agents/<agent_set>/<stage>/prompt", methods=["GET"])
def agents_get_prompt(agent_set: str, stage: str):
    """Get prompt template for a stage."""
    from ..agent import AGENTS_DIR
    prompt_file = AGENTS_DIR / agent_set / f"{stage}.prompt.md"
    if not prompt_file.exists():
        return jsonify({"error": f"Prompt not found"}), 404
    return jsonify({"stage": stage, "content": prompt_file.read_text(encoding="utf-8")})


@bp.route("/api/agents/<agent_set>/<stage>/prompt", methods=["PUT"])
def agents_update_prompt(agent_set: str, stage: str):
    """Update prompt template for a stage."""
    from ..agent import AGENTS_DIR
    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "Missing 'content'"}), 400

    prompt_file = AGENTS_DIR / agent_set / f"{stage}.prompt.md"
    if not prompt_file.parent.exists():
        return jsonify({"error": f"Agent set '{agent_set}' not found"}), 404

    prompt_file.write_text(content, encoding="utf-8")
    return jsonify({"stage": stage, "length": len(content), "status": "updated"})
