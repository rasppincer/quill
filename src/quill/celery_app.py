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
import logging
from celery import Celery

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
) -> dict:
    """Execute a Quill stage (or full chain) in a worker process.

    Args:
        piece_id: Identifier of the piece to process.
        stage: Stage name to start from.
        agent_set: Agent configuration set to use.
        chain: If True, run all remaining stages after ``stage``.

    Returns:
        A dict with keys ``stage``, ``decision``, ``critique``,
        ``loop_count``, and ``error``.
    """
    import uuid
    from .runner import StageRunner
    from .db import db_session

    logger.info(
        "Worker: starting run piece=%s stage=%s agent_set=%s chain=%s",
        piece_id, stage, agent_set, chain,
    )

    try:
        runner = StageRunner(agent_set=agent_set)

        if chain:
            results = runner.run_chain(piece_id, from_stage=stage)
            return {
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
            result = runner.run_stage(piece_id, stage, trace_id=trace_id)
            return {
                "stage": result.stage,
                "decision": result.decision,
                "critique": result.critique,
                "loop_count": result.loop_count,
                "error": result.error,
            }

    except Exception as exc:
        logger.exception("Worker: run failed piece=%s stage=%s", piece_id, stage)
        return {
            "stage": stage,
            "decision": None,
            "critique": None,
            "loop_count": 0,
            "error": str(exc),
        }

    finally:
        # Release the scoped DB session used inside StageRunner
        db_session.remove()
