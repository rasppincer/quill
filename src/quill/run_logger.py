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
        self._model = load_model_config().get("model", "")

    def log(
        self,
        piece: "Piece",
        stage: str,
        call_type: str,
        system: str,
        user: str,
        result: dict | None = None,
    ):
        """Append a run log entry.

        Args:
            piece: The piece being processed.
            stage: Current stage name.
            call_type: "generate", "evaluate", or "agent".
            system: System prompt sent to LLM.
            user: User prompt sent to LLM.
            result: Optional dict with decision, critique, elapsed, etc.
        """
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
