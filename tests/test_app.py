"""Tests for app.py — API endpoint contracts via Flask test client."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import yaml

from quill.app import app as flask_app
from quill.piece import _stage_filename


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
        assert len(data["stages"]) == 10


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

    def test_body_length_nonzero_when_current_stage_missing(
        self, client, sample_piece, tmp_output, monkeypatch
    ):
        """Regression: body_length should not be 0 when current stage file
        doesn't exist but other stage files have content."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        # Advance the piece so current_stage=review, but don't create review.md
        piece_dir = tmp_output / "test-piece"
        meta_path = piece_dir / "meta.yaml"
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        meta["current_stage"] = "review"  # no review.md exists
        meta_path.write_text(
            yaml.dump(meta, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        resp = client.get("/api/pieces/test-piece")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["body_length"] > 0, (
            "body_length should be > 0 even when current stage file is missing"
        )
        assert len(data["body"]) > 0


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

    def test_agents_for_stage_excludes_flavor_without_prompt(self, client):
        """non-fiction missing draft.prompt.md must not appear for draft stage."""
        resp = client.get("/api/agents/for-stage/draft")
        assert resp.status_code == 200
        data = resp.get_json()
        names = [s["name"] for s in data["agent_sets"]]
        assert "fiction" in names
        assert "non-fiction" not in names

    def test_agents_for_stage_excludes_flavor_without_outline(self, client):
        """non-fiction missing outline.prompt.md must not appear for outline stage."""
        resp = client.get("/api/agents/for-stage/outline")
        assert resp.status_code == 200
        data = resp.get_json()
        names = [s["name"] for s in data["agent_sets"]]
        assert "fiction" in names
        assert "non-fiction" not in names

    def test_agents_for_stage_includes_all_when_all_have_prompt(self, client):
        """Stage where all flavors have a prompt returns all three."""
        resp = client.get("/api/agents/for-stage/review")
        assert resp.status_code == 200
        data = resp.get_json()
        names = [s["name"] for s in data["agent_sets"]]
        assert "default" in names
        assert "fiction" in names
        assert "non-fiction" in names

    def test_agents_for_stage_empty_for_stage_without_any_prompts(self, client):
        """Stage that no flavor has prompts for returns empty list."""
        resp = client.get("/api/agents/for-stage/nonexistent-stage")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["agent_sets"] == []

    def test_agents_for_stage_response_shape(self, client):
        """Response includes stage name and agent_sets with name + description."""
        resp = client.get("/api/agents/for-stage/review")
        data = resp.get_json()
        assert data["stage"] == "review"
        for s in data["agent_sets"]:
            assert "name" in s
            assert "description" in s

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
# Debug prompt
# ---------------------------------------------------------------------------


class TestDebugPrompt:
    def test_debug_prompt_returns_composed_prompt(self, client, sample_piece, tmp_output, monkeypatch):
        """Debug endpoint returns the filled prompt without calling LLM."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        # Advance to review
        client.post("/api/pieces/test-piece/advance")

        resp = client.get("/api/pieces/test-piece/prompt/review")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["stage"] == "review"
        assert "single_call" in data
        assert data["single_call"]["char_count"] > 0
        assert data["is_content_stage"] is False

    def test_debug_prompt_content_stage_shows_both_calls(self, client, sample_piece_with_review, tmp_output, monkeypatch):
        """Content stage debug shows generate + evaluate prompts."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        # Advance to revise (a content stage that has a prompt in the fixture)
        client.post("/api/pieces/test-piece/advance")  # draft → review
        client.post("/api/pieces/test-piece/advance")  # review → revise

        resp = client.get("/api/pieces/test-piece/prompt/revise")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_content_stage"] is True
        assert "generate" in data
        assert "evaluate" in data
        assert data["generate"]["char_count"] > 0

    def test_debug_prompt_with_agent_set(self, client, sample_piece, tmp_output, monkeypatch):
        """Debug endpoint accepts agent_set query param."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        resp = client.get("/api/pieces/test-piece/prompt/review?agent_set=fiction")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["agent_set"] == "fiction"

    def test_debug_prompt_nonexistent_piece(self, client):
        resp = client.get("/api/pieces/nope/prompt/review")
        assert resp.status_code == 404

    def test_debug_prompt_template_vars(self, client, sample_piece, tmp_output, monkeypatch):
        """Debug shows all template variable values including loop state."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        resp = client.get("/api/pieces/test-piece/prompt/review")
        data = resp.get_json()
        tv = data["template_vars"]
        assert tv["TITLE"] == "Test Piece"
        assert tv["GENRE"] == "fiction"
        assert tv["STAGE"] == "review"
        assert tv["loop_count"] == 0
        assert tv["is_looping"] is False
        assert tv["max_loops"] == 3


# ---------------------------------------------------------------------------
# Run agent
# ---------------------------------------------------------------------------


class TestRunAgent:
    @patch("quill.runner.LLMClient")
    def test_run_agent_on_piece(self, mock_llm_cls, client, sample_piece, tmp_output, monkeypatch):
        """Run agent on a piece's current stage."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

        # Set manual trigger so advance doesn't auto-run agent
        from quill.piece import load_piece
        piece = load_piece(sample_piece)
        piece.trigger = "manual"
        piece.save()

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


# ---------------------------------------------------------------------------
# Import (mid-progress)
# ---------------------------------------------------------------------------


class TestImportAPI:
    def test_import_mid_progress_seruil(self, client, tmp_output, monkeypatch):
        """Import a piece called 'Seruil' at draft stage with partial content."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        resp = client.post("/api/pieces/import", json={
            "title": "Seruil",
            "current_stage": "draft",
            "genre": "fiction",
            "type": "story",
            "body": "Seruil stood at the edge of the known world, staring into the void.",
            "stages": {
                "brief": "A fantasy story about Seruil, a wanderer between realms.",
                "outline": "1. Seruil at the boundary\n2. The void speaks\n3. Choice",
                "draft": "Seruil stood at the edge of the known world, staring into the void.",
            },
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] == "seruil"
        assert data["stage"] == "draft"
        assert "brief" in data["stages_imported"]
        assert "draft" in data["stages_imported"]
        assert "outline" in data["stages_imported"]

        # Verify the piece can be retrieved
        resp = client.get("/api/pieces/seruil")
        assert resp.status_code == 200
        detail = resp.get_json()
        assert detail["title"] == "Seruil"
        assert detail["genre"] == "fiction"
        assert detail["current_stage"] == "draft"
        assert detail["body_length"] > 0

        # Verify multiple stage files exist on disk
        piece_dir = tmp_output / "seruil"
        assert (piece_dir / _stage_filename("brief")).exists()
        assert (piece_dir / _stage_filename("outline")).exists()
        assert (piece_dir / _stage_filename("draft")).exists()
        assert (piece_dir / "meta.yaml").exists()

    def test_import_minimal(self, client, tmp_output, monkeypatch):
        """Import with only a title — everything else defaults."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        resp = client.post("/api/pieces/import", json={"title": "Minimal Piece"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["stage"] == "brief"
        assert data["id"] == "minimal-piece"

    def test_import_with_body_only(self, client, tmp_output, monkeypatch):
        """Import at revise stage with just a body, no stages dict."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        resp = client.post("/api/pieces/import", json={
            "title": "Body Only",
            "current_stage": "revise",
            "body": "This is the revised text.",
            "genre": "non-fiction",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["stage"] == "revise"

        # Should have revise.md but no earlier stage files
        piece_dir = tmp_output / "body-only"
        assert (piece_dir / _stage_filename("revise")).exists()
        assert not (piece_dir / _stage_filename("brief")).exists()
        assert not (piece_dir / _stage_filename("draft")).exists()

    def test_import_missing_title(self, client):
        """Import without title returns 400."""
        resp = client.post("/api/pieces/import", json={"genre": "fiction"})
        assert resp.status_code == 400
        assert "Missing" in resp.get_json()["error"]

    def test_import_duplicate(self, client, sample_piece, tmp_output, monkeypatch):
        """Import a piece with existing ID returns 409."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        resp = client.post("/api/pieces/import", json={"title": "Test Piece"})
        assert resp.status_code == 409

    def test_import_invalid_stage(self, client):
        """Import with an unknown stage returns 400."""
        resp = client.post("/api/pieces/import", json={
            "title": "Bad Stage",
            "current_stage": "nonexistent",
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "valid_stages" in data

    def test_import_preserves_created_date(self, client, tmp_output, monkeypatch):
        """Import can specify a custom created date."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        resp = client.post("/api/pieces/import", json={
            "title": "Old Piece",
            "current_stage": "draft",
            "created": "2025-03-15",
            "body": "An old draft.",
        })
        assert resp.status_code == 201

        resp = client.get("/api/pieces/old-piece")
        assert resp.status_code == 200
        assert resp.get_json()["created"] == "2025-03-15"

    def test_import_can_advance_after(self, client, tmp_output, monkeypatch):
        """An imported piece can be advanced through the pipeline."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        client.post("/api/pieces/import", json={
            "title": "Advanceable",
            "current_stage": "draft",
            "body": "Draft content here.",
        })
        resp = client.post("/api/pieces/advanceable/advance")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["current_stage"] == "review"


# ---------------------------------------------------------------------------
# Audio generation API
# ---------------------------------------------------------------------------


class TestAudioAPI:
    """Tests for /api/pieces/<id>/audio endpoints."""

    def test_audio_generate_no_piece(self, client):
        """Generate audio for nonexistent piece returns 404."""
        resp = client.post("/api/pieces/nope/audio", json={})
        assert resp.status_code == 404

    def test_audio_generate_no_content(self, client, tmp_output, monkeypatch):
        """Generate audio for empty stage returns 400."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
        # Create a piece with empty draft
        piece_dir = tmp_output / "empty-piece"
        piece_dir.mkdir()
        meta = {
            "id": "empty-piece", "title": "Empty", "current_stage": "draft",
            "language": "en", "created": "2026-01-01", "updated": "2026-01-01",
        }
        (piece_dir / "meta.yaml").write_text(yaml.dump(meta), encoding="utf-8")
        (piece_dir / _stage_filename("draft")).write_text(
            "---\nid: empty-piece\n---\n\n   ", encoding="utf-8"
        )

        resp = client.post("/api/pieces/empty-piece/audio", json={})
        assert resp.status_code == 400
        assert "no content" in resp.get_json()["error"].lower()

    def test_audio_generate_success(self, client, sample_piece, monkeypatch, tmp_path):
        """Generate audio produces an MP3 file."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", sample_piece.parent)

        # Mock the actual TTS generation
        from quill.audio import AudioResult
        import quill.audio as audio_mod

        def fake_generate(text, output_dir, filename="audio.mp3", options=None):
            output_dir.mkdir(parents=True, exist_ok=True)
            out = output_dir / filename
            out.write_bytes(b"fake-mp3-data-here")
            return AudioResult(
                path=str(out), filename=filename,
                voice="en-US-AriaNeural", size_bytes=18,
                created="2026-06-21 12:00:00",
            )

        monkeypatch.setattr("quill.audio.generate_audio", fake_generate)

        resp = client.post("/api/pieces/test-piece/audio", json={
            "stage": "draft",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["piece_id"] == "test-piece"
        assert data["stage"] == "draft"
        assert data["voice"] == "en-US-AriaNeural"
        assert data["size_bytes"] == 18
        assert data["filename"].endswith(".mp3")

    def test_audio_generate_with_options(self, client, sample_piece, monkeypatch):
        """Generate audio passes options through."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", sample_piece.parent)

        captured_options = {}

        from quill.audio import AudioResult

        def fake_generate(text, output_dir, filename="audio.mp3", options=None):
            captured_options["voice"] = options.voice
            captured_options["rate"] = options.rate
            captured_options["pitch"] = options.pitch
            output_dir.mkdir(parents=True, exist_ok=True)
            out = output_dir / filename
            out.write_bytes(b"data")
            return AudioResult(
                path=str(out), filename=filename,
                voice=options.voice or "en-US-AriaNeural", size_bytes=4,
            )

        monkeypatch.setattr("quill.audio.generate_audio", fake_generate)

        resp = client.post("/api/pieces/test-piece/audio", json={
            "voice": "en-GB-SoniaNeural",
            "rate": "+20%",
            "pitch": "+5Hz",
        })
        assert resp.status_code == 200
        assert captured_options["voice"] == "en-GB-SoniaNeural"
        assert captured_options["rate"] == "+20%"
        assert captured_options["pitch"] == "+5Hz"

    def test_audio_list_empty(self, client, sample_piece, monkeypatch):
        """List audio files returns empty when none exist."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", sample_piece.parent)

        resp = client.get("/api/pieces/test-piece/audio")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0
        assert data["files"] == []

    def test_audio_list_with_files(self, client, sample_piece, monkeypatch):
        """List audio files returns existing MP3s."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", sample_piece.parent)

        # Create audio files
        audio_dir = sample_piece / "audio"
        audio_dir.mkdir()
        (audio_dir / "draft_20260621.mp3").write_bytes(b"audio1")
        (audio_dir / "draft_20260622.mp3").write_bytes(b"audio2")

        resp = client.get("/api/pieces/test-piece/audio")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 2
        assert data["files"][0]["filename"] == "draft_20260622.mp3"

    def test_audio_download(self, client, sample_piece, monkeypatch):
        """Download an audio file."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", sample_piece.parent)

        audio_dir = sample_piece / "audio"
        audio_dir.mkdir()
        (audio_dir / "test.mp3").write_bytes(b"mp3-content")

        resp = client.get("/api/pieces/test-piece/audio/test.mp3")
        assert resp.status_code == 200
        assert resp.data == b"mp3-content"

    def test_audio_download_not_found(self, client, sample_piece, monkeypatch):
        """Download nonexistent audio file returns 404."""
        monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", sample_piece.parent)

        resp = client.get("/api/pieces/test-piece/audio/nope.mp3")
        assert resp.status_code == 404

    def test_audio_list_no_piece(self, client):
        """List audio for nonexistent piece returns 404."""
        resp = client.get("/api/pieces/nonexistent/audio")
        assert resp.status_code == 404

    def test_audio_voices_presets(self, client):
        """Voice presets endpoint returns curated voice list."""
        resp = client.get("/api/audio/voices")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "presets" in data
        assert "en" in data["presets"]
        assert len(data["presets"]["en"]) >= 3
