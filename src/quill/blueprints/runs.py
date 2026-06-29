"""Run execution, async, SSE, run-log, debug prompt."""

from __future__ import annotations

import json
import logging
import uuid

from flask import Blueprint, jsonify, request, Response, stream_with_context

from .shared import get_pipeline
from ..piece import get_piece
from ..runner import StageRunner, RunManager

logger = logging.getLogger(__name__)

bp = Blueprint("runs", __name__)


@bp.route("/api/pieces/<piece_id>/run", methods=["POST"])
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

    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    # Block manual run during auto mode
    if piece.trigger == "auto" and RunManager().is_piece_running(piece_id):
        return jsonify({"error": "Piece is in auto mode — cannot run agent manually"}), 409

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

        # If running on an earlier stage, supersede later stages
        from ..pipeline import load_pipeline
        pipeline = load_pipeline("default")
        if target_stage in pipeline.stage_order and piece.current_stage in pipeline.stage_order:
            target_idx = pipeline.stage_order.index(target_stage)
            current_idx = pipeline.stage_order.index(piece.current_stage)
            if target_idx < current_idx:
                piece.supersede_from(target_stage)

        trace_id = str(uuid.uuid4())

        # Try orchestrator first (for multi-chapter pieces)
        from ..orchestrator import Orchestrator
        orch = Orchestrator(agent_set=agent_set)
        orch_result = orch.run_stage(piece_id, target_stage, output_dir=None)
        if orch_result is not None:
            return jsonify({
                "piece_id": piece_id,
                "stage": orch_result.stage,
                "decision": orch_result.decision,
                "critique": orch_result.critique,
                "loop_count": 0,
                "error": orch_result.error,
                "orchestrated": True,
            })

        # Fall back to normal StageRunner
        result = runner.run_stage(piece_id, target_stage, trace_id=trace_id)
        return jsonify({
            "piece_id": piece_id,
            "stage": result.stage,
            "decision": result.decision,
            "critique": result.critique,
            "loop_count": result.loop_count,
            "error": result.error,
        })


@bp.route("/api/pieces/<piece_id>/run-async", methods=["POST"])
def pieces_run_async(piece_id: str):
    """Start an async agent run with SSE progress streaming.

    JSON body:
        stage: Stage to run (default: current stage).
        agent_set: Agent set to use (default: "default").
        chain: If true, run all remaining stages.

    Returns:
        {"run_id": "...", "piece_id": "...", "stage": "..."}
    """
    data = request.get_json(silent=True) or {}
    stage = data.get("stage")
    chain = data.get("chain", False)

    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    agent_set = data.get("agent_set") or piece.agent_set or "default"

    manager = RunManager()
    run_id = manager.start_run(
        piece_id=piece_id,
        stage=stage or piece.current_stage,
        agent_set=agent_set,
        chain=chain,
    )

    if run_id is None:
        return jsonify({"error": f"Piece '{piece_id}' already has a running job"}), 409

    return jsonify({
        "run_id": run_id,
        "piece_id": piece_id,
        "stage": stage or piece.current_stage,
    })


@bp.route("/api/pieces/<piece_id>/runs/<run_id>/events")
def pieces_run_events(piece_id: str, run_id: str):
    """SSE endpoint for live run progress.

    Streams Server-Sent Events until the run completes.
    Event types: stage_start, stage_llm_call, stage_complete,
                 loop_start, chain_start, chain_stage_complete,
                 chain_complete, run_complete, error.
    """
    manager = RunManager()

    run = manager.get_run(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    if run["piece_id"] != piece_id:
        return jsonify({"error": "Run does not belong to this piece"}), 404

    def generate():
        for event_str in manager.get_events(run_id):
            yield event_str

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@bp.route("/api/pieces/<piece_id>/run-log")
def pieces_run_log(piece_id: str):
    """Get the run log for a piece.

    Query params:
        stage: Filter by stage (optional).
        limit: Max entries to return (default: 50).
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    log_file = piece.stage_dir() / "run-log.jsonl"
    if not log_file.exists():
        return jsonify({"entries": [], "count": 0})

    stage_filter = request.args.get("stage")
    limit = int(request.args.get("limit", 50))

    entries = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if stage_filter and entry.get("stage") != stage_filter:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    # Return most recent first
    entries.reverse()
    entries = entries[:limit]

    return jsonify({"entries": entries, "count": len(entries)})


@bp.route("/api/pieces/<piece_id>/prompt/<stage>")
def pieces_debug_prompt(piece_id: str, stage: str):
    """Debug: show the composed prompt for a stage without calling the LLM.

    Query params:
        agent_set: Agent set to use (default: piece's agent_set or "default").
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    agent_set = request.args.get("agent_set") or piece.agent_set or "default"
    runner = StageRunner(agent_set=agent_set)
    result = runner.compose_prompt(piece_id, stage)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


# ---------------------------------------------------------------------------
# Auto pipeline
# ---------------------------------------------------------------------------


@bp.route("/api/pieces/<piece_id>/auto", methods=["POST"])
def pieces_auto(piece_id: str):
    """Start the auto pipeline — runs all remaining stages.

    The piece must have trigger set to 'auto' and brief content.
    While running, run/advance endpoints are blocked.
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    if RunManager().is_piece_running(piece_id):
        return jsonify({"error": f"Piece '{piece_id}' already has a running job"}), 409

    # Require brief content
    from ..piece import _stage_filename
    brief_file = piece.stage_dir() / _stage_filename("brief")
    if brief_file.exists():
        from ..piece import _FRONTMATTER_RE
        text = brief_file.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        body = text[m.end():] if m else text
        if not body.strip():
            return jsonify({"error": "Brief has no content. Write your brief before starting auto pipeline."}), 400
    else:
        return jsonify({"error": "Brief has no content. Write your brief before starting auto pipeline."}), 400

    # Set trigger to auto
    piece.trigger = "auto"
    piece.save()

    agent_set = piece.agent_set or "default"
    manager = RunManager()
    run_id = manager.start_run(
        piece_id=piece_id,
        stage=piece.current_stage,
        agent_set=agent_set,
        chain=True,
    )

    if run_id is None:
        return jsonify({"error": f"Piece '{piece_id}' already has a running job"}), 409

    return jsonify({
        "run_id": run_id,
        "piece_id": piece_id,
        "stage": piece.current_stage,
        "trigger": "auto",
    })


@bp.route("/api/pieces/<piece_id>/interrupt", methods=["POST"])
def pieces_interrupt(piece_id: str):
    """Interrupt the auto pipeline after the current stage completes.

    Downgrades trigger to 'on_advance'.
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    manager = RunManager()

    if not manager.is_piece_running(piece_id):
        return jsonify({"error": f"Piece '{piece_id}' has no running job"}), 400

    # Signal interrupt
    manager.interrupt(piece_id)

    # Downgrade trigger
    piece.trigger = "on_advance"
    piece.save()

    return jsonify({
        "piece_id": piece_id,
        "trigger": "on_advance",
        "status": "interrupt_requested",
    })
