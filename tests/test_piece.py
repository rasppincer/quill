"""Tests for piece.py — loading, saving, directory format, metadata."""

import pytest
from pathlib import Path

import yaml

from quill.piece import Piece, load_piece, list_pieces, _stage_filename, get_piece, _FRONTMATTER_RE


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
        (d / _stage_filename("draft")).write_text("content", encoding="utf-8")
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
# Content cleaning
# ---------------------------------------------------------------------------


class TestCleanContent:
    """Test mechanical content cleanup."""

    def test_em_dash_replaced(self):
        assert Piece._clean_content("foo \u2014 bar") == "foo  -  bar"

    def test_en_dash_replaced(self):
        assert Piece._clean_content("foo \u2013 bar") == "foo  -  bar"

    def test_smart_single_quotes_replaced(self):
        assert Piece._clean_content("\u2018hello\u2019") == "'hello'"

    def test_smart_double_quotes_replaced(self):
        assert Piece._clean_content("\u201chello\u201d") == '"hello"'

    def test_nbsp_replaced(self):
        assert Piece._clean_content("foo\u00a0bar") == "foo bar"

    def test_regular_text_unchanged(self):
        text = "This is normal text with 'quotes' and \"double quotes\"."
        assert Piece._clean_content(text) == text

    def test_combined_cleaning(self):
        text = "He said \u201chello \u2014 it\u2019s fine\u201d"
        result = Piece._clean_content(text)
        assert "\u2014" not in result
        assert "\u2019" not in result
        assert "\u201c" not in result
        assert "\u201d" not in result
        assert '"' in result
        assert "'" in result

    def test_write_output_cleans_content(self, tmp_path):
        """write_output applies _clean_content before writing."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        p = Piece(id="clean-test", title="Test", genre="fiction", current_stage="draft")
        p.save(output_dir)
        p.write_output("draft", "He said \u201chello\u201d \u2014 fine.")
        content = (output_dir / "clean-test" / _stage_filename("draft")).read_text()
        assert "\u2014" not in content
        assert "\u201c" not in content


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
        assert path.name == _stage_filename("brief")
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
        assert (sample_piece / _stage_filename("draft")).exists()
        assert (sample_piece / _stage_filename("review")).exists()


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
                assert d["display_name"] == "05_draft.md"
            elif d["stage"] == "brief":
                assert d["display_name"] == "01_brief.md"

    def test_feedback_stages_no_prefix(self, sample_piece_with_review):
        piece = load_piece(sample_piece_with_review)
        displays = piece.display_stages()
        for d in displays:
            if d["stage"] == "review":
                assert d["display_name"] == _stage_filename("review")  # 04_review.md


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


# ---------------------------------------------------------------------------
# Database Persistence
# ---------------------------------------------------------------------------


class TestDatabasePersistence:
    """Test saving and loading pieces directly to/from the SQL database."""

    def test_save_and_load_top_level_project(self, tmp_path):
        from quill.models import Project, DocumentNode, StageState
        from quill.db import db_session

        p = Piece(
            id="db-project",
            title="DB Project",
            genre="non-fiction",
            type="essay",
            audience="academics",
            tone="formal",
            language="en",
            target_length="2000 words",
            constraints=["be concise"],
            current_stage="brief",
            body="This is a test essay brief.",
        )
        # Disable dual-write to only test DB
        p.dual_write = False
        p.save()

        # Query DB directly to verify
        session = db_session()
        proj = session.query(Project).filter_by(id="db-project").first()
        assert proj is not None
        assert proj.title == "DB Project"
        assert proj.genre == "non-fiction"
        assert proj.constraints == ["be concise"]
        assert proj.current_stage == "brief"

        node = session.query(DocumentNode).filter_by(id="db-project").first()
        assert node is not None
        assert node.title == "DB Project"
        assert node.node_type == "project"

        st_state = session.query(StageState).filter_by(document_node_id="db-project", stage="brief").first()
        assert st_state is not None
        assert st_state.body == "This is a test essay brief."
        assert st_state.state == "fresh"

        # Load back via load_piece
        loaded = load_piece(tmp_path / "db-project")
        assert loaded.id == "db-project"
        assert loaded.title == "DB Project"
        assert loaded.body == "This is a test essay brief."
        assert loaded.current_stage == "brief"
        assert loaded.genre == "non-fiction"
        assert loaded.type == "essay"

    def test_save_and_load_child_chapter(self, tmp_path):
        from quill.models import DocumentNode, StageState
        from quill.db import db_session

        # Save parent first (to satisfy ForeignKey projects.id)
        parent = Piece(id="parent-story", title="Parent Story", genre="fiction")
        parent.dual_write = False
        parent.save()

        child = Piece(
            id="parent-story-chapter-1",
            title="Chapter 1: The Beginning",
            parent="parent-story",
            current_stage="draft",
            body="Chapter 1 content goes here.",
        )
        child.dual_write = False
        child.save()

        # Query DB directly
        session = db_session()
        node = session.query(DocumentNode).filter_by(id="parent-story-chapter-1").first()
        assert node is not None
        assert node.title == "Chapter 1: The Beginning"
        assert node.project_id == "parent-story"
        assert node.parent_id == "parent-story"

        st_state = session.query(StageState).filter_by(document_node_id="parent-story-chapter-1", stage="draft").first()
        assert st_state is not None
        assert st_state.body == "Chapter 1 content goes here."

        # Load child back
        loaded_child = load_piece(tmp_path / "parent-story-chapter-1")
        assert loaded_child.id == "parent-story-chapter-1"
        assert loaded_child.parent == "parent-story"
        assert loaded_child.body == "Chapter 1 content goes here."
        assert loaded_child.current_stage == "draft"

    def test_advance_and_supersede_db(self):
        from quill.models import StageState
        from quill.db import db_session

        p = Piece(id="flow-test", title="Flow Test", current_stage="brief", body="Brief content.")
        p.dual_write = False
        p.save()

        # Advance to outline
        p.advance_to("outline")
        p.write_output("outline", "Outline content.")
        p.save()

        session = db_session()
        st_brief = session.query(StageState).filter_by(document_node_id="flow-test", stage="brief").first()
        st_outline = session.query(StageState).filter_by(document_node_id="flow-test", stage="outline").first()
        assert st_brief.body == "Brief content."
        assert st_outline.body == "Outline content."

        # Supersede back to brief
        p.supersede_from("brief")

        # Re-query
        st_outline_new = session.query(StageState).filter_by(document_node_id="flow-test", stage="outline").first()
        assert st_outline_new.state == "fresh"
        assert st_outline_new.body is None

    def test_resolved_agent_set_autodetect(self):
        # 1. Manually specified agent_set
        p1 = Piece(id="test1", title="Test 1", agent_set="non-fiction")
        assert p1.resolved_agent_set == "non-fiction"

        # 2. Empty agent_set, non-fiction genre
        p2 = Piece(id="test2", title="Test 2", agent_set="", genre="non-fiction")
        assert p2.resolved_agent_set == "non-fiction"

        # 3. Empty agent_set, fiction genre
        p3 = Piece(id="test3", title="Test 3", agent_set="", genre="fiction")
        assert p3.resolved_agent_set == "fiction"

        # 4. Empty agent_set, unknown genre -> fallback to default
        p4 = Piece(id="test4", title="Test 4", agent_set="", genre="unknown-genre")
        assert p4.resolved_agent_set == "default"

        # 5. Empty agent_set, empty genre -> fallback to default
        p5 = Piece(id="test5", title="Test 5", agent_set="", genre="")
        assert p5.resolved_agent_set == "default"

