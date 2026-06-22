"""Tests for async execution — RunManager, event emission, SSE endpoints."""

import json
import queue
import pytest
import time
from unittest.mock import patch, MagicMock

import yaml

from quill.runner import RunManager, StageRunner
from quill.piece import _stage_filename
from quill.agent import AgentDecision


@pytest.fixture
def runner(tmp_agents, monkeypatch):
    """StageRunner with mocked agent dir."""
    monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
    monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")
    return StageRunner(agent_set="default")


# ---------------------------------------------------------------------------
# RunManager singleton
# ---------------------------------------------------------------------------


class TestRunManagerSingleton:
    """Test RunManager singleton behavior."""

    def test_singleton_identity(self):
        """RunManager() always returns the same instance."""
        a = RunManager()
        b = RunManager()
        assert a is b

    def test_has_executor(self):
        """RunManager has a ThreadPoolExecutor."""
        mgr = RunManager()
        assert hasattr(mgr, "_executor")
        assert mgr._executor._max_workers == 2

    def test_has_runs_dict(self):
        """RunManager has an in-memory runs dict."""
        mgr = RunManager()
        assert hasattr(mgr, "_runs")
        assert isinstance(mgr._runs, dict)


# ---------------------------------------------------------------------------
# RunManager.start_run / get_run
# ---------------------------------------------------------------------------


class TestRunManagerStartRun:
    """Test starting async runs."""

    @patch("quill.runner.StageRunner")
    def test_start_run_returns_run_id(self, mock_runner_cls, tmp_output, tmp_agents, monkeypatch):
        """start_run() returns a 12-char hex run_id."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

        # Create a piece
        from quill.piece import Piece
        piece = Piece(
            id="async-piece", title="Async Test", genre="fiction",
            type="story", audience="general", tone="casual",
            language="en", target_length="1000 words", constraints=[],
            current_stage="review", created="2026-01-01", updated="2026-01-01",
            body="Test content.", agent_set="default",
        )
        piece.save()

        # Mock runner
        mock_runner = MagicMock()
        mock_runner.run_stage.return_value = AgentDecision(
            decision="advance", critique="Good.", output="", stage="review",
        )
        mock_runner_cls.return_value = mock_runner

        mgr = RunManager()
        run_id = mgr.start_run("async-piece", stage="review", agent_set="default")

        assert isinstance(run_id, str)
        assert len(run_id) == 12

        # Wait for background thread to complete
        time.sleep(0.5)

        run_info = mgr.get_run(run_id)
        assert run_info is not None
        assert run_info["piece_id"] == "async-piece"
        assert run_info["status"] == "complete"

    def test_get_run_nonexistent(self):
        """get_run() returns None for unknown run_id."""
        mgr = RunManager()
        assert mgr.get_run("nonexistent") is None


# ---------------------------------------------------------------------------
# RunManager.get_events (SSE stream)
# ---------------------------------------------------------------------------


class TestRunManagerGetEvents:
    """Test SSE event streaming."""

    def test_get_events_run_not_found(self):
        """get_events yields error event for unknown run_id."""
        mgr = RunManager()
        events = list(mgr.get_events("no-such-run"))
        assert len(events) == 1
        assert "error" in events[0]
        assert "Run not found" in events[0]

    @patch("quill.runner.StageRunner")
    def test_get_events_yields_run_complete(self, mock_runner_cls, tmp_output, tmp_agents, monkeypatch):
        """get_events yields run_complete event at the end."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

        from quill.piece import Piece
        piece = Piece(
            id="sse-piece", title="SSE Test", genre="fiction",
            type="story", audience="general", tone="casual",
            language="en", target_length="1000 words", constraints=[],
            current_stage="review", created="2026-01-01", updated="2026-01-01",
            body="Test content.", agent_set="default",
        )
        piece.save()

        mock_runner = MagicMock()
        mock_runner.run_stage.return_value = AgentDecision(
            decision="advance", critique="Good.", output="", stage="review",
        )
        mock_runner_cls.return_value = mock_runner

        mgr = RunManager()
        run_id = mgr.start_run("sse-piece", stage="review")

        # Collect events with timeout
        events = []
        for event_str in mgr.get_events(run_id):
            events.append(event_str)
            if "run_complete" in event_str:
                break

        assert any("run_complete" in e for e in events)


# ---------------------------------------------------------------------------
# Event emission in run_stage
# ---------------------------------------------------------------------------


class TestRunStageEventEmission:
    """Test that run_stage emits events to the queue."""

    @patch("quill.runner.LLMClient")
    def test_review_emits_stage_start_and_complete(self, mock_llm_cls, runner, sample_piece, tmp_output, monkeypatch):
        """Review stage emits stage_start and stage_complete events."""
        from quill.piece import load_piece

        mock_client = MagicMock()
        mock_client.chat.return_value = '```json\n{"decision": "advance", "critique": "Good."}\n```'
        mock_llm_cls.return_value = mock_client
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        q = queue.Queue()
        result = runner.run_stage("test-piece", "review", output_dir=tmp_output, event_queue=q)

        assert result.decision == "advance"

        # Drain queue
        events = []
        while not q.empty():
            events.append(q.get())

        event_types = [e["type"] for e in events]
        assert "stage_start" in event_types
        assert "stage_llm_call" in event_types
        assert "stage_complete" in event_types

        # Check stage_start data
        start_event = next(e for e in events if e["type"] == "stage_start")
        assert start_event["data"]["stage"] == "review"
        assert start_event["data"]["is_content_stage"] is False

    @patch("quill.runner.LLMClient")
    def test_content_stage_emits_generate_and_evaluate(self, mock_llm_cls, runner, sample_piece_with_review, tmp_output, monkeypatch):
        """Content stages emit generate and evaluate LLM call events."""
        from quill.piece import load_piece

        mock_client = MagicMock()
        mock_client.chat.side_effect = [
            "The revised draft.",  # generate
            '```json\n{"decision": "advance", "critique": "Good."}\n```',  # evaluate
        ]
        mock_llm_cls.return_value = mock_client
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        piece = load_piece(sample_piece_with_review)
        piece.current_stage = "revise"
        piece.save()

        q = queue.Queue()
        result = runner.run_stage("test-piece", "revise", output_dir=tmp_output, event_queue=q)

        events = []
        while not q.empty():
            events.append(q.get())

        llm_events = [e for e in events if e["type"] == "stage_llm_call"]
        calls = [e["data"]["call"] for e in llm_events]
        assert "generate" in calls
        assert "evaluate" in calls

    @patch("quill.runner.LLMClient")
    def test_no_events_when_queue_is_none(self, mock_llm_cls, runner, sample_piece, tmp_output, monkeypatch):
        """When event_queue is None, no events are emitted (backward compatible)."""
        mock_client = MagicMock()
        mock_client.chat.return_value = '```json\n{"decision": "advance", "critique": "Good."}\n```'
        mock_llm_cls.return_value = mock_client
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        # No event_queue passed — should work fine
        result = runner.run_stage("test-piece", "review", output_dir=tmp_output)
        assert result.decision == "advance"


# ---------------------------------------------------------------------------
# Event emission in run_chain
# ---------------------------------------------------------------------------


class TestRunChainEventEmission:
    """Test that run_chain emits chain-level events."""

    @patch("quill.runner.LLMClient")
    def test_chain_emits_chain_start_and_complete(self, mock_llm_cls, runner, tmp_output, tmp_agents, monkeypatch):
        """Chain emits chain_start, chain_stage_complete, chain_complete."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        piece_dir = tmp_output / "chain-event-piece"
        piece_dir.mkdir()
        meta = {
            "id": "chain-event-piece", "title": "Chain Events", "genre": "fiction",
            "type": "story", "audience": "general", "tone": "casual",
            "language": "en", "target_length": "1000 words",
            "current_stage": "outline", "agent_set": "default",
        }
        (piece_dir / "meta.yaml").write_text(yaml.dump(meta, default_flow_style=False))
        (piece_dir / _stage_filename("draft")).write_text("Draft content.")

        mock_client = MagicMock()
        mock_client.chat.return_value = '```json\n{"decision": "advance", "critique": "Good."}\n```'
        mock_llm_cls.return_value = mock_client

        q = queue.Queue()
        results = runner.run_chain("chain-event-piece", from_stage="outline",
                                   output_dir=tmp_output, event_queue=q)

        events = []
        while not q.empty():
            events.append(q.get())

        event_types = [e["type"] for e in events]
        assert "chain_start" in event_types
        assert "chain_stage_complete" in event_types
        assert "chain_complete" in event_types


# ---------------------------------------------------------------------------
# Async API endpoints
# ---------------------------------------------------------------------------


class TestAsyncEndpoints:
    """Test the async run API endpoints."""

    @pytest.fixture
    def client(self, tmp_output, tmp_agents, monkeypatch):
        """Flask test client."""
        from quill.app import app as flask_app
        from quill.run_manager import RunManager
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")
        # Clear RunManager state between tests
        manager = RunManager()
        manager._runs.clear()
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as c:
            yield c

    def test_run_async_returns_run_id(self, client, sample_piece, tmp_output, monkeypatch):
        """POST /run-async returns run_id."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        resp = client.post("/api/pieces/test-piece/run-async", json={
            "agent_set": "default",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "run_id" in data
        assert data["piece_id"] == "test-piece"
        assert len(data["run_id"]) == 12

    def test_run_async_piece_not_found(self, client, tmp_output, monkeypatch):
        """POST /run-async with nonexistent piece returns 404."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        resp = client.post("/api/pieces/no-such/run-async", json={})
        assert resp.status_code == 404

    def test_events_endpoint_returns_sse(self, client, sample_piece, tmp_output, monkeypatch):
        """GET /runs/<id>/events returns text/event-stream."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        # Start a run
        resp = client.post("/api/pieces/test-piece/run-async", json={
            "agent_set": "default",
        })
        run_id = resp.get_json()["run_id"]

        # Check SSE endpoint exists and returns correct content type
        # (We can't easily test the streaming in a sync test client)
        resp = client.get(f"/api/pieces/test-piece/runs/{run_id}/events")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type

    def test_events_endpoint_run_not_found(self, client, tmp_output, monkeypatch):
        """GET /events for nonexistent run returns 404."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        resp = client.get("/api/pieces/test-piece/runs/nonexistent/events")
        assert resp.status_code == 404

    def test_events_endpoint_wrong_piece(self, client, sample_piece, tmp_output, monkeypatch):
        """GET /events for run belonging to different piece returns 404."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        resp = client.post("/api/pieces/test-piece/run-async", json={})
        run_id = resp.get_json()["run_id"]

        resp = client.get(f"/api/pieces/other-piece/runs/{run_id}/events")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# RunManager cleanup
# ---------------------------------------------------------------------------


class TestRunManagerCleanup:
    """Test old run cleanup."""

    def test_cleanup_removes_old_runs(self):
        """Runs older than 5 minutes are cleaned up."""
        mgr = RunManager()
        # Manually insert an old run
        run_id = "oldrun123456"
        mgr._runs[run_id] = {
            "queue": queue.Queue(),
            "result": {"decision": "advance", "critique": "ok"},
            "result": None,
            "piece_id": "test",
            "stage": "review",
            "agent_set": "default",
            "chain": False,
            "started_at": time.time() - 600,  # 10 minutes ago
        }

        # Trigger cleanup via start_run (which calls _cleanup_old_runs)
        # Instead, call directly
        mgr._cleanup_old_runs()

        assert mgr.get_run(run_id) is None
