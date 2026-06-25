"""Tests for auto pipeline and interrupt endpoints."""
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock

from quill.app import app as flask_app
from quill.piece import _stage_filename


@pytest.fixture
def client(tmp_output, tmp_agents, monkeypatch):
    """Flask test client with isolated output and agent dirs."""
    monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
    monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
    monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


class TestAutoPipeline:
    """POST /api/pieces/<id>/auto — start auto mode."""

    def test_auto_starts_chain(self, client, tmp_output, tmp_agents):
        """Auto endpoint starts a chain run."""
        d = tmp_output / "auto-piece"
        d.mkdir()
        meta = {"id": "auto-piece", "title": "Auto", "current_stage": "brief"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: auto-piece\n---\n\nBrief content.")

        resp = client.post("/api/pieces/auto-piece/auto")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["trigger"] == "auto"
        assert "run_id" in data

    def test_auto_requires_brief_content(self, client, tmp_output, tmp_agents):
        """Cannot start auto pipeline without brief content."""
        d = tmp_output / "no-brief"
        d.mkdir()
        meta = {"id": "no-brief", "title": "No Brief", "current_stage": "brief"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: no-brief\n---\n\n")

        resp = client.post("/api/pieces/no-brief/auto")
        assert resp.status_code == 400
        assert "brief" in resp.get_json()["error"].lower()

    def test_auto_sets_trigger(self, client, tmp_output, tmp_agents):
        """Auto endpoint sets trigger to 'auto'."""
        d = tmp_output / "trigger-auto"
        d.mkdir()
        meta = {"id": "trigger-auto", "title": "TA", "current_stage": "brief"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: trigger-auto\n---\n\nBrief.")

        resp = client.post("/api/pieces/trigger-auto/auto")
        assert resp.status_code == 200

        from quill.piece import load_piece
        piece = load_piece(d)
        assert piece.trigger == "auto"


class TestInterrupt:
    """POST /api/pieces/<id>/interrupt — stop auto mode."""

    def test_interrupt_downgrades_trigger(self, client, tmp_output, tmp_agents):
        """Interrupt downgrades trigger to on_advance."""
        d = tmp_output / "int-piece"
        d.mkdir()
        meta = {"id": "int-piece", "title": "Int", "current_stage": "brief", "trigger": "auto"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: int-piece\n---\n\nBrief.")

        # Start auto pipeline first
        client.post("/api/pieces/int-piece/auto")

        # Interrupt
        resp = client.post("/api/pieces/int-piece/interrupt")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["trigger"] == "on_advance"

    def test_interrupt_without_running_job(self, client, tmp_output, tmp_agents):
        """Cannot interrupt when no job is running."""
        d = tmp_output / "no-run"
        d.mkdir()
        meta = {"id": "no-run", "title": "NR", "current_stage": "brief"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: no-run\n---\n\nBrief.")

        resp = client.post("/api/pieces/no-run/interrupt")
        assert resp.status_code == 400


class TestAutoModeGuard:
    """Run/advance blocked during auto mode."""

    def test_run_blocked_during_auto(self, client, tmp_output, tmp_agents):
        """Cannot run agent manually while auto pipeline is running."""
        d = tmp_output / "guard-run"
        d.mkdir()
        meta = {"id": "guard-run", "title": "GR", "current_stage": "brief", "trigger": "auto"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: guard-run\n---\n\nBrief.")

        # Start auto pipeline
        client.post("/api/pieces/guard-run/auto")

        # Try manual run — should be blocked
        resp = client.post("/api/pieces/guard-run/run", json={"stage": "brief"})
        assert resp.status_code == 409
        assert "auto mode" in resp.get_json()["error"].lower()
