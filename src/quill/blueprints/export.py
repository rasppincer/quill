"""Google Docs, comic, audio export."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, render_template, send_from_directory

from .shared import get_pipeline
from ..piece import get_piece, _FRONTMATTER_RE, _stage_filename

logger = logging.getLogger(__name__)

bp = Blueprint("export", __name__)


# ---------------------------------------------------------------------------
# Google Docs export
# ---------------------------------------------------------------------------


@bp.route("/api/pieces/<piece_id>/export/google-docs", methods=["POST"])
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
    stage_file = piece.stage_dir() / _stage_filename(stage)
    if not stage_file.exists():
        return jsonify({"error": f"Stage file '{stage}.md' not found"}), 404

    text = stage_file.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text

    if not body.strip():
        return jsonify({"error": f"Stage '{stage}' has no content to export"}), 400

    try:
        from ..gdocs import create_doc
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


# ---------------------------------------------------------------------------
# Comic generation
# ---------------------------------------------------------------------------


@bp.route("/api/pieces/<piece_id>/comic", methods=["POST"])
def pieces_comic(piece_id: str):
    """Generate a comic adaptation of a piece.

    JSON body:
        stage: Which stage to use (default: current stage).
        style: Comic style — "manga", "western", or "noir" (default: "manga").
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    data = request.get_json(silent=True) or {}
    stage = data.get("stage", piece.current_stage)
    style = data.get("style", "manga")

    if style not in ("manga", "western", "noir"):
        return jsonify({"error": f"Invalid style '{style}'. Use: manga, western, noir"}), 400

    try:
        from ..comic import generate_comic_html, save_comic_html
        html = generate_comic_html(piece, stage=stage, style=style)
        output_path = save_comic_html(piece, html)
        return jsonify({
            "piece_id": piece_id,
            "stage": stage,
            "style": style,
            "path": str(output_path),
            "viewer_url": f"/pieces/{piece_id}/comic",
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except ConnectionError as e:
        return jsonify({"error": f"LLM error: {e}"}), 502
    except Exception as e:
        logger.exception("Comic generation failed")
        return jsonify({"error": f"Comic generation failed: {e}"}), 500


@bp.route("/pieces/<piece_id>/comic")
def dashboard_comic(piece_id: str):
    """View generated comic for a piece."""
    piece = get_piece(piece_id)
    if not piece:
        return render_template("dashboard.html"), 404

    comic_file = piece.stage_dir() / "comic" / "comic.html"
    if not comic_file.exists():
        return render_template("dashboard.html"), 404

    return comic_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Audio generation (TTS)
# ---------------------------------------------------------------------------


@bp.route("/api/pieces/<piece_id>/audio", methods=["POST"])
def pieces_audio_generate(piece_id: str):
    """Generate an audio version of a piece using text-to-speech.

    JSON body (all optional):
        stage: Which stage to read (default: current stage).
        voice: edge-tts voice ID (default: auto from piece language).
        rate: Speech rate, e.g. "+10%", "-20%" (default: "+0%").
        pitch: Pitch adjustment, e.g. "+5Hz" (default: "+0Hz").
        volume: Volume adjustment, e.g. "+0%" (default: "+0%").
        filename: Output filename (default: "<stage>_<timestamp>.mp3").
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    data = request.get_json(silent=True) or {}
    stage = data.get("stage", piece.current_stage)

    # Load the stage content
    stage_file = piece.stage_dir() / _stage_filename(stage)
    if not stage_file.exists():
        return jsonify({"error": f"Stage file '{stage}.md' not found"}), 404

    text = stage_file.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text

    if not body.strip():
        return jsonify({"error": f"Stage '{stage}' has no content"}), 400

    # Audio options from request
    from ..audio import AudioOptions, generate_audio

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = data.get("filename", f"{stage}_{ts}.mp3")

    options = AudioOptions(
        voice=data.get("voice", ""),
        rate=data.get("rate", "+0%"),
        pitch=data.get("pitch", "+0Hz"),
        volume=data.get("volume", "+0%"),
        language=data.get("language", piece.language),
    )

    try:
        result = generate_audio(
            text=body,
            output_dir=piece.stage_dir() / "audio",
            filename=filename,
            options=options,
        )
        return jsonify({
            "piece_id": piece_id,
            "stage": stage,
            "filename": result.filename,
            "voice": result.voice,
            "size_bytes": result.size_bytes,
            "path": result.path,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/pieces/<piece_id>/audio")
def pieces_audio_list(piece_id: str):
    """List all generated audio files for a piece."""
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    from ..audio import list_audio_files

    files = list_audio_files(piece.stage_dir())
    return jsonify({"piece_id": piece_id, "files": files, "count": len(files)})


@bp.route("/api/pieces/<piece_id>/audio/<filename>")
def pieces_audio_download(piece_id: str, filename: str):
    """Download a generated audio file."""
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    audio_dir = piece.stage_dir() / "audio"
    if not audio_dir.exists():
        return jsonify({"error": "No audio files found"}), 404

    file_path = audio_dir / filename
    if not file_path.exists():
        return jsonify({"error": f"File '{filename}' not found"}), 404

    return send_from_directory(str(audio_dir), filename, as_attachment=True)


@bp.route("/api/audio/voices")
def audio_voices():
    """List available TTS voices, optionally filtered by language.

    Query params:
        language: Language code filter (e.g., 'en', 'bg', 'de').
    """
    from ..audio import list_voices, VOICE_PRESETS

    language = request.args.get("language", "")

    # Return presets if no language specified (faster, curated list)
    if not language:
        return jsonify({"presets": VOICE_PRESETS})

    try:
        voices = asyncio.run(list_voices(language))
        return jsonify({"language": language, "voices": voices})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
