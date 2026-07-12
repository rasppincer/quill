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
        def run_stage(self, piece_id, stage, event_queue=None, trace_id=None, **kwargs):
            return FakeResult(stage=stage, decision="advance", critique="ok", loop_count=1, error=None)

    monkeypatch.setattr(runner_mod, "StageRunner", FakeStageRunner)

    result = mod.run_stage_task.apply(
        args=["some-piece", "draft", "default", False]
    ).get()

    assert result["stage"] == "draft"
    assert result["decision"] == "advance"
    assert result["error"] is None


def test_celery_task_sends_callback(monkeypatch):
    """run_stage_task must send a POST request to callback_url with execution status."""
    import importlib
    import quill.celery_app as mod
    importlib.reload(mod)
    mod.celery_app.conf.task_always_eager = True

    # Stub StageRunner
    import quill.runner as runner_mod
    from collections import namedtuple
    FakeResult = namedtuple("FakeResult", ["stage", "decision", "critique", "loop_count", "error"])

    class FakeStageRunner:
        def __init__(self, agent_set="default"):
            pass
        def run_stage(self, piece_id, stage, event_queue=None, trace_id=None, extra_context=None):
            return FakeResult(stage=stage, decision="advance", critique="ok", loop_count=1, error=None)

    monkeypatch.setattr(runner_mod, "StageRunner", FakeStageRunner)

    # Spy requests.post
    import requests
    posted_urls = []
    posted_payloads = []

    def fake_post(url, json=None, timeout=None):
        posted_urls.append(url)
        posted_payloads.append(json)
        class FakeResponse:
            status_code = 200
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    result = mod.run_stage_task.apply(
        args=["some-piece", "draft"],
        kwargs={
            "callback_url": "http://callback-url.com/callback",
            "extra_context": {"some": "ctx"}
        }
    ).get()

    assert result["stage"] == "draft"
    assert "http://callback-url.com/callback" in posted_urls
    assert posted_payloads[0]["node_id"] == "some-piece"
    assert posted_payloads[0]["stage"] == "draft"
    assert posted_payloads[0]["status"] == "completed"

