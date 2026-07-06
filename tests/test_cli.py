"""Unit tests for the sync-legacy CLI command."""

from __future__ import annotations

import os
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from quill.app import create_app
from quill.db import engine, db_session
from quill.models import Base, Project, DocumentNode, StageState, Metrics
from quill.piece import _stage_filename


def test_sync_legacy_command(tmp_path):
    """Test importing pieces via the sync-legacy CLI command."""
    # 1. Setup temporary output folder with a project and a legacy piece
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Create directory format piece
    proj_dir = output_dir / "my-project"
    proj_dir.mkdir()
    meta = {
        "id": "my-project",
        "title": "My Test Project",
        "genre": "fiction",
        "type": "story",
        "audience": "general",
        "tone": "casual",
        "language": "en",
        "target_length": "1000 words",
        "constraints": ["twist ending"],
        "current_stage": "outline",
        "created": "2026-01-01",
        "updated": "2026-01-02",
        "agent_set": "default",
        "trigger": "on_advance",
        "stage_states": {"brief": "ready", "outline": "ready"},
        "loops": {"outline": 1},
    }
    (proj_dir / "meta.yaml").write_text(yaml.dump(meta), encoding="utf-8")

    brief_file = proj_dir / _stage_filename("brief")
    brief_file.write_text(
        "---\nid: my-project\ntitle: My Test Project\ncurrent_stage: brief\n---\n\nThis is brief content.",
        encoding="utf-8",
    )

    outline_file = proj_dir / _stage_filename("outline")
    outline_file.write_text(
        "---\nid: my-project\ntitle: My Test Project\ncurrent_stage: outline\n---\n\nThis is outline content.",
        encoding="utf-8",
    )

    # Save a decision file for outline
    # prefix is derived from outline stage prefix
    prefix = _stage_filename("outline").split("_")[0]
    decision_file = proj_dir / f"{prefix}_outline.decision.md"
    decision_file.write_text(
        "## Decision: advance\n\n## Critique\nExcellent outline layout.\n", encoding="utf-8"
    )

    # Save a metrics file for outline
    metrics_file = proj_dir / f"{prefix}_outline.metrics.yaml"
    metrics_meta = {
        "flesch_ease": 75.0,
        "flesch_kincaid": 6.0,
        "word_count": 3,
        "sentence_count": 1,
        "avg_sentence_length": 3.0,
        "type_token_ratio": 1.0,
        "passive_voice_pct": 0.0,
    }
    metrics_file.write_text(yaml.dump(metrics_meta), encoding="utf-8")

    # Create a legacy single-file piece
    legacy_file = output_dir / "legacy-piece.md"
    legacy_meta = {
        "id": "legacy-piece",
        "title": "Legacy Title",
        "genre": "non-fiction",
        "current_stage": "brief",
    }
    legacy_file.write_text(
        f"---\n{yaml.dump(legacy_meta)}---\n\nLegacy brief content.", encoding="utf-8"
    )

    # Create a child piece (chapter) in directory format
    chapter_dir = output_dir / "my-project-chapter-1"
    chapter_dir.mkdir()
    chapter_meta = {
        "id": "my-project-chapter-1",
        "title": "Chapter 1",
        "parent": "my-project",
        "current_stage": "brief",
        "stage_states": {"brief": "ready"},
    }
    (chapter_dir / "meta.yaml").write_text(yaml.dump(chapter_meta), encoding="utf-8")
    (chapter_dir / _stage_filename("brief")).write_text(
        "---\nid: my-project-chapter-1\ntitle: Chapter 1\n---\n\nChapter brief content.",
        encoding="utf-8",
    )

    # 2. Patch database URL to in-memory, configure output dir, and invoke CLI command
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}):
        with patch("quill.cli.DEFAULT_OUTPUT_DIR", output_dir):
            # We must recreate the tables on the patched in-memory database
            Base.metadata.create_all(bind=engine)

            # Let's clean the DB first just to be sure
            session = db_session()
            session.query(Project).delete()
            session.query(DocumentNode).delete()
            session.query(StageState).delete()
            session.query(Metrics).delete()
            session.commit()

            app = create_app()
            runner = app.test_cli_runner()

            # Run sync command
            result = runner.invoke(args=["sync-legacy"])
            assert "Successfully synced piece 'my-project'" in result.output
            assert "Successfully synced piece 'legacy-piece'" in result.output
            assert "Successfully synced piece 'my-project-chapter-1'" in result.output
            assert result.exit_code == 0

            # 3. Assert database records were created correctly
            session = db_session()

            # Verify Project
            project = session.query(Project).filter_by(id="my-project").first()
            assert project is not None
            assert project.title == "My Test Project"
            assert project.genre == "fiction"
            assert project.current_stage == "outline"
            assert project.created_at.strftime("%Y-%m-%d") == "2026-01-01"

            # Verify project DocumentNode
            node = session.query(DocumentNode).filter_by(id="my-project").first()
            assert node is not None
            assert node.node_type == "project"

            # Verify child DocumentNode
            child_node = session.query(DocumentNode).filter_by(id="my-project-chapter-1").first()
            assert child_node is not None
            assert child_node.node_type == "chapter"
            assert child_node.project_id == "my-project"
            assert child_node.parent_id == "my-project"

            # Verify StageState for outline
            outline_state = (
                session.query(StageState)
                .filter_by(document_node_id="my-project", stage="outline")
                .first()
            )
            assert outline_state is not None
            assert outline_state.state == "ready"
            assert outline_state.loop_count == 1
            assert "This is outline content." in outline_state.body
            assert outline_state.decision == "advance"
            assert outline_state.critique == "Excellent outline layout."

            # Verify StageState for brief (which does not have decision/critique/metrics)
            brief_state = (
                session.query(StageState).filter_by(document_node_id="my-project", stage="brief").first()
            )
            assert brief_state is not None
            assert "This is brief content." in brief_state.body
            assert brief_state.decision is None

            # Verify Metrics for outline
            outline_metrics = (
                session.query(Metrics)
                .filter_by(document_node_id="my-project", stage="outline")
                .first()
            )
            assert outline_metrics is not None
            assert outline_metrics.flesch_ease == 75.0
            assert outline_metrics.word_count == 3

            # Verify Metrics for brief (should be auto-computed on the fly since .metrics.yaml was missing)
            brief_metrics = (
                session.query(Metrics).filter_by(document_node_id="my-project", stage="brief").first()
            )
            assert brief_metrics is not None
            assert brief_metrics.word_count > 0

            # Verify legacy piece Project/DocumentNode
            legacy_project = session.query(Project).filter_by(id="legacy-piece").first()
            assert legacy_project is not None
            assert legacy_project.genre == "non-fiction"

            # 4. Test deduplication - running again should skip
            result_again = runner.invoke(args=["sync-legacy"])
            assert "Piece 'my-project' already exists in database. Skipping." in result_again.output

            # 5. Test --force flag updates records
            # Let's modify a value in files
            (proj_dir / "meta.yaml").write_text(
                yaml.dump({**meta, "title": "My Updated Project Title"}), encoding="utf-8"
            )
            result_force = runner.invoke(args=["sync-legacy", "--force"])
            assert "Successfully synced piece 'my-project'" in result_force.output

            # Verify the update in DB
            session.expire_all()
            session = db_session()
            project_updated = session.query(Project).filter_by(id="my-project").first()
            assert project_updated.title == "My Updated Project Title"

            # 6. Test Safety Guard: skip actively generating
            # Set state in DB to generating
            outline_state = session.query(StageState).filter_by(document_node_id="my-project", stage="outline").first()
            outline_state.state = "generating"
            session.commit()

            result_safety = runner.invoke(args=["sync-legacy", "--force"])
            assert (
                "Skipping active piece 'my-project' (currently generating/running)."
                in result_safety.output
            )
