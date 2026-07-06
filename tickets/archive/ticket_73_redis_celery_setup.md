# Ticket 73: Setup Redis & Celery/Dramatiq Infrastructure

## Status: DONE ✅
Completed: 2026-07-06
Branch: `feat/ticket-73-celery`
Commits: `9d18b82`, `28c5dbc`, `fa6eba3`

## Description
Set up Redis and a Celery worker framework to support distributed task execution.

## Background
Currently, async operations run in Python threads inside the web server process. If the server is restarted, tasks disappear. Moving to Celery with Redis broker provides crash resilience and horizontal scaling.

## Tasks
- [x] Add `celery` and `redis` dependencies to `pyproject.toml`.
- [x] Create `src/quill/celery_app.py` to initialize Celery with Redis broker and backend.
- [x] Add instructions to start Redis and Celery worker service (LAN Redis at 192.168.0.4).

## Success Criteria
- [x] Celery workers can be started and successfully connect to the Redis broker.
- [x] Basic task enqueueing and execution work in worker processes.

## Implementation Notes
- Redis on LAN at `192.168.0.4:6379`, password-auth (`redis://:klan_nedoklan@192.168.0.4:6379/0`)
- `REDIS_URL` env var configures broker + backend (set in `.env`, documented in `.env.example`)
- Live connectivity tests in `tests/test_redis_connectivity.py` — opt-in via `QUILL_TEST_REDIS_LIVE=1`
- Worker concurrency controlled by existing `QUILL_MAX_WORKERS` env var
- `RunManager` threading NOT replaced — wiring Celery into the API is ticket 74

## Priority
High

---
**Next Expected Ticket Number**: 74
