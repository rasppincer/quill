"""Shared fixtures for Quill test suite."""

import pytest
from pathlib import Path

import yaml


@pytest.fixture
def tmp_output(tmp_path):
    """Temporary output directory for pieces."""
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def tmp_agents(tmp_path):
    """Temporary agents directory with model.yaml and one agent set."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    # Global model config
    model_cfg = {
        "api_base": "http://localhost:9999/v1",
        "api_key": "",
        "model": "test-model",
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    (agents_dir / "model.yaml").write_text(
        yaml.dump(model_cfg, default_flow_style=False), encoding="utf-8"
    )

    # Default agent set
    default_dir = agents_dir / "default"
    default_dir.mkdir()
    set_cfg = {
        "description": "Test agents",
        "temperature": 0.7,
        "max_tokens": 4096,
        "max_loops": 3,
        "trigger": "on_advance",
        "stages": {
            "review": {"name": "Review Agent", "temperature": 0.5},
            "revise": {"name": "Revise Agent", "temperature": 0.6},
        },
    }
    (default_dir / "config.yaml").write_text(
        yaml.dump(set_cfg, default_flow_style=False), encoding="utf-8"
    )

    # Prompt templates
    (default_dir / "review.prompt.md").write_text(
        "# Review Agent\n\nReview this:\n{{CONTENT}}\n\n"
        'Respond with ```json\n{"decision": "advance", "critique": "..."}\n```',
        encoding="utf-8",
    )
    (default_dir / "revise.prompt.md").write_text(
        "# Revise Agent\n\nRevise this:\n{{CONTENT}}\n\n"
        'Revised text here.\n\n```json\n{"decision": "advance", "critique": "..."}\n```',
        encoding="utf-8",
    )

    return agents_dir


@pytest.fixture
def sample_piece(tmp_output):
    """Create a sample piece in directory format and return its path."""
    piece_dir = tmp_output / "test-piece"
    piece_dir.mkdir()

    meta = {
        "id": "test-piece",
        "title": "Test Piece",
        "genre": "fiction",
        "type": "story",
        "audience": "general",
        "tone": "casual",
        "language": "en",
        "target_length": "1000 words",
        "constraints": ["must have a twist"],
        "current_stage": "draft",
        "created": "2026-01-01",
        "updated": "2026-01-01",
        "agent_set": "default",
    }
    (piece_dir / "meta.yaml").write_text(
        yaml.dump(meta, default_flow_style=False, sort_keys=False), encoding="utf-8"
    )

    # Brief
    (piece_dir / "brief.md").write_text(
        "---\nid: test-piece\ntitle: Test Piece\ncurrent_stage: brief\n---\n\nThis is the brief.",
        encoding="utf-8",
    )

    # Draft
    (piece_dir / "draft.md").write_text(
        "---\nid: test-piece\ntitle: Test Piece\ncurrent_stage: draft\n---\n\nThis is the draft content. It needs work.",
        encoding="utf-8",
    )

    return piece_dir


@pytest.fixture
def sample_piece_with_review(sample_piece):
    """Sample piece that also has a review file."""
    review_content = "The draft needs a stronger opening and better pacing."
    (sample_piece / "review.md").write_text(review_content, encoding="utf-8")
    return sample_piece
