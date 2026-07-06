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
