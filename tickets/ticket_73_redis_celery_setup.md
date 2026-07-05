# Ticket 73: Setup Redis & Celery/Dramatiq Infrastructure

## Description
Set up Redis and a Celery worker framework to support distributed task execution.

## Background
Currently, async operations run in Python threads inside the web server process. If the server is restarted, tasks disappear. Moving to Celery with Redis broker provides crash resilience and horizontal scaling.

## Tasks
- [ ] Add `celery` and `redis` dependencies to `pyproject.toml`.
- [ ] Create `src/quill/celery_app.py` to initialize Celery with Redis broker and backend.
- [ ] Add Docker Compose file or instructions to start Redis and Celery worker service.

## Success Criteria
- [ ] Celery workers can be started and successfully connect to the Redis broker.
- [ ] Basic task enqueueing and execution work in worker processes.

## Priority
High

---
**Next Expected Ticket Number**: 74
