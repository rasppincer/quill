# Ticket 74: Port RunManager to Celery Task Worker

## Description
Complete the switch from `RunManager` (ThreadPoolExecutor + in-memory SSE queues) to Celery task dispatch for background agent execution.

## Status
**Partially done.** The Celery infrastructure is in place:
- `src/quill/celery_app.py` defines `run_stage_task` (single stage) and handles `run_chain` internally.
- `celery_app.conf` is configured with Redis broker/backend, `task_acks_late`, `worker_prefetch_multiplier=1`, and `worker_concurrency` from env.
- Celery worker can be started with `celery -A quill.celery_app worker --loglevel=info`.

**What is NOT done:** the web layer (`src/quill/blueprints/runs.py`) still dispatches via `RunManager` (ThreadPoolExecutor + in-memory event queues). The hand-off from HTTP request → Celery task has not been wired.

## Remaining Tasks
- [ ] Update `blueprints/runs.py` POST `/runs` handler to call `run_stage_task.delay(piece_id, stage, agent_set, chain)` instead of `RunManager().start_run(...)`.
- [ ] Replace `RunManager().is_piece_running(piece_id)` check with a Celery task state lookup (query Redis backend by task ID).
- [ ] Persist the Celery `AsyncResult` task ID in the database (or Redis) so the events endpoint can subscribe to it.
- [ ] Update `RunManager.is_interrupted()` / `clear_interrupt()` to work with Celery task revocation (`celery_app.control.revoke(task_id, terminate=True)`).
- [ ] Remove or deprecate `RunManager._executor` (ThreadPoolExecutor) once Celery dispatch is confirmed working.

## Success Criteria
- [ ] Running stage/chain from the dashboard enqueues a Celery task (visible in Flower or Redis CLI).
- [ ] Celery worker executes `StageRunner` in a separate process.
- [ ] Interrupting a run (`POST /runs/<id>/interrupt`) terminates the Celery task cleanly.
- [ ] All existing run API tests pass.

## Priority
High — blocks Ticket 75 (Redis Pub/Sub events)

---
**Next Expected Ticket Number**: 75
