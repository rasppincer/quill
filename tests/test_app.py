"""Tests for app.py — API endpoint contracts via Flask test client."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import yaml

from quill.app import app as flask_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_output, tmp_agents, monkeypatch):
    """Flask test client with isolated output and agent dirs."""
    monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
    monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
    monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def client_with_piece(client, sample_piece, tmp_output, monkeypatch):
    """Test client that already has a piece created."""
    monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
    return client


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "stages" in data

    def test_root_redirects(self, client):
        resp = client.get("/")
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TestPipelineAPI:
    def test_pipeline_info(self, client):
        resp = client.get("/api/pipeline")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "default"
        assert len(data["stages"]) == 9


# ---------------------------------------------------------------------------
# Pieces CRUD
# ---------------------------------------------------------------------------


class TestPiecesAPI:
    def test_list_pieces_empty(self, client, tmp_output):
        resp = client.get("/api/pieces")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0

    def test_create_piece(self, client, tmp_output):
        resp = client.post("/api/pieces", json={
            "title": "My Blog Post",
            "genre": "non-fiction",
            "type": "blog",
            "audience": "developers",
            "tone": "technical",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] == "my-blog-post"
        assert data["stage"] == "brief"

    def test_create_piece_missing_title(self, client):
        resp = client.post("/api/pieces", json={"genre": "fiction"})
        assert resp.status_code == 400
        assert "Missing" in resp.get_json()["error"]

    def test_create_duplicate_piece(self, client, sample_piece, tmp_output):
        resp = client.post("/api/pieces", json={"title": "Test Piece"})
        assert resp.status_code == 409

    def test_get_piece(self, client, sample_piece, tmp_output):
        resp = client.get("/api/pieces/test-piece")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "Test Piece"

    def test_get_nonexistent_piece(self, client):
        resp = client.get("/api/pieces/nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Stage management
# ---------------------------------------------------------------------------


class TestStageAPI:
    def test_advance(self, client, sample_piece, tmp_output):
        resp = client.post("/api/pieces/test-piece/advance")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["current_stage"] == "review"
        assert data["previous_stage"] == "draft"

    def test_reject(self, client, sample_piece, tmp_output):
        # First advance to review
        client.post("/api/pieces/test-piece/advance")
        # Then reject back to draft
        resp = client.post("/api/pieces/test-piece/reject", json={
            "target": "draft",
            "reason": "Needs rework",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["current_stage"] == "draft"

    def test_reject_invalid_target(self, client, sample_piece, tmp_output):
        resp = client.post("/api/pieces/test-piece/reject", json={"target": "done"})
        assert resp.status_code == 400

    def test_reject_missing_target(self, client, sample_piece, tmp_output):
        resp = client.post("/api/pieces/test-piece/reject", json={})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------


class TestModelAPI:
    def test_get_model_config(self, client):
        resp = client.get("/api/model")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["model"] == "test-model"

    def test_update_model_config(self, client):
        resp = client.put("/api/model", json={"model": "new-model"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["config"]["model"] == "new-model"

    def test_update_preserves_other_fields(self, client):
        client.put("/api/model", json={"model": "updated"})
        resp = client.get("/api/model")
        data = resp.get_json()
        assert data["model"] == "updated"
        assert data["api_base"] == "http://localhost:9999/v1"  # preserved

    def test_list_models(self, client):
        """Models endpoint connects to LLM — mock it."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({
                "data": [
                    {"id": "model-a"},
                    {"id": "model-b"},
                    {"id": "embed-model"},  # should be filtered
                ]
            }).encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            resp = client.get("/api/models")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "model-a" in data["models"]
            assert "model-b" in data["models"]
            assert "embed-model" not in data["models"]


# ---------------------------------------------------------------------------
# Agent API
# ---------------------------------------------------------------------------


class TestAgentAPI:
    def test_list_agent_sets(self, client):
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.get_json()
        names = [s["name"] for s in data["sets"]]
        assert "default" in names

    def test_list_agents_no_model_field(self, client):
        """Agent sets should not include model (it's global now)."""
        resp = client.get("/api/agents")
        data = resp.get_json()
        for s in data["sets"]:
            assert "model" not in s

    def test_agent_detail(self, client):
        resp = client.get("/api/agents/default")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "config" in data
        assert "prompts" in data

    def test_agent_detail_nonexistent(self, client):
        resp = client.get("/api/agents/nope")
        assert resp.status_code == 404

    def test_agents_for_stage(self, client):
        resp = client.get("/api/agents/for-stage/review")
        assert resp.status_code == 200
        data = resp.get_json()
        names = [s["name"] for s in data["agent_sets"]]
        assert "default" in names

    def test_agents_for_stage_no_model_field(self, client):
        """for-stage should not return model (it's global)."""
        resp = client.get("/api/agents/for-stage/review")
        data = resp.get_json()
        for s in data["agent_sets"]:
            assert "model" not in s

    def test_get_prompt(self, client):
        resp = client.get("/api/agents/default/review/prompt")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "content" in data
        assert len(data["content"]) > 0

    def test_update_prompt(self, client):
        resp = client.put("/api/agents/default/review/prompt", json={
            "content": "# New Review Prompt\n\nUpdated content.",
        })
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "updated"

    def test_update_prompt_empty_content(self, client):
        resp = client.put("/api/agents/default/review/prompt", json={"content": ""})
        assert resp.status_code == 400

    def test_prompt_endpoints_use_AGENTS_DIR(self, client, tmp_agents):
        """Prompt PUT must write to the monkeypatched dir, not the real one.

        Regression test: app.py previously hardcoded Path.parents[2]/agents
        instead of using AGENTS_DIR, so tests clobbered production prompt files.
        """
        from quill.agent import AGENTS_DIR
        real_agents = Path(__file__).resolve().parents[2] / "agents"
        real_review = real_agents / "default" / "review.prompt.md"

        # Read the real prompt before the test
        real_before = real_review.read_text(encoding="utf-8") if real_review.exists() else ""

        # PUT via API — should write to tmp_agents, not real_agents
        resp = client.put("/api/agents/default/review/prompt", json={
            "content": "# Test Isolation Check\n\nThis should not appear in the real file.",
        })
        assert resp.status_code == 200

        # Real file must be unchanged
        real_after = real_review.read_text(encoding="utf-8") if real_review.exists() else ""
        assert real_before == real_after, "Prompt PUT wrote to real agents dir instead of tmp!"

        # Tmp file must have the new content
        tmp_review = tmp_agents / "default" / "review.prompt.md"
        assert tmp_review.exists()
        assert "Test Isolation Check" in tmp_review.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Run agent
# ---------------------------------------------------------------------------


class TestRunAgent:
    @patch("quill.runner.LLMClient")
    def test_run_agent_on_piece(self, mock_llm_cls, client, sample_piece, tmp_output, monkeypatch):
        """Run agent on a piece's current stage."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        # Advance to review (which has an agent)
        client.post("/api/pieces/test-piece/advance")

        mock_client = MagicMock()
        mock_client.chat.return_value = '```json\n{"decision": "advance", "critique": "Solid work."}\n```'
        mock_llm_cls.return_value = mock_client

        resp = client.post("/api/pieces/test-piece/run", json={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["decision"] == "advance"

    def test_run_nonexistent_piece(self, client):
        resp = client.post("/api/pieces/nope/run", json={})
        assert resp.status_code == 404
