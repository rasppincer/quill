"""Pieces CRUD + lifecycle + pipeline info."""

from __future__ import annotations

import json
import logging
import re
import yaml
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, redirect, url_for

from .shared import get_pipeline
from ..piece import Piece, get_piece, list_pieces, _FRONTMATTER_RE, _stage_filename
from ..metrics import maybe_recompute
from ..runner import RunManager

logger = logging.getLogger(__name__)

bp = Blueprint("pieces", __name__)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@bp.route("/")
def index():
    """Redirect to dashboard."""
    return redirect(url_for("dashboard.dashboard"))



@bp.route("/health")
def health():
    """Health check."""
    pipeline = get_pipeline()
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


@bp.route("/api/pipeline")
def pipeline_info():
    """Get pipeline stage definitions."""
    pipeline = get_pipeline()
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


@bp.route("/api/pieces")
def pieces_list():
    """List all pieces with current stage and progress."""
    pipeline = get_pipeline()
    pieces = list_pieces()
    result = []
    for p in pieces:
        d = p.to_dict()
        d["progress"] = pipeline.progress(p.current_stage)
        result.append(d)
    return jsonify({"count": len(result), "pieces": result})


@bp.route("/api/pieces", methods=["POST"])
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


@bp.route("/api/pieces/import", methods=["POST"])
def pieces_import():
    """Import a piece, optionally at a mid-progress stage.

    JSON body:
        title (required): Piece title.
        current_stage: Stage to import at (default: "brief").
        genre, type, audience, tone, language, target_length, constraints: Optional metadata.
        body: Content for the current stage (optional).
        stages: Dict of {stage_name: content} to create multiple stage files (optional).
                Each entry creates output/<id>/<stage>.md with frontmatter.
        agent_set: Agent set to use (optional).

    Missing metadata fields default to empty strings. The piece integrates
    seamlessly with the existing work management flow — it can be advanced,
    rejected, and run through agents like any other piece.
    """
    pipeline = get_pipeline()
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

    current_stage = data.get("current_stage", "brief").strip()
    if current_stage not in pipeline.stage_order:
        return jsonify({
            "error": f"Unknown stage '{current_stage}'",
            "valid_stages": pipeline.stage_order,
        }), 400

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
        current_stage=current_stage,
        created=data.get("created", now),
        updated=now,
        agent_set=data.get("agent_set", ""),
        body=data.get("body", ""),
    )

    # Save the piece (creates directory + meta.yaml + current stage file)
    piece.save()

    # If stages dict provided, write additional stage files
    stages_data = data.get("stages") or {}
    for stage_name, stage_content in stages_data.items():
        if stage_name not in pipeline.stage_order:
            continue  # skip unknown stages silently
        if not stage_content:
            continue  # skip empty stages

        stage_file = piece.stage_dir() / _stage_filename(stage_name)
        if stage_file.exists() and stage_name == current_stage:
            continue  # already saved by piece.save()

        frontmatter = piece.to_frontmatter()
        frontmatter["current_stage"] = stage_name
        fm = yaml.dump(
            frontmatter,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        stage_file.write_text(f"---\n{fm}---\n\n{stage_content}", encoding="utf-8")

    logger.info("Imported piece '%s' at stage '%s' (%d stage files)",
                title, current_stage, len(stages_data) + 1)

    return jsonify({
        "id": piece.id,
        "title": piece.title,
        "stage": piece.current_stage,
        "path": str(piece.save()),
        "stages_imported": [current_stage] + [s for s in stages_data if s in pipeline.stage_order],
    }), 201


@bp.route("/api/pieces/<piece_id>")
def pieces_get(piece_id: str):
    """Get piece detail."""
    pipeline = get_pipeline()
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    d = piece.to_dict()
    d["progress"] = pipeline.progress(piece.current_stage)

    # Include metrics for current stage
    stage_file = piece.stage_dir() / _stage_filename(piece.current_stage)
    d["metrics"] = maybe_recompute(stage_file)

    # Read body from stage file when piece.body is empty
    body = piece.body
    if not body and stage_file.exists():
        text = stage_file.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        body = text[m.end():] if m else text
    if not body:
        # Fallback: find the latest stage file with content (skip .decision.md)
        for sf in sorted(piece.stage_dir().glob("*.md"), reverse=True):
            if sf.name.endswith(".decision.md"):
                continue
            try:
                text = sf.read_text(encoding="utf-8")
                m = _FRONTMATTER_RE.match(text)
                body = text[m.end():] if m else text
                if body.strip():
                    break
            except Exception:
                continue
    d["body"] = body
    d["body_length"] = len(body)

    d["running"] = RunManager().is_piece_running(piece_id)

    return jsonify(d)


@bp.route("/api/pieces/<piece_id>/rename", methods=["POST"])
def pieces_rename(piece_id: str):
    """Rename a piece (update title in meta.yaml and all stage files).

    JSON body:
        title (required): New title.
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    data = request.get_json(silent=True) or {}
    new_title = data.get("title", "").strip()
    if not new_title:
        return jsonify({"error": "Missing 'title'"}), 400

    old_title = piece.title
    piece.title = new_title
    piece.updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Update ONLY meta.yaml — do NOT call piece.save() which would
    # overwrite the current stage file with frontmatter + empty body.
    stage_dir = piece.stage_dir()
    meta_path = stage_dir / "meta.yaml"
    if meta_path.exists():
        meta_data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        meta_data["title"] = new_title
        meta_data["updated"] = piece.updated
        meta_path.write_text(
            yaml.dump(meta_data, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    # Update title in ALL stage files' frontmatter (patch in-place, don't rewrite)
    for md_file in stage_dir.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
            m = _FRONTMATTER_RE.match(text)
            if m:
                fm = yaml.safe_load(m.group(1)) or {}
                if fm.get("title") == old_title:
                    fm["title"] = new_title
                    new_fm = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False)
                    new_text = f"---\n{new_fm}---\n{text[m.end():]}"
                    md_file.write_text(new_text, encoding="utf-8")
        except Exception:
            pass

    return jsonify({
        "id": piece.id,
        "old_title": old_title,
        "new_title": new_title,
    })


# ---------------------------------------------------------------------------
# Brief content editing
# ---------------------------------------------------------------------------


@bp.route("/api/pieces/<piece_id>/brief", methods=["GET"])
def pieces_brief_get(piece_id: str):
    """Get brief content (body below frontmatter)."""
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    stage_file = piece.stage_dir() / _stage_filename("brief")
    body = ""
    if stage_file.exists():
        text = stage_file.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        body = text[m.end():] if m else text

    has_content = bool(body.strip())
    return jsonify({"content": body, "has_content": has_content})


@bp.route("/api/pieces/<piece_id>/brief", methods=["PUT"])
def pieces_brief_put(piece_id: str):
    """Save brief content (body below frontmatter).

    JSON body:
        content (required): The brief text to save.
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    data = request.get_json(silent=True) or {}
    content = data.get("content", "")

    stage_file = piece.stage_dir() / _stage_filename("brief")
    if stage_file.exists():
        # Preserve frontmatter, replace body
        text = stage_file.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if m:
            new_text = f"{text[:m.end()]}{content}"
        else:
            new_text = content
    else:
        # Create new file with minimal frontmatter
        fm = yaml.dump({
            "id": piece.id, "title": piece.title,
            "genre": piece.genre, "type": piece.type,
            "language": piece.language,
            "current_stage": "brief",
        }, default_flow_style=False, allow_unicode=True, sort_keys=False)
        new_text = f"---\n{fm}---\n{content}"

    stage_file.write_text(new_text, encoding="utf-8")

    return jsonify({"status": "saved", "has_content": bool(content.strip())})


# ---------------------------------------------------------------------------
# Stage management
# ---------------------------------------------------------------------------


@bp.route("/api/pieces/<piece_id>/advance", methods=["POST"])
def pieces_advance(piece_id: str):
    """Advance a piece to the next stage."""
    pipeline = get_pipeline()
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    if RunManager().is_piece_running(piece_id):
        return jsonify({"error": f"Piece '{piece_id}' has a running job — wait for it to complete"}), 409

    # Brief stage requires user-written content before advancing
    if piece.current_stage == "brief":
        stage_file = piece.stage_dir() / _stage_filename("brief")
        body = ""
        if stage_file.exists():
            text = stage_file.read_text(encoding="utf-8")
            m = _FRONTMATTER_RE.match(text)
            body = text[m.end():] if m else text
        if not body.strip():
            return jsonify({
                "error": "Brief has no content. Write your brief before advancing.",
                "hint": "Describe what you want written — the topic, angle, key points, style.",
            }), 400

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
    next_stage_file = piece.stage_dir() / _stage_filename(next_stage)
    if not next_stage_file.exists():
        piece.body = ""
    else:
        # Load existing stage file body
        text = next_stage_file.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        piece.body = text[m.end():] if m else text
    piece.save()

    # Compute metrics for the stage we just left (if it has content)
    old_stage_file = piece.stage_dir() / _stage_filename(old_stage)
    if old_stage_file.exists():
        maybe_recompute(old_stage_file)

    return jsonify({
        "id": piece.id,
        "previous_stage": old_stage,
        "current_stage": piece.current_stage,
        "progress": pipeline.progress(piece.current_stage),
    })


@bp.route("/api/pieces/<piece_id>/reject", methods=["POST"])
def pieces_reject(piece_id: str):
    """Revert a piece to a previous stage.

    JSON body:
        target (required): Stage to revert to.
        reason: Why the revert is happening.
    """
    pipeline = get_pipeline()
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    if RunManager().is_piece_running(piece_id):
        return jsonify({"error": f"Piece '{piece_id}' has a running job — wait for it to complete"}), 409

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
        target_file = piece.stage_dir() / _stage_filename(target)
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
