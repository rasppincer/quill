# Ticket 74: Port RunManager to Distributed Task Worker

## Description
Rewrite `src/quill/run_manager.py` to submit agent runs as Celery tasks instead of thread pool submissions.

## Background
The ThreadPoolExecutor needs to be deprecated in favor of Celery task delays. The background agent execution must be managed as a task state in the database/Redis backend.

## Tasks
- [ ] Refactor `RunManager.start_run()` to enqueue a Celery task `run_stage_task` or `run_chain_task`.
- [ ] Define Celery task definitions in `src/quill/tasks.py` that call `StageRunner`.
- [ ] Handle task state tracking (pending, running, success, failure) in the database.

## Success Criteria
- [ ] Running stage/chain triggers enqueues a Celery task.
- [ ] Celery worker executes the stage runner code in a separate process.
- [ ] Re-running or interrupting tasks is handled safely via task IDs.

## Priority
High

---
**Next Expected Ticket Number**: 75
