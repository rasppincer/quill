"""Phase 2b Task 1: read_inputs must not inject loop artefacts for any loop_count.

The old two-call engine appended <stage>.md and <stage>.decision.md to
{{CONTENT}} whenever loop_count > 0.  Under the single-call PIVOT design that
block is dead and must be removed.
"""

import yaml
import pytest
from quill.context_assembler import ContextAssembler
from quill.pipeline import load_pipeline
from quill.piece import load_piece, _stage_filename


@pytest.fixture
def piece_with_stale_loop(tmp_output):
    """A piece directory with loops.structure: 1 and the artefacts the old
    engine would have written — these must NOT appear in read_inputs output."""
    piece_dir = tmp_output / "loop-test"
    piece_dir.mkdir()

    meta = {
        "id": "loop-test",
        "title": "Loop Test",
        "genre": "non-fiction",
        "type": "editorial",
        "audience": "engineers",
        "tone": "technical",
        "language": "en",
        "target_length": "900",
        "constraints": [],
        "current_stage": "structure",
        "created": "2026-01-01",
        "updated": "2026-01-01",
        "agent_set": "",
        "loops": {"structure": 1},
    }
    (piece_dir / "meta.yaml").write_text(
        yaml.dump(meta, default_flow_style=False, sort_keys=False), encoding="utf-8"
    )

    # Files are flat in the piece directory (stage_dir() == piece_dir)
    # brief — the legitimate declared input for structure
    (piece_dir / _stage_filename("brief")).write_text(
        "BRIEF CONTENT", encoding="utf-8"
    )

    # structure — previous attempt artefact (must NOT appear in content)
    (piece_dir / _stage_filename("structure")).write_text(
        "PREVIOUS STRUCTURE ATTEMPT", encoding="utf-8"
    )

    # structure.decision.md — old evaluator artefact (must NOT appear in content)
    (piece_dir / _stage_filename("structure", ".decision.md")).write_text(
        "DECISION CRITIQUE CONTENT", encoding="utf-8"
    )

    return piece_dir


def test_read_inputs_does_not_inject_loop_artefacts(piece_with_stale_loop, monkeypatch):
    """read_inputs for structure must only include brief.md, regardless of loop_count."""
    monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", piece_with_stale_loop.parent)
    pipeline = load_pipeline("default")
    piece = load_piece(piece_with_stale_loop)

    assembler = ContextAssembler()
    result = assembler.read_inputs(piece, "structure", pipeline, loop_count=1)

    assert "BRIEF CONTENT" in result, "Expected brief content in read_inputs output"
    assert "PREVIOUS STRUCTURE ATTEMPT" not in result, (
        "read_inputs injected the previous structure attempt — loop-back block not removed"
    )
    assert "DECISION CRITIQUE CONTENT" not in result, (
        "read_inputs injected the decision critique — loop-back block not removed"
    )


def test_read_inputs_resolves_looped_inputs(tmp_path):
    from quill.piece import Piece
    from quill.context_assembler import ContextAssembler
    from quill.pipeline import Pipeline, Stage

    # Setup a dummy piece with loops
    piece = Piece(id="test_piece")
    piece._path = tmp_path

    # Write a loop count mapping to yaml instead of database mocking
    meta_path = tmp_path / "meta.yaml"
    meta_path.write_text("loops:\n  revise: 3\n  draft: 0\n")

    # Write the stage files on disk
    (tmp_path / "08_revise.L3.md").write_text("---\ntitle: Test\n---\nLooped revise content")

    pipeline = Pipeline(
        name="default",
        stage_inputs={"humanize": ["revise.md"]},
        stages={"humanize": Stage(key="humanize", name="Humanize")}
    )

    assembler = ContextAssembler()
    content = assembler.read_inputs(piece, "humanize", pipeline)
    assert "Looped revise content" in content

