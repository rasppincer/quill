"""Tests for navigation + supersession endpoints.

Covers: stage navigation, trigger setting, supersession on re-run,
auto pipeline start, and state transitions.
"""
import pytest
import yaml
from pathlib import Path

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


class TestStageNavigation:
    """GET /api/pieces/<id>/stages/<stage> — navigate to a stage."""

    def test_navigate_to_ready_stage(self, client, tmp_output):
        """Can navigate to a stage that has been reached (state != empty)."""
        d = tmp_output / "nav-piece"
        d.mkdir()
        meta = {
            "id": "nav-piece", "title": "Nav", "current_stage": "draft",
            "stage_states": {"brief": "ready", "outline": "ready", "draft": "ready"},
        }
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: nav-piece\n---\n\nBrief content.")
        (d / _stage_filename("outline")).write_text("---\nid: nav-piece\n---\n\nOutline content.")
        (d / _stage_filename("draft")).write_text("---\nid: nav-piece\n---\n\nDraft content.")

        resp = client.get("/api/pieces/nav-piece/stages/brief")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "content" in data
        assert "Brief content" in data["content"]

    def test_navigate_to_empty_stage_blocked(self, client, tmp_output):
        """Cannot navigate to a stage with state 'empty'."""
        d = tmp_output / "nav-lock"
        d.mkdir()
        meta = {
            "id": "nav-lock", "title": "Lock", "current_stage": "outline",
            "stage_states": {"brief": "ready", "outline": "ready"},
        }
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: nav-lock\n---\n\nBrief.")

        resp = client.get("/api/pieces/nav-lock/stages/draft")
        assert resp.status_code == 404
        assert "not yet been reached" in resp.get_json()["error"]

    def test_navigate_to_superseded_stage_allowed(self, client, tmp_output):
        """Superseded stages are still navigable (content may still exist)."""
        d = tmp_output / "nav-super"
        d.mkdir()
        meta = {
            "id": "nav-super", "title": "Super", "current_stage": "outline",
            "stage_states": {"brief": "ready", "outline": "ready", "draft": "superseded"},
        }
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: nav-super\n---\n\nBrief.")
        (d / _stage_filename("draft")).write_text("---\nid: nav-super\n---\n\nOld draft.")

        resp = client.get("/api/pieces/nav-super/stages/draft")
        assert resp.status_code == 200

    def test_navigate_returns_metrics(self, client, tmp_output):
        """Navigation response includes metrics for the stage."""
        d = tmp_output / "nav-metrics"
        d.mkdir()
        meta = {
            "id": "nav-metrics", "title": "Metrics", "current_stage": "draft",
            "stage_states": {"brief": "ready", "draft": "ready"},
        }
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: nav-metrics\n---\n\nBrief content here.")
        (d / _stage_filename("draft")).write_text("---\nid: nav-metrics\n---\n\nDraft content here with enough words for metrics.")

        resp = client.get("/api/pieces/nav-metrics/stages/brief")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "metrics" in data


class TestTriggerSetting:
    """POST /api/pieces/<id>/trigger — set trigger mode."""

    def test_set_trigger(self, client, tmp_output):
        """Can set trigger to manual, on_advance, or auto."""
        d = tmp_output / "trigger-piece"
        d.mkdir()
        meta = {"id": "trigger-piece", "title": "Trigger", "current_stage": "brief"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: trigger-piece\n---\n\nBrief.")

        resp = client.post("/api/pieces/trigger-piece/trigger", json={"trigger": "manual"})
        assert resp.status_code == 200
        assert resp.get_json()["trigger"] == "manual"

    def test_get_trigger_in_piece_detail(self, client, tmp_output):
        """Piece detail includes trigger field."""
        d = tmp_output / "detail-trigger"
        d.mkdir()
        meta = {"id": "detail-trigger", "title": "Detail", "current_stage": "brief", "trigger": "auto"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: detail-trigger\n---\n\nBrief.")

        resp = client.get("/api/pieces/detail-trigger")
        assert resp.status_code == 200
        assert resp.get_json()["trigger"] == "auto"

    def test_invalid_trigger_rejected(self, client, tmp_output):
        """Invalid trigger value is rejected."""
        d = tmp_output / "bad-trigger"
        d.mkdir()
        meta = {"id": "bad-trigger", "title": "Bad", "current_stage": "brief"}
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: bad-trigger\n---\n\nBrief.")

        resp = client.post("/api/pieces/bad-trigger/trigger", json={"trigger": "invalid"})
        assert resp.status_code == 400


class TestSupersession:
    """Running agent on earlier stage supersedes later stages."""

    def test_supersede_on_earlier_stage_run(self, client, tmp_output, tmp_agents):
        """Running agent on outline when at draft supersedes draft."""
        d = tmp_output / "super-piece"
        d.mkdir()
        meta = {
            "id": "super-piece", "title": "Super", "current_stage": "draft",
            "stage_states": {"brief": "ready", "outline": "ready", "draft": "ready"},
        }
        (d / "meta.yaml").write_text(yaml.dump(meta))
        (d / _stage_filename("brief")).write_text("---\nid: super-piece\n---\n\nBrief.")
        (d / _stage_filename("outline")).write_text("---\nid: super-piece\n---\n\nOutline.")
        (d / _stage_filename("draft")).write_text("---\nid: super-piece\n---\n\nDraft.")

        # Run agent on outline (earlier than current draft)
        resp = client.post("/api/pieces/super-piece/run", json={
            "stage": "outline", "agent_set": "fiction",
        })
        assert resp.status_code == 200

        # Check draft is superseded
        from quill.piece import load_piece
        piece = load_piece(d)
        assert piece.get_stage_state("draft") == "superseded"
        assert piece.current_stage == "outline"
