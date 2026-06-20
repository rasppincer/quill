"""Tests for piece.py — loading, saving, directory format, metadata."""

import pytest
from pathlib import Path

import yaml

from quill.piece import Piece, load_piece, list_pieces, get_piece, _FRONTMATTER_RE


# ---------------------------------------------------------------------------
# Frontmatter regex
# ---------------------------------------------------------------------------


class TestFrontmatterRegex:
    """Test the YAML frontmatter parser."""

    def test_parses_valid_frontmatter(self):
        text = "---\nid: my-piece\ntitle: Hello\n---\n\nBody here."
        m = _FRONTMATTER_RE.match(text)
        assert m is not None
        meta = yaml.safe_load(m.group(1))
        assert meta["id"] == "my-piece"
        assert text[m.end():] == "Body here."

    def test_no_frontmatter(self):
        text = "Just plain text, no frontmatter."
        m = _FRONTMATTER_RE.match(text)
        assert m is None

    def test_empty_body(self):
        text = "---\nid: test\n---\n"
        m = _FRONTMATTER_RE.match(text)
        assert m is not None
        body = text[m.end():]
        assert body.strip() == ""


# ---------------------------------------------------------------------------
# Piece loading (directory format)
# ---------------------------------------------------------------------------


class TestLoadPiece:
    """Test loading pieces from directory format."""

    def test_loads_directory_piece(self, sample_piece):
        piece = load_piece(sample_piece)
        assert piece.id == "test-piece"
        assert piece.title == "Test Piece"
        assert piece.genre == "fiction"
        assert piece.current_stage == "draft"
        assert piece.agent_set == "default"
        assert piece._is_legacy is False

    def test_loads_body_from_current_stage(self, sample_piece):
        piece = load_piece(sample_piece)
        assert "draft content" in piece.body

    def test_missing_meta_yaml_raises(self, tmp_output):
        """Directory without meta.yaml should raise ValueError."""
        d = tmp_output / "no-meta"
        d.mkdir()
        (d / "draft.md").write_text("content", encoding="utf-8")
        with pytest.raises(ValueError, match="No meta.yaml"):
            load_piece(d)

    def test_missing_stage_file_graceful(self, tmp_output):
        """meta.yaml pointing to non-existent stage file — body should be empty."""
        d = tmp_output / "missing-stage"
        d.mkdir()
        meta = {"id": "missing-stage", "title": "Test", "current_stage": "review"}
        (d / "meta.yaml").write_text(yaml.dump(meta), encoding="utf-8")
        # No review.md exists
        piece = load_piece(d)
        assert piece.current_stage == "review"
        assert piece.body == ""

    def test_loads_agent_set(self, sample_piece):
        piece = load_piece(sample_piece)
        assert piece.agent_set == "default"


# ---------------------------------------------------------------------------
# Piece saving
# ---------------------------------------------------------------------------


class TestSavePiece:
    """Test saving pieces to disk."""

    def test_save_creates_directory_structure(self, tmp_output):
        piece = Piece(
            id="new-piece",
            title="New Piece",
            genre="non-fiction",
            type="blog",
            current_stage="brief",
            body="This is the brief.",
        )
        path = piece.save(tmp_output)

        assert path.exists()
        assert path.name == "brief.md"
        assert (tmp_output / "new-piece" / "meta.yaml").exists()

    def test_save_meta_yaml_content(self, tmp_output):
        piece = Piece(
            id="meta-test",
            title="Meta Test",
            genre="fiction",
            current_stage="draft",
            body="Draft body.",
        )
        piece.save(tmp_output)

        meta = yaml.safe_load((tmp_output / "meta-test" / "meta.yaml").read_text())
        assert meta["id"] == "meta-test"
        assert meta["title"] == "Meta Test"
        assert meta["current_stage"] == "draft"

    def test_save_stage_file_has_frontmatter(self, tmp_output):
        piece = Piece(id="fm-test", title="FM Test", current_stage="brief", body="Content.")
        path = piece.save(tmp_output)

        text = path.read_text()
        assert text.startswith("---\n")
        assert "Content." in text

    def test_save_preserves_existing_stages(self, sample_piece, tmp_output):
        """Saving at a new stage shouldn't delete old stage files."""
        piece = load_piece(sample_piece)
        assert piece.current_stage == "draft"

        # Advance to review
        piece.current_stage = "review"
        piece.body = "Review feedback."
        piece.save(tmp_output)

        # Both draft.md and review.md should exist
        assert (sample_piece / "draft.md").exists()
        assert (sample_piece / "review.md").exists()


# ---------------------------------------------------------------------------
# Piece listing
# ---------------------------------------------------------------------------


class TestListPieces:
    """Test listing pieces from output directory."""

    def test_list_finds_directory_pieces(self, sample_piece, tmp_output):
        pieces = list_pieces(tmp_output)
        ids = [p.id for p in pieces]
        assert "test-piece" in ids

    def test_list_skips_hidden_dirs(self, tmp_output):
        """Directories starting with . or _ should be skipped."""
        (tmp_output / ".hidden").mkdir()
        (tmp_output / ".hidden" / "test.md").write_text("---\nid: h\n---\n\nx")
        pieces = list_pieces(tmp_output)
        assert len(pieces) == 0

    def test_get_piece_by_id(self, sample_piece, tmp_output):
        piece = get_piece("test-piece", tmp_output)
        assert piece is not None
        assert piece.title == "Test Piece"

    def test_get_nonexistent_piece(self, tmp_output):
        assert get_piece("nope", tmp_output) is None


# ---------------------------------------------------------------------------
# Display stages
# ---------------------------------------------------------------------------


class TestDisplayStages:
    """Test the prefixed display names."""

    def test_content_stages_get_prefix(self, sample_piece):
        piece = load_piece(sample_piece)
        displays = piece.display_stages()
        for d in displays:
            if d["stage"] == "draft":
                assert d["display_name"] == "03_draft.md"
            elif d["stage"] == "brief":
                assert d["display_name"] == "01_brief.md"

    def test_feedback_stages_no_prefix(self, sample_piece_with_review):
        piece = load_piece(sample_piece_with_review)
        displays = piece.display_stages()
        for d in displays:
            if d["stage"] == "review":
                assert d["display_name"] == "review.md"  # no prefix


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    """Test piece serialization."""

    def test_to_dict_has_expected_keys(self, sample_piece):
        piece = load_piece(sample_piece)
        d = piece.to_dict()
        assert "id" in d
        assert "title" in d
        assert "body_length" in d
        assert "stages" in d
        assert "display_stages" in d

    def test_body_length(self, sample_piece):
        piece = load_piece(sample_piece)
        d = piece.to_dict()
        assert d["body_length"] == len(piece.body)
