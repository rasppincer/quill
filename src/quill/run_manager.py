"""Async run management — thread pool, event queues, SSE streaming."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class RunManager:
    """Singleton manager for async agent runs with SSE event streaming.

    Uses a ThreadPoolExecutor(max_workers=2) to run StageRunner in background
    threads. Each run gets an in-memory event queue that SSE endpoints can
    subscribe to.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._executor = ThreadPoolExecutor(
                        max_workers=int(os.environ.get("QUILL_MAX_WORKERS", "2"))
                    )
                    inst._runs = {}  # run_id -> run info dict
                    inst._run_lock = threading.Lock()
                    inst._piece_locks = {}  # piece_id -> threading.Lock
                    inst._piece_locks_lock = threading.Lock()
                    inst._interrupted = set()  # piece_ids to interrupt after current stage
                    cls._instance = inst
        return cls._instance

    def _get_piece_lock(self, piece_id: str) -> threading.Lock:
        """Get or create a lock for a specific piece."""
        with self._piece_locks_lock:
            if piece_id not in self._piece_locks:
                self._piece_locks[piece_id] = threading.Lock()
            return self._piece_locks[piece_id]

    def is_piece_running(self, piece_id: str) -> bool:
        """Check if a piece has a running async job."""
        with self._run_lock:
            for info in self._runs.values():
                if info["piece_id"] == piece_id and info["status"] == "running":
                    return True
        return False

    def interrupt(self, piece_id: str):
        """Mark a piece for interruption after the current stage completes."""
        self._interrupted.add(piece_id)
        logger.info("Interrupt requested for piece '%s'", piece_id)

    def is_interrupted(self, piece_id: str) -> bool:
        """Check if a piece has been requested to interrupt."""
        return piece_id in self._interrupted

    def clear_interrupt(self, piece_id: str):
        """Clear the interrupt flag for a piece."""
        self._interrupted.discard(piece_id)

    def start_run(
        self,
        piece_id: str,
        stage: str,
        agent_set: str = "default",
        chain: bool = False,
    ) -> str | None:
        """Start a background run and return the run_id.

        Args:
            piece_id: The piece to run on.
            stage: Stage to run (default: piece's current stage).
            agent_set: Agent set to use.
            chain: If True, run all remaining stages.

        Returns:
            run_id string for SSE subscription.
        """
        self._cleanup_old_runs()

        if self.is_piece_running(piece_id):
            return None  # piece already has a running job

        run_id = uuid.uuid4().hex[:12]
        event_queue: queue.Queue = queue.Queue()

        with self._run_lock:
            self._runs[run_id] = {
                "queue": event_queue,
                "status": "running",
                "result": None,
                "piece_id": piece_id,
                "stage": stage,
                "agent_set": agent_set,
                "chain": chain,
                "started_at": time.time(),
            }

        self._executor.submit(
            self._execute_run, run_id, piece_id, stage, agent_set, chain, event_queue,
        )
        return run_id

    def get_run(self, run_id: str) -> dict | None:
        """Get run info by id."""
        with self._run_lock:
            return self._runs.get(run_id)

    def get_events(self, run_id: str):
        """Generator that yields SSE-formatted event strings.

        Blocks until the run completes (sentinel None in queue).
        Yields lines like:
            event: stage_start
            data: {"stage": "review", ...}

        Handles client disconnect by catching GeneratorExit.
        """
        with self._run_lock:
            run = self._runs.get(run_id)
        if not run:
            yield f"event: error\ndata: {__import__('json').dumps({'error': 'Run not found'})}\n\n"
            return

        q = run["queue"]
        try:
            while True:
                try:
                    event = q.get(timeout=300)  # 5 min timeout
                except queue.Empty:
                    # Heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
                    continue

                if event is None:
                    # Sentinel: run is complete
                    with self._run_lock:
                        run_info = self._runs.get(run_id, {})
                    yield f"event: run_complete\ndata: {__import__('json').dumps({'status': run_info.get('status', 'unknown'), 'result': run_info.get('result')})}\n\n"
                    return

                event_type = event.get("type", "message")
                data = event.get("data", {})
                yield f"event: {event_type}\ndata: {__import__('json').dumps(data)}\n\n"
        except GeneratorExit:
            # Client disconnected — stop consuming
            return

    def _execute_run(self, run_id, piece_id, stage, agent_set, chain, event_queue):
        """Background worker that runs StageRunner and emits events."""
        import json as _json

        try:
            from .runner import StageRunner
            runner = StageRunner(agent_set=agent_set)

            if chain:
                results = runner.run_chain(
                    piece_id, from_stage=stage, event_queue=event_queue,
                )
                result_data = {
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
                }
            else:
                trace_id = str(uuid.uuid4())
                result = runner.run_stage(
                    piece_id, stage or "", event_queue=event_queue, trace_id=trace_id,
                )
                result_data = {
                    "stage": result.stage,
                    "decision": result.decision,
                    "critique": result.critique,
                    "loop_count": result.loop_count,
                    "error": result.error,
                }

            with self._run_lock:
                if run_id in self._runs: self._runs[run_id]["status"] = "complete"
                if run_id in self._runs: self._runs[run_id]["result"] = result_data

        except Exception as exc:
            logger.exception("Run %s failed", run_id)
            with self._run_lock:
                if run_id in self._runs: self._runs[run_id]["status"] = "error"
                if run_id in self._runs: self._runs[run_id]["result"] = {"error": str(exc)}
            event_queue.put({"type": "error", "data": {"error": str(exc)}})

        finally:
            # Don't set status to "complete" here — let it stay "running" until
            # the SSE sentinel (None) is consumed by the client. This prevents
            # race conditions where the piece is still being processed by the
            # frontend but the run is marked complete.
            event_queue.put(None)

    def _cleanup_old_runs(self):
        """Remove runs older than 5 minutes (thread-safe)."""
        cutoff = time.time() - 300
        with self._run_lock:
            expired = [
                rid for rid, info in self._runs.items()
                if info["started_at"] < cutoff
            ]
            for rid in expired:
                del self._runs[rid]
