"""Flask application — Quill writing workflow API.

Endpoints:
    GET  /health                       — Health check
    GET  /api/pieces                   — List all pieces + current stages
    POST /api/pieces                   — Create new piece from brief
    GET  /api/pieces/<id>              — Piece detail
    POST /api/pieces/<id>/advance      — Advance to next stage
    POST /api/pieces/<id>/reject       — Revert to a previous stage
    GET  /api/pipeline                 — Pipeline stage definitions
"""

from __future__ import annotations

import json
import logging
import re
import yaml
from datetime import datetime, timezone

from flask import Flask, jsonify, request, render_template, redirect, url_for

from pathlib import Path
from werkzeug.middleware.proxy_fix import ProxyFix

# Load .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass  # python-dotenv not installed — rely on env vars from systemd/shell
from .pipeline import load_pipeline
from .piece import Piece, get_piece, list_pieces, load_piece, _FRONTMATTER_RE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_pkg_dir = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(_pkg_dir / "templates"),
    static_folder=str(_pkg_dir / "static"),
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_prefix=1)


@app.context_processor
def inject_base():
    """Inject base URL prefix for static files behind a reverse proxy."""
    prefix = request.headers.get("X-Forwarded-Prefix", "")
    return {"base": prefix}

pipeline = load_pipeline("default")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Redirect to dashboard."""
    return redirect(url_for("dashboard"))



@app.route("/health")
def health():
    """Health check."""
    pieces = list_pieces()
    return jsonify({
        "status": "ok",
        "piece_count": len(pieces),
        "pipeline": pipeline.name,
        "stages": pipeline.stage_order,
    })


# ---------------------------------------------------------------------------
# Pipeline info
# ---------------------------------------------------------------------------


@app.route("/api/pipeline")
def pipeline_info():
    """Get pipeline stage definitions."""
    return jsonify({
        "name": pipeline.name,
        "description": pipeline.description,
        "stages": [
            {
                "key": s.key,
                "name": s.name,
                "description": s.description,
                "next": s.next,
                "can_reject_to": s.can_reject_to,
            }
            for s in pipeline.stages.values()
        ],
    })


# ---------------------------------------------------------------------------
# Pieces CRUD
# ---------------------------------------------------------------------------


@app.route("/api/pieces")
def pieces_list():
    """List all pieces with current stage and progress."""
    pieces = list_pieces()
    result = []
    for p in pieces:
        d = p.to_dict()
        d["progress"] = pipeline.progress(p.current_stage)
        result.append(d)
    return jsonify({"count": len(result), "pieces": result})


@app.route("/api/pieces", methods=["POST"])
def pieces_create():
    """Create a new piece from brief data.

    JSON body:
        title (required): Piece title.
        genre: fiction | non-fiction
        type: story | blog | editorial | analysis | tutorial | essay
        audience: Target audience.
        tone: Tone/style.
        language: en | bg | mixed
        target_length: e.g. "5000-8000 words"
        constraints: List of constraints.
        body: Brief content (optional).
    """
    data = request.get_json(silent=True) or {}

    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Missing 'title'"}), 400

    # Generate ID from title
    piece_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
    if not piece_id:
        piece_id = f"piece-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    # Check for duplicate
    if get_piece(piece_id):
        return jsonify({"error": f"Piece '{piece_id}' already exists"}), 409

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    piece = Piece(
        id=piece_id,
        title=title,
        genre=data.get("genre", ""),
        type=data.get("type", ""),
        audience=data.get("audience", ""),
        tone=data.get("tone", ""),
        language=data.get("language", ""),
        target_length=data.get("target_length", ""),
        constraints=data.get("constraints", []) or [],
        current_stage="brief",
        created=now,
        updated=now,
        body=data.get("body", ""),
    )

    path = piece.save()
    return jsonify({"id": piece.id, "title": piece.title, "stage": piece.current_stage, "path": str(path)}), 201


@app.route("/api/pieces/<piece_id>")
def pieces_get(piece_id: str):
    """Get piece detail."""
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    d = piece.to_dict()
    d["progress"] = pipeline.progress(piece.current_stage)

    # Include metrics for current stage
    from .metrics import maybe_recompute
    stage_file = piece.stage_dir() / f"{piece.current_stage}.md"
    d["metrics"] = maybe_recompute(stage_file)

    return jsonify(d)


# ---------------------------------------------------------------------------
# Stage management
# ---------------------------------------------------------------------------


@app.route("/api/pieces/<piece_id>/advance", methods=["POST"])
def pieces_advance(piece_id: str):
    """Advance a piece to the next stage."""
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    next_stage = pipeline.next_stage(piece.current_stage)
    if not next_stage:
        return jsonify({"error": f"Piece is at final stage '{piece.current_stage}'"}), 400

    valid, msg = pipeline.validate_transition(piece.current_stage, next_stage)
    if not valid:
        return jsonify({"error": msg}), 400

    old_stage = piece.current_stage

    # Save current stage file (preserves its body)
    if not piece._is_legacy:
        piece.save()

    # Advance: update meta.yaml to point to next stage
    piece.current_stage = next_stage
    # Only clear body if the next stage file doesn't already exist
    next_stage_file = piece.stage_dir() / f"{next_stage}.md"
    if not next_stage_file.exists():
        piece.body = ""
    else:
        # Load existing stage file body
        text = next_stage_file.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        piece.body = text[m.end():] if m else text
    piece.save()

    # Compute metrics for the stage we just left (if it has content)
    from .metrics import maybe_recompute
    old_stage_file = piece.stage_dir() / f"{old_stage}.md"
    if old_stage_file.exists():
        maybe_recompute(old_stage_file)

    return jsonify({
        "id": piece.id,
        "previous_stage": old_stage,
        "current_stage": piece.current_stage,
        "progress": pipeline.progress(piece.current_stage),
    })


@app.route("/api/pieces/<piece_id>/reject", methods=["POST"])
def pieces_reject(piece_id: str):
    """Revert a piece to a previous stage.

    JSON body:
        target (required): Stage to revert to.
        reason: Why the revert is happening.
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    data = request.get_json(silent=True) or {}
    target = data.get("target", "").strip()
    if not target:
        return jsonify({"error": "Missing 'target' stage"}), 400

    valid, msg = pipeline.validate_transition(piece.current_stage, target)
    if not valid:
        return jsonify({"error": msg}), 400

    old_stage = piece.current_stage
    piece.current_stage = target

    # Load body from target stage file
    if not piece._is_legacy:
        target_file = piece.stage_dir() / f"{target}.md"
        if target_file.exists():
            text = target_file.read_text(encoding="utf-8")
            m = _FRONTMATTER_RE.match(text)
            piece.body = text[m.end():] if m else text

    piece.save()

    return jsonify({
        "id": piece.id,
        "previous_stage": old_stage,
        "current_stage": piece.current_stage,
        "reason": data.get("reason", ""),
        "progress": pipeline.progress(piece.current_stage),
    })


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Dashboard (frontend)
# ---------------------------------------------------------------------------


@app.route("/dashboard")
def dashboard():
    """Pieces overview page."""
    return render_template("dashboard.html")


@app.route("/pieces/<piece_id>")
def dashboard_piece(piece_id: str):
    """Piece detail page."""
    piece = get_piece(piece_id)
    if not piece:
        return render_template("dashboard.html"), 404

    stages_list = list(pipeline.stages.values())
    progress = pipeline.progress(piece.current_stage)

    # Include metrics for current stage
    from .metrics import maybe_recompute
    stage_file = piece.stage_dir() / f"{piece.current_stage}.md"
    metrics = maybe_recompute(stage_file)

    return render_template(
        "piece.html",
        piece=piece.to_dict(),
        progress=progress,
        pipeline=stages_list,
        pipeline_order=pipeline.stage_order,
        metrics=metrics,
    )


@app.route("/dashboard/pipeline")
def dashboard_pipeline():
    """Pipeline info page."""
    stages_list = list(pipeline.stages.values())
    return render_template("pipeline.html", pipeline=stages_list)


@app.route("/dashboard/agents")
def dashboard_agents():
    """Agent management page."""
    return render_template("agents.html")


# ---------------------------------------------------------------------------
# Agent API
# ---------------------------------------------------------------------------


@app.route("/api/agents")
def agents_list():
    """List available agent sets with prompts ordered by pipeline sequence."""
    from .agent import list_agent_sets, list_agent_prompts
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


@app.route("/api/agents", methods=["POST"])
def agents_create():
    """Create a new flavor (agent set).

    JSON body:
        name (required): Flavor name (lowercase, hyphens).
        description: Flavor description.
        clone_from: Clone prompts from this flavor (default: "default").
    """
    from .agent import AGENTS_DIR
    import shutil

    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip().lower()
    description = data.get("description", "").strip()
    clone_from = data.get("clone_from", "default").strip()

    if not name:
        return jsonify({"error": "Missing 'name'"}), 400

    # Validate name (alphanumeric + hyphens only)
    import re
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


@app.route("/api/agents/<flavor_name>", methods=["DELETE"])
def agents_delete(flavor_name: str):
    """Delete a flavor (agent set).

    Cannot delete 'default' — it's the base flavor.
    """
    from .agent import AGENTS_DIR
    import shutil

    if flavor_name == "default":
        return jsonify({"error": "Cannot delete the 'default' flavor"}), 403

    target_dir = AGENTS_DIR / flavor_name
    if not target_dir.exists():
        return jsonify({"error": f"Flavor '{flavor_name}' not found"}), 404

    shutil.rmtree(target_dir)
    return jsonify({"status": "deleted", "name": flavor_name})


@app.route("/api/model", methods=["GET"])
def model_get():
    """Get global model configuration."""
    from .agent import load_model_config
    return jsonify(load_model_config())


@app.route("/api/model", methods=["PUT"])
def model_put():
    """Update global model configuration.

    JSON body: any subset of api_base, model, temperature, max_tokens.
    api_key is not stored here — use QUILL_API_KEY env var instead.
    """
    from .agent import load_model_config, save_model_config
    current = load_model_config()
    data = request.get_json(silent=True) or {}
    for key in ("api_base", "model", "temperature", "max_tokens"):
        if key in data:
            current[key] = data[key]
    # Strip api_key if sent — it belongs in env, not yaml
    current.pop("api_key", None)
    save_model_config(current)
    return jsonify({"status": "updated", "config": current})


@app.route("/api/models", methods=["GET"])
def models_list():
    """List available models from the configured LLM API."""
    from .agent import load_model_config
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


@app.route("/api/agents/for-stage/<stage>")
def agents_for_stage(stage: str):
    """List agent sets that have a prompt for the given stage."""
    from .agent import list_agent_sets
    from .agent import AGENTS_DIR
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


@app.route("/api/agents/<agent_set>")
def agents_detail(agent_set: str):
    """Get agent set config and prompts sorted by pipeline order."""
    from .agent import load_agent_config, list_agent_prompts, AGENTS_DIR
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


@app.route("/api/agents/<agent_set>/<stage>/prompt", methods=["GET"])
def agents_get_prompt(agent_set: str, stage: str):
    """Get prompt template for a stage."""
    from .agent import AGENTS_DIR
    prompt_file = AGENTS_DIR / agent_set / f"{stage}.prompt.md"
    if not prompt_file.exists():
        return jsonify({"error": f"Prompt not found"}), 404
    return jsonify({"stage": stage, "content": prompt_file.read_text(encoding="utf-8")})


@app.route("/api/agents/<agent_set>/<stage>/prompt", methods=["PUT"])
def agents_update_prompt(agent_set: str, stage: str):
    """Update prompt template for a stage."""
    from .agent import AGENTS_DIR
    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "Missing 'content'"}), 400

    prompt_file = AGENTS_DIR / agent_set / f"{stage}.prompt.md"
    if not prompt_file.parent.exists():
        return jsonify({"error": f"Agent set '{agent_set}' not found"}), 404

    prompt_file.write_text(content, encoding="utf-8")
    return jsonify({"stage": stage, "length": len(content), "status": "updated"})


@app.route("/api/pieces/<piece_id>/run", methods=["POST"])
def pieces_run(piece_id: str):
    """Run an agent on a specific stage or chain all remaining stages.

    JSON body:
        stage: Stage to run (default: current stage).
        agent_set: Agent set to use (default: "default").
        chain: If true, run all remaining stages.
    """
    data = request.get_json(silent=True) or {}
    stage = data.get("stage")
    chain = data.get("chain", False)

    from .runner import StageRunner
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    # Use piece's agent_set, fall back to request body, then "default"
    agent_set = data.get("agent_set") or piece.agent_set or "default"
    runner = StageRunner(agent_set=agent_set)

    if chain:
        results = runner.run_chain(piece_id, from_stage=stage)
        return jsonify({
            "piece_id": piece_id,
            "chain": True,
            "results": [
                {
                    "stage": r.stage,
                    "decision": r.decision,
                    "critique": r.critique[:500] + "..." if len(r.critique) > 500 else r.critique,
                    "loop_count": r.loop_count,
                    "error": r.error,
                }
                for r in results
            ],
        })
    else:
        target_stage = stage or piece.current_stage
        result = runner.run_stage(piece_id, target_stage)
        return jsonify({
            "piece_id": piece_id,
            "stage": result.stage,
            "decision": result.decision,
            "critique": result.critique,
            "loop_count": result.loop_count,
            "error": result.error,
        })




# ---------------------------------------------------------------------------
# Google Docs export
# ---------------------------------------------------------------------------


@app.route("/api/pieces/<piece_id>/export/google-docs", methods=["POST"])
def pieces_export_google_docs(piece_id: str):
    """Export a piece to Google Docs.

    JSON body:
        stage: Which stage to export (default: current stage).
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    data = request.get_json(silent=True) or {}
    stage = data.get("stage", piece.current_stage)

    # Load the stage content
    stage_file = piece.stage_dir() / f"{stage}.md"
    if not stage_file.exists():
        return jsonify({"error": f"Stage file '{stage}.md' not found"}), 404

    text = stage_file.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text

    if not body.strip():
        return jsonify({"error": f"Stage '{stage}' has no content to export"}), 400

    try:
        from .gdocs import create_doc
        title = f"{piece.title} ({stage})"
        result = create_doc(title, body)
        return jsonify({
            "piece_id": piece_id,
            "stage": stage,
            "document_id": result["documentId"],
            "url": result["url"],
            "title": result["title"],
        })
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.exception("Google Docs export failed")
        return jsonify({"error": f"Export failed: {e}"}), 500


def main():
    """Run the server."""
    app.run(host="0.0.0.0", port=8325, debug=False)


if __name__ == "__main__":
    main()
from flask import Flask, jsonify, request, render_template, redirect, url_for, redirect
