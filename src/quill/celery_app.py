"""Celery application — task broker and worker entry point.

Initialises Celery with Redis as both broker and result backend.
The broker URL is read from the REDIS_URL environment variable
(default: redis://localhost:6379/0).

Usage
-----
Start a worker from the repo root::

    celery -A quill.celery_app worker --loglevel=info

Enqueue a task from Python (or Flask)::

    from quill.celery_app import run_stage_task
    async_result = run_stage_task.delay(piece_id, stage, agent_set, chain)
"""

from __future__ import annotations

import os
from pathlib import Path
import logging
from celery import Celery

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ── configuration ──────────────────────────────────────────────────────────────

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "quill",
    broker=_REDIS_URL,
    backend=_REDIS_URL,
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Reliability
    task_acks_late=True,           # ack after task completes, not before
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # one task at a time per worker thread
    # Concurrency — match existing RunManager default
    worker_concurrency=int(os.environ.get("QUILL_MAX_WORKERS", "2")),
    # Result expiry
    result_expires=3600,           # keep results for 1 hour
)


# ── tasks ──────────────────────────────────────────────────────────────────────

@celery_app.task(name="quill.celery_app.run_stage_task", bind=True, max_retries=0)
def run_stage_task(
    self,
    piece_id: str,
    stage: str,
    agent_set: str = "default",
    chain: bool = False,
    callback_url: str | None = None,
    extra_context: dict | None = None,
) -> dict:
    """Execute a Quill stage (or full chain) in a worker process.

    Args:
        piece_id: Identifier of the piece to process.
        stage: Stage name to start from.
        callback_url: Optional URL to send completion callback POST request.
        extra_context: Optional additional template context variables.
        agent_set: Agent configuration set to use.
        chain: If True, run all remaining stages after ``stage``.

    Returns:
        A dict with keys ``stage``, ``decision``, ``critique``,
        ``loop_count``, and ``error``.
    """
    import uuid
    import requests
    from .runner import StageRunner
    from .db import db_session

    logger.info(
        "Worker: starting run piece=%s stage=%s agent_set=%s chain=%s callback=%s",
        piece_id, stage, agent_set, chain, callback_url,
    )

    result_dict = {}
    try:
        runner = StageRunner(agent_set=agent_set)

        if chain:
            results = runner.run_chain(piece_id, from_stage=stage)
            result_dict = {
                "chain": True,
                "results": [
                    {
                        "stage": r.stage,
                        "decision": r.decision,
                        "critique": (r.critique or "")[:500],
                        "loop_count": r.loop_count,
                        "error": r.error,
                    }
                    for r in results
                ],
            }
        else:
            trace_id = str(uuid.uuid4())
            result = runner.run_stage(piece_id, stage, trace_id=trace_id, extra_context=extra_context)
            result_dict = {
                "stage": result.stage,
                "decision": result.decision,
                "critique": result.critique,
                "loop_count": result.loop_count,
                "error": result.error,
            }

        # Send successful callback
        if callback_url:
            payload = {
                "node_id": piece_id,
                "stage": stage,
                "status": "completed" if not result_dict.get("error") else "failed",
                "error": result_dict.get("error"),
            }
            try:
                requests.post(callback_url, json=payload, timeout=10)
            except Exception as cb_err:
                logger.error("Worker: failed to send completed callback to %s: %s", callback_url, cb_err)

        return result_dict

    except Exception as exc:
        logger.exception("Worker: run failed piece=%s stage=%s", piece_id, stage)
        err_dict = {
            "stage": stage,
            "decision": None,
            "critique": None,
            "loop_count": 0,
            "error": str(exc),
        }

        # Send failed callback
        if callback_url:
            payload = {
                "node_id": piece_id,
                "stage": stage,
                "status": "failed",
                "error": str(exc),
            }
            try:
                requests.post(callback_url, json=payload, timeout=10)
            except Exception as cb_err:
                logger.error("Worker: failed to send failed callback to %s: %s", callback_url, cb_err)

        return err_dict

    finally:
        # Release the scoped DB session used inside StageRunner
        db_session.remove()

