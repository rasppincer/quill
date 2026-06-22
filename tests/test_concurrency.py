"""Tests for concurrency guards — piece-level locking and advance/reject blocking."""
import queue
import time
import uuid

import pytest
import yaml


class TestConcurrencyGuards:
    """Verify that concurrent operations on the same piece are blocked."""

    @pytest.fixture
    def client(self, tmp_output, tmp_agents, monkeypatch):
        from quill.app import app as flask_app
        from quill.run_manager import RunManager
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
        monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")
        RunManager()._runs.clear()
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as c:
            yield c

    def _create_at_stage(self, tmp_output, piece_id, stage):
        """Create a piece directory at a specific stage."""
        from quill.piece import Piece, _stage_filename
        piece = Piece(id=piece_id, title=f"Test {piece_id}", genre="fiction", current_stage=stage)
        piece.save(tmp_output)
        # Write some content so the piece is valid
        stage_file = tmp_output / piece_id / _stage_filename(stage)
        stage_file.write_text(f"Content for {stage}", encoding="utf-8")
        return piece

    def _inject_running_job(self, piece_id, stage="review"):
        """Inject a fake running job into RunManager."""
        from quill.run_manager import RunManager
        manager = RunManager()
        run_id = uuid.uuid4().hex[:12]
        with manager._run_lock:
            manager._runs[run_id] = {
                "queue": queue.Queue(),
                "status": "running",
                "result": None,
                "piece_id": piece_id,
                "stage": stage,
                "agent_set": "default",
                "chain": False,
                "started_at": time.time(),
            }
        return run_id

    def test_cannot_start_two_runs_on_same_piece(self, client, tmp_output):
        """Second run-async on same piece returns 409."""
        self._create_at_stage(tmp_output, "lock-test", "review")
        self._inject_running_job("lock-test")

        resp = client.post("/api/pieces/lock-test/run-async", json={
            "stage": "review", "agent_set": "default",
        })
        assert resp.status_code == 409
        assert "already has a running job" in resp.get_json()["error"]

    def test_cannot_advance_while_running(self, client, tmp_output):
        """Advance blocked while piece has a running job."""
        self._create_at_stage(tmp_output, "advance-block", "review")
        self._inject_running_job("advance-block", stage="review")

        resp = client.post("/api/pieces/advance-block/advance")
        assert resp.status_code == 409
        assert "has a running job" in resp.get_json()["error"]

    def test_cannot_reject_while_running(self, client, tmp_output):
        """Reject blocked while piece has a running job."""
        self._create_at_stage(tmp_output, "reject-block", "review")
        self._inject_running_job("reject-block", stage="review")

        resp = client.post("/api/pieces/reject-block/reject", json={"target": "draft"})
        assert resp.status_code == 409
        assert "has a running job" in resp.get_json()["error"]

    def test_can_start_runs_on_different_pieces(self, client, tmp_output):
        """Different pieces can run concurrently."""
        self._create_at_stage(tmp_output, "piece-a", "review")
        self._create_at_stage(tmp_output, "piece-b", "review")

        resp_a = client.post("/api/pieces/piece-a/run-async", json={
            "stage": "review", "agent_set": "default",
        })
        resp_b = client.post("/api/pieces/piece-b/run-async", json={
            "stage": "review", "agent_set": "default",
        })
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_a.get_json()["run_id"] != resp_b.get_json()["run_id"]

    def test_advance_allowed_when_no_running_job(self, client, tmp_output):
        """Advance works when no job is running."""
        self._create_at_stage(tmp_output, "advance-ok", "review")

        resp = client.post("/api/pieces/advance-ok/advance")
        assert resp.status_code == 200
