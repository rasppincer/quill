"""Timing instrumentation for performance analysis."""

from __future__ import annotations

import functools
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Global list — flushed to disk at end of run
_timing_entries: list[dict] = []


def timeit(label: str | None = None):
    """Decorator that logs execution time of a function.

    If label is None, uses the function's qualified name.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.monotonic()
            result = fn(*args, **kwargs)
            elapsed = time.monotonic() - t0
            name = label or fn.__qualname__
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "label": name,
                "elapsed_s": round(elapsed, 3),
            }
            _timing_entries.append(entry)
            logger.info("[timeit] %s: %.3fs", name, elapsed)
            return result
        return wrapper
    return decorator


def log_timing(label: str, elapsed_s: float):
    """Manually log a timing entry (for LLM calls, etc.)."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "elapsed_s": round(elapsed_s, 3),
    }
    _timing_entries.append(entry)
    logger.info("[timeit] %s: %.3fs", label, elapsed_s)


def flush_timings(path: Path | str):
    """Write all timing entries to a JSONL file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for entry in _timing_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info("[timeit] Flushed %d entries to %s", len(_timing_entries), path)


def clear_timings():
    """Clear the in-memory timing list."""
    _timing_entries.clear()


def get_timings() -> list[dict]:
    """Return current timing entries."""
    return list(_timing_entries)
