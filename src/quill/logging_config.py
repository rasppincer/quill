"""Logging configuration for Quill.

Two-tier logging:
- Common log (logs/quill.log): startup, config, errors, non-piece events
- Per-piece logs (logs/pieces/<piece_id>_<YYYYMMDD>.log): stage transitions,
  LLM calls, state changes, timing

Routing: PieceLogHandler checks record.piece_id — if present, routes to
per-piece file. Otherwise falls through to common log.

Rotation: TimedRotatingFileHandler at midnight, 3 days retention.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, date
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"
PIECES_DIR = LOGS_DIR / "pieces"

# Configurable via env
LOG_LEVEL = os.environ.get("QUILL_LOG_LEVEL", "INFO").upper()
LOG_DAYS = int(os.environ.get("QUILL_LOG_DAYS", "3"))

_initialized = False


class PieceLogHandler(logging.Handler):
    """Routes log records with piece_id to per-piece log files.

    Piece logs are named <piece_id>_<YYYYMMDD>.log — one file per day
    per piece. Old files are cleaned up on rotation.
    """

    def __init__(self):
        super().__init__()
        self._handlers: dict[str, logging.FileHandler] = {}
        PIECES_DIR.mkdir(parents=True, exist_ok=True)

    def emit(self, record):
        piece_id = getattr(record, "piece_id", None)
        if not piece_id:
            return

        # Sanitize piece_id for filename
        safe_id = piece_id.replace("/", "_").replace("\\", "_")
        today = date.today().strftime("%Y%m%d")
        filename = f"{safe_id}_{today}.log"
        filepath = PIECES_DIR / filename

        # Cache handler per filename (changes daily)
        if filename not in self._handlers:
            handler = logging.FileHandler(str(filepath), encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            self._handlers[filename] = handler

        self._handlers[filename].emit(record)

        # Periodic cleanup of old piece logs
        self._cleanup_old_logs()

    def _cleanup_old_logs(self):
        """Remove piece logs older than LOG_DAYS."""
        cutoff = date.today()
        for f in PIECES_DIR.glob("*.log"):
            try:
                # Parse date from filename: <piece_id>_YYYYMMDD.log
                parts = f.stem.rsplit("_", 1)
                if len(parts) == 2:
                    file_date = date.fromisoformat(parts[1][:4] + "-" + parts[1][4:6] + "-" + parts[1][6:8])
                    age = (cutoff - file_date).days
                    if age > LOG_DAYS:
                        f.unlink()
            except (ValueError, IndexError):
                pass


def setup_logging(logs_dir: Path | None = None):
    """Initialize the Quill logging system.

    Call once at app startup. Idempotent.
    """
    global _initialized, LOGS_DIR, PIECES_DIR
    if _initialized:
        return

    if logs_dir:
        LOGS_DIR = logs_dir
        PIECES_DIR = logs_dir / "pieces"

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    PIECES_DIR.mkdir(parents=True, exist_ok=True)

    # Root logger — captures everything
    root = logging.getLogger("quill")
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Remove any existing handlers (including default StreamHandler)
    root.handlers.clear()

    # 1. Common log — quill.log with daily rotation, 3 days
    common_handler = TimedRotatingFileHandler(
        str(LOGS_DIR / "quill.log"),
        when="midnight",
        interval=1,
        backupCount=LOG_DAYS,
        encoding="utf-8",
    )
    common_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    common_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    root.addHandler(common_handler)

    # 2. Per-piece log handler
    piece_handler = PieceLogHandler()
    piece_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    root.addHandler(piece_handler)

    _initialized = True
    root.info("Logging initialized — level=%s, logs_dir=%s, retention=%d days",
              LOG_LEVEL, LOGS_DIR, LOG_DAYS)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a module (non-piece context)."""
    return logging.getLogger(f"quill.{name}")


def get_piece_logger(name: str, piece_id: str) -> logging.LoggerAdapter:
    """Get a logger that automatically tags records with piece_id.

    Usage:
        log = get_piece_logger("runner", "my-story")
        log.info("Starting stage review")  # → goes to pieces/my-story_20260625.log
    """
    logger = logging.getLogger(f"quill.{name}")
    return logging.LoggerAdapter(logger, {"piece_id": piece_id})
