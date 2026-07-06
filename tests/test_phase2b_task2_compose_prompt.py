"""Phase 2b Task 2: compose_prompt must return a single 'prompt' key, not two-call keys.

Under the single-call PIVOT design every stage is one LLM call.
compose_prompt must return {"prompt": {"system": ..., "user": ..., "char_count": ...}}
for all stages — not the old {"generate": ..., "evaluate": ...} shape.
"""

import yaml
import pytest
from quill.context_assembler import ContextAssembler
from quill.piece import _stage_filename


@pytest.fixture
def piece_for_compose(tmp_output, tmp_agents, monkeypatch):
    """A minimal piece directory with a structure agent prompt, suitable for compose_prompt."""
    monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)
    monkeypatch.setattr("quill.agent.AGENTS_DIR", tmp_agents)
    monkeypatch.setattr("quill.agent.MODEL_CONFIG_FILE", tmp_agents / "model.yaml")

    piece_dir = tmp_output / "compose-test"
    piece_dir.mkdir()

    meta = {
        "id": "compose-test",
        "title": "Compose Test",
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
        "agent_set": "non-fiction",
    }
    (piece_dir / "meta.yaml").write_text(
        yaml.dump(meta, default_flow_style=False, sort_keys=False), encoding="utf-8"
    )
    (piece_dir / _stage_filename("brief")).write_text("Brief content.", encoding="utf-8")

    # Add structure prompt to the non-fiction agent set in tmp_agents
    nonfiction_dir = tmp_agents / "non-fiction"
    (nonfiction_dir / "structure.prompt.md").write_text(
        "# Structure\n\n{{CONTENT}}\n", encoding="utf-8"
    )
    # Ensure config.yaml lists structure
    cfg = yaml.safe_load((nonfiction_dir / "config.yaml").read_text())
    if "structure" not in cfg.get("stages", {}):
        cfg.setdefault("stages", {})["structure"] = {"name": "Structure Agent"}
        (nonfiction_dir / "config.yaml").write_text(
            yaml.dump(cfg, default_flow_style=False), encoding="utf-8"
        )

    return piece_dir


def test_compose_prompt_returns_single_prompt_key(piece_for_compose):
    """compose_prompt must return a 'prompt' key for a content stage (structure)."""
    assembler = ContextAssembler(agent_set="non-fiction")
    result = assembler.compose_prompt("compose-test", "structure")

    assert "error" not in result, f"compose_prompt returned an error: {result.get('error')}"
    assert "prompt" in result, (
        f"Expected 'prompt' key in compose_prompt result, got keys: {list(result.keys())}"
    )
    assert "system" in result["prompt"]
    assert "user" in result["prompt"]
    assert "char_count" in result["prompt"]


def test_compose_prompt_no_two_call_keys(piece_for_compose):
    """compose_prompt must NOT return 'generate', 'evaluate', or 'single_call' keys."""
    assembler = ContextAssembler(agent_set="non-fiction")
    result = assembler.compose_prompt("compose-test", "structure")

    assert "generate" not in result, "compose_prompt still returns old 'generate' key"
    assert "evaluate" not in result, "compose_prompt still returns old 'evaluate' key"
    assert "single_call" not in result, "compose_prompt still returns old 'single_call' key"
    assert "is_content_stage" not in result, (
        "compose_prompt still returns deprecated 'is_content_stage' key"
    )
