# Redis & Celery Infrastructure Setup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Celery + Redis as a crash-resilient, horizontally-scalable task broker to replace in-process `ThreadPoolExecutor` runs.

**Architecture:** A dedicated `celery_app.py` module initialises Celery with `redis://` as both the broker and result backend. A single `run_stage` Celery task wraps the existing `StageRunner` so worker processes can execute stages independently of the Flask web server. Docker Compose provides Redis and a worker service for local development.

**Tech Stack:** Python >= 3.10, Celery >= 5.3, redis-py >= 5.0, Redis 7 (Docker), Flask-SQLAlchemy for DB sessions in worker context.

## Global Constraints

- Python `>=3.10` — no walrus operator before that boundary
- All new dependencies added to `pyproject.toml` `[project]` `dependencies` list (not `dev` extras)
- Redis URL configurable via `REDIS_URL` env var; default `redis://localhost:6379/0`
- Celery app name must be `"quill"`
- Worker concurrency defaults to `QUILL_MAX_WORKERS` env var (same as existing `RunManager`)
- Do **not** wire Celery into `RunManager` yet — this ticket is infrastructure only; wiring is a separate ticket

---

## Task 1: Add Dependencies to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `celery` and `redis` importable in the installed package

- [ ] **Step 1: Write the failing import test**

```python
# tests/test_celery_deps.py
def test_celery_importable():
    import celery
    assert celery.__version__

def test_redis_importable():
    import redis
    assert redis.__version__
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/bob/projects/quill
.venv/bin/pytest tests/test_celery_deps.py -v
```

Expected: `ModuleNotFoundError: No module named 'celery'` (or similar)

- [ ] **Step 3: Add dependencies**

Edit `pyproject.toml` — add two lines to the `dependencies` list:

```toml
[project]
name = "quill"
version = "0.1.0"
description = "Writing workflow engine — multi-stage pipeline for long-form content"
requires-python = ">=3.10"
dependencies = [
    "flask>=3.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "SQLAlchemy>=2.0",
    "flask-sqlalchemy>=3.0",
    "flask-migrate>=4.0",
    "litellm>=1.0.0",
    "tenacity",
    "celery>=5.3",
    "redis>=5.0",
]
```

- [ ] **Step 4: Install into the venv**

```bash
cd /home/bob/projects/quill
.venv/bin/pip install -e ".[dev]"
```

Expected: `Successfully installed celery-... redis-...`

- [ ] **Step 5: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_celery_deps.py -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/test_celery_deps.py
git commit -m "feat(deps): add celery>=5.3 and redis>=5.0 dependencies"
```

---

## Task 2: Create `celery_app.py`

**Files:**
- Create: `src/quill/celery_app.py`
- Test: `tests/test_celery_app.py`

**Interfaces:**
- Produces:
  - `celery_app: Celery` — importable Celery application instance
  - `run_stage_task(piece_id: str, stage: str, agent_set: str, chain: bool) -> dict` — registered Celery task

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_celery_app.py
"""Tests for Celery app initialisation."""
import os
import pytest


def test_celery_app_name():
    """The Celery app must be named 'quill'."""
    from quill.celery_app import celery_app
    assert celery_app.main == "quill"


def test_celery_broker_from_env(monkeypatch):
    """REDIS_URL env var must be picked up as broker and backend."""
    monkeypatch.setenv("REDIS_URL", "redis://testhost:6379/1")
    import importlib
    import quill.celery_app as mod
    importlib.reload(mod)
    assert "testhost" in mod.celery_app.conf.broker_url
    assert "testhost" in mod.celery_app.conf.result_backend


def test_run_stage_task_registered():
    """run_stage_task must be registered in the Celery app."""
    from quill.celery_app import celery_app
    assert "quill.celery_app.run_stage_task" in celery_app.tasks


def test_run_stage_task_eager(monkeypatch):
    """run_stage_task executes eagerly and returns a dict."""
    import importlib
    import quill.celery_app as mod
    importlib.reload(mod)
    mod.celery_app.conf.task_always_eager = True

    # Stub out StageRunner so we don't hit the LLM
    import quill.runner as runner_mod
    from collections import namedtuple
    FakeResult = namedtuple("FakeResult", ["stage", "decision", "critique", "loop_count", "error"])

    class FakeStageRunner:
        def __init__(self, agent_set="default"):
            pass
        def run_stage(self, piece_id, stage, event_queue=None, trace_id=None):
            return FakeResult(stage=stage, decision="advance", critique="ok", loop_count=1, error=None)

    monkeypatch.setattr(runner_mod, "StageRunner", FakeStageRunner)

    result = mod.run_stage_task.apply(
        args=["some-piece", "draft", "default", False]
    ).get()

    assert result["stage"] == "draft"
    assert result["decision"] == "advance"
    assert result["error"] is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_celery_app.py -v
```

Expected: `ModuleNotFoundError: No module named 'quill.celery_app'`

- [ ] **Step 3: Create `src/quill/celery_app.py`**

```python
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
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Concurrency — match existing RunManager default
    worker_concurrency=int(os.environ.get("QUILL_MAX_WORKERS", "2")),
    # Result expiry
    result_expires=3600,
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
        chain: If True, run all remaining stages after stage.

    Returns:
        A dict with keys stage, decision, critique, loop_count, and error.
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
        db_session.remove()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_celery_app.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/quill/celery_app.py tests/test_celery_app.py
git commit -m "feat: add celery_app.py with run_stage_task"
```

---

## Task 3: Configure External Redis & Document Worker Startup

No Docker required — point `REDIS_URL` at the Redis instance already on your LAN.

**Files:**
- Modify: `.env.example` — add `REDIS_URL`
- Create: `tests/test_redis_connectivity.py` — pytest connectivity check (skipped if Redis unreachable)

**Interfaces:**
- Produces: Running `REDIS_URL=redis://<host>:6379/0 celery -A quill.celery_app worker` connects successfully

- [ ] **Step 1: Find your LAN Redis address**

```bash
# If you know the host already, skip this. Otherwise:
ping -c1 <your-redis-hostname-or-ip>
redis-cli -h <your-redis-hostname-or-ip> ping
# Expected: PONG
```

- [ ] **Step 2: Update `.env.example`**

Append these lines to `.env.example`:

```dotenv
# Redis broker URL for Celery workers.
# Point this at any reachable Redis instance — local or LAN.
# Examples:
#   redis://localhost:6379/0          (local Redis)
#   redis://192.168.1.50:6379/0       (LAN Redis by IP)
#   redis://redis.home.arpa:6379/0    (LAN Redis by hostname)
REDIS_URL=redis://localhost:6379/0
```

- [ ] **Step 3: Set `REDIS_URL` in your local `.env`**

```bash
echo 'REDIS_URL=redis://<your-redis-host>:6379/0' >> /home/bob/projects/quill/.env
```

Replace `<your-redis-host>` with the actual IP or hostname.

- [ ] **Step 4: Write the connectivity test**

```python
# tests/test_redis_connectivity.py
"""Connectivity smoke-test for the Redis broker.

Skipped automatically when REDIS_URL is not set in the environment,
so the test suite stays green without a live Redis.
Run manually against your LAN Redis:

    REDIS_URL=redis://192.168.1.50:6379/0 pytest tests/test_redis_connectivity.py -v
"""
import os
import pytest

REDIS_URL = os.environ.get("REDIS_URL", "")


@pytest.mark.skipif(
    not REDIS_URL,
    reason="REDIS_URL not set — skipping live connectivity test",
)
def test_redis_ping():
    """redis-py can connect and PING the configured Redis server."""
    import redis
    client = redis.from_url(REDIS_URL, socket_connect_timeout=3)
    assert client.ping(), "Redis did not respond to PING"


@pytest.mark.skipif(
    not REDIS_URL,
    reason="REDIS_URL not set — skipping live connectivity test",
)
def test_celery_broker_reachable():
    """Celery can inspect the broker without raising a connection error."""
    from quill.celery_app import celery_app
    # inspect().ping() returns {} if no workers are up — that's fine.
    # ConnectionError / OperationalError would mean the broker is unreachable.
    try:
        celery_app.control.inspect(timeout=3).ping()
    except Exception as exc:
        pytest.fail(f"Celery broker unreachable: {exc}")
```

- [ ] **Step 5: Run the connectivity tests against your LAN Redis**

```bash
cd /home/bob/projects/quill
REDIS_URL=redis://<your-redis-host>:6379/0 .venv/bin/pytest tests/test_redis_connectivity.py -v
```

Expected:
```
test_redis_ping                PASSED
test_celery_broker_reachable   PASSED
```

- [ ] **Step 6: Verify the Celery worker connects**

In a terminal:
```bash
cd /home/bob/projects/quill
REDIS_URL=redis://<your-redis-host>:6379/0 \
  .venv/bin/celery -A quill.celery_app worker --loglevel=info
```

Expected output (within a few seconds):
```
[tasks]
  . quill.celery_app.run_stage_task

[2026-...] Connected to redis://<your-redis-host>:6379/0
[2026-...] mingle: all alone
celery@hostname ready.
```

- [ ] **Step 7: Commit**

```bash
git add .env.example tests/test_redis_connectivity.py
git commit -m "feat: configure REDIS_URL for LAN Redis and add connectivity tests"
```

---

## Verification Plan

### Automated Tests (no live Redis needed)

```bash
.venv/bin/pytest tests/test_celery_deps.py tests/test_celery_app.py -v
```

Expected: `6 passed`

The connectivity tests in `test_redis_connectivity.py` skip automatically without a live Redis:

```bash
.venv/bin/pytest tests/test_redis_connectivity.py -v
# 2 skipped (REDIS_URL not set)
```

### Live Smoke Test (with your LAN Redis)

```bash
# Terminal 1 — start the worker
cd /home/bob/projects/quill
REDIS_URL=redis://<your-redis-host>:6379/0 \
  .venv/bin/celery -A quill.celery_app worker --loglevel=info

# Terminal 2 — enqueue a task
cd /home/bob/projects/quill
REDIS_URL=redis://<your-redis-host>:6379/0 \
  .venv/bin/python - <<'EOF'
from quill.celery_app import run_stage_task
r = run_stage_task.delay("nonexistent-piece", "draft", "default", False)
print("Task ID:", r.id)
print("Result:", r.get(timeout=10))
EOF
# Expected: Worker log shows task received; result dict returned
# (error key will be set for nonexistent piece — that is fine)
```

### Success Criteria (from ticket)

- [ ] Celery worker starts and connects to the Redis broker without errors
- [ ] Basic task enqueueing (`run_stage_task.delay(...)`) works and returns a result dict
