# Ticket 75: Redis Pub/Sub for Dashboard Events

## Description
Replace thread-local SSE event queues with Redis Pub/Sub so that live execution events reach the dashboard regardless of which web worker process handles the SSE connection.

## Status
**Unstarted.** The current implementation uses an in-memory `queue.Queue` per run inside `RunManager`, streamed via SSE at `/api/pieces/<id>/runs/<run_id>/events`. This breaks in any multi-worker setup because the SSE client may hit a different process than the one holding the queue.

**Depends on Ticket 74** — the Celery task worker must be wired to the web layer first, since Celery workers run in separate processes and cannot use in-memory queues to communicate events back to the web tier.

## Tasks
- [ ] Modify `stage_runner.py`'s `_emit()` to publish event dicts to a Redis Pub/Sub channel keyed by `run_id` (e.g. `quill:events:<run_id>`).
- [ ] Update the SSE endpoint (`/api/pieces/<id>/runs/<run_id>/events`) to subscribe to the Redis channel and yield events from it.
- [ ] Update dashboard JS (`src/quill/static/`) to remain on `EventSource` (SSE is fine — no need for WebSockets unless push from server is required for other reasons).
- [ ] Ensure the Redis channel is cleaned up after the run completes (TTL or explicit unsubscribe).

## Success Criteria
- [ ] Live execution logs and progress badges update in real-time in the dashboard.
- [ ] Event delivery works correctly across multiple gunicorn/uvicorn worker processes.
- [ ] No stale Redis channels accumulate after runs complete.

## Priority
Medium — depends on Ticket 74

---
**Next Expected Ticket Number**: 76
