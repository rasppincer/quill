"""Run logging — JSONL append to run-log.jsonl per piece."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .piece import Piece

logger = logging.getLogger(__name__)


class RunLogger:
    """Appends structured run log entries to run-log.jsonl."""

    def __init__(self):
        from .agent import load_model_config
        cfg = load_model_config()
        self._model = cfg.get("model", "")
        self._debug = cfg.get("debug_prompts", False)

    def log(
        self,
        piece: "Piece",
        stage: str,
        call_type: str,
        system: str,
        user: str,
        result: dict | None = None,
    ):
        """Append a run log entry. If debug_prompts is on, also dump full prompts."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "call": call_type,
            "model": self._model,
            "system_chars": len(system),
            "user_chars": len(user),
        }
        if result:
            entry.update(result)

        log_file = piece.stage_dir() / "run-log.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("Run log entry: %s/%s (%s)", piece.id, stage, call_type)

        if self._debug:
            self._dump_prompt(piece, stage, call_type, system, user)

    @staticmethod
    def _dump_prompt(piece: "Piece", stage: str, call_type: str, system: str, user: str):
        """Write full prompt to a debug file."""
        from .piece import _stage_filename
        debug_file = piece.stage_dir() / _stage_filename(stage, f".{call_type}-prompt.md")
        content = (
            f"# Debug: {call_type} prompt for {stage}\n"
            f"# Piece: {piece.id}\n\n"
            f"## System\n{system}\n\n"
            f"## User\n{user}\n"
        )
        debug_file.write_text(content, encoding="utf-8")
        logger.info("Debug prompt dumped to %s", debug_file)
