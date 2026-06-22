"""Dashboard HTML routes."""

from __future__ import annotations

import logging

from flask import Blueprint, render_template

from .shared import get_pipeline
from ..piece import get_piece, _stage_filename

logger = logging.getLogger(__name__)

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
def dashboard():
    """Pieces overview page."""
    return render_template("dashboard.html")


@bp.route("/pieces/<piece_id>")
def dashboard_piece(piece_id: str):
    """Piece detail page."""
    pipeline = get_pipeline()
    piece = get_piece(piece_id)
    if not piece:
        return render_template("dashboard.html"), 404

    stages_list = list(pipeline.stages.values())
    progress = pipeline.progress(piece.current_stage)

    # Include metrics for current stage
    from ..metrics import maybe_recompute
    stage_file = piece.stage_dir() / _stage_filename(piece.current_stage)
    metrics = maybe_recompute(stage_file)

    return render_template(
        "piece.html",
        piece=piece.to_dict(),
        progress=progress,
        pipeline=stages_list,
        pipeline_order=pipeline.stage_order,
        metrics=metrics,
    )


@bp.route("/dashboard/pipeline")
def dashboard_pipeline():
    """Pipeline info page."""
    pipeline = get_pipeline()
    stages_list = list(pipeline.stages.values())
    return render_template("pipeline.html", pipeline=stages_list)


@bp.route("/dashboard/agents")
def dashboard_agents():
    """Agent management page."""
    return render_template("agents.html")
