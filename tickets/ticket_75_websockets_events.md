# Ticket 75: Implement Redis Pub/Sub & WebSockets for Dashboard Events

## Description
Replace the SSE `/api/pieces/<id>/runs/<run_id>/events` stream with a WebSocket or Redis Pub/Sub event bridge to feed the dashboard in real-time.

## Background
Currently, events are put into thread-local queues and served via SSE. In a multi-worker setup, SSE clients might hit a web server that doesn't hold the local thread queue. Redis Pub/Sub solves this by broadcasting events globally.

## Tasks
- [ ] Modify `stage_runner.py`'s `_emit()` to publish event messages to a Redis pub/sub channel scoped by `run_id` or `piece_id`.
- [ ] Set up a WebSocket endpoint (using Flask-SocketIO or FastAPI WebSockets) to subscribe to the Redis pub/sub channel.
- [ ] Update dashboard JS in `src/quill/static/` to connect via WebSockets instead of EventSource SSE.

## Success Criteria
- [ ] Live execution logs, tokens, and progress badges update in real-time on the UI.
- [ ] Event delivery works seamlessly across multiple web server worker processes.

## Priority
Medium

---
**Next Expected Ticket Number**: 76
