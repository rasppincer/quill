"""Step definitions for piece lifecycle tests."""
import json
import os
import shutil
import time
from pathlib import Path

import yaml
from behave import given, when, then, use_step_matcher

use_step_matcher("parse")

OUTPUT_DIR = Path.home() / "projects" / "quill" / "output"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api(context, method, path, **kwargs):
    """Make an API call and store the response."""
    import requests
    url = f"{context.api_base}{path}"
    resp = getattr(requests, method)(url, **kwargs)
    context.response = resp
    try:
        context.response_json = resp.json()
    except Exception:
        context.response_json = None
    return resp


def create_piece_via_api(context, title, genre="fiction", **extra):
    """Create a piece and return its ID."""
    data = {"title": title, "genre": genre, "type": "story", "audience": "test",
            "tone": "neutral", "language": "en", "target_length": "1000"}
    data.update(extra)
    resp = api(context, "post", "/api/pieces", json=data)
    assert resp.status_code == 201, f"Failed to create piece: {resp.text}"
    piece_id = context.response_json["id"]
    context.created_pieces.append(piece_id)
    context.piece_id = piece_id
    return piece_id


def write_stage_file(piece_id, stage, content, with_frontmatter=False, title=None):
    """Write content to a stage file directly on disk."""
    stage_dir = OUTPUT_DIR / piece_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / f"{stage}.md"
    if with_frontmatter:
        meta_path = stage_dir / "meta.yaml"
        if meta_path.exists():
            meta = yaml.safe_load(meta_path.read_text()) or {}
        else:
            meta = {}
        if title:
            meta["title"] = title
        fm = yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False)
        path.write_text(f"---\n{fm}---\n\n{content}", encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")


def set_piece_stage(piece_id, stage):
    """Directly update meta.yaml to set the current stage."""
    meta_path = OUTPUT_DIR / piece_id / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text()) or {}
    meta["current_stage"] = stage
    meta_path.write_text(
        yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def read_meta(piece_id):
    """Read meta.yaml for a piece."""
    meta_path = OUTPUT_DIR / piece_id / "meta.yaml"
    return yaml.safe_load(meta_path.read_text()) if meta_path.exists() else {}


def read_stage_file(piece_id, stage):
    """Read raw content of a stage file."""
    path = OUTPUT_DIR / piece_id / f"{stage}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------

@given("a clean Quill instance")
def step_clean_instance(context):
    """Verify the API is reachable."""
    resp = api(context, "get", "/health")
    assert resp.status_code == 200, f"Quill API not reachable: {resp.status_code}"


@given('a piece "{piece_id}" at stage "{stage}"')
def step_piece_at_stage(context, piece_id, stage):
    """Create a piece and set it to the given stage."""
    title = piece_id.replace("-", " ").title()
    pid = create_piece_via_api(context, title)
    # The API returns a slugified ID — use it
    context.piece_id = pid
    # Write stage files up to AND including the target stage
    stages = ["brief", "outline", "draft", "review", "revise", "humanize", "validate", "polish", "done"]
    for s in stages:
        write_stage_file(pid, s, f"Content for {s} stage of {title}")
        if s == stage:
            break
    # Set the stage directly in meta.yaml
    set_piece_stage(pid, stage)
    context.piece_id = pid


@given('a piece "{piece_id}" exists')
def step_piece_exists(context, piece_id):
    """Ensure a piece exists."""
    title = piece_id.replace("-", " ").title()
    pid = create_piece_via_api(context, title)
    context.piece_id = pid


@given('the piece has outline.md and draft.md content')
def step_has_outline_draft(context):
    """Write outline and draft stage files."""
    pid = context.piece_id
    write_stage_file(pid, "outline", "# Outline\n\n## Section 1\nSetup\n## Section 2\nConflict\n## Section 3\nResolution")
    write_stage_file(pid, "draft", "# Draft\n\nThe story begins in a quiet lab. Dr. Aris stared at the data, confused by what he saw.")


@given('the piece has draft.md content')
def step_has_draft(context):
    """Write a draft stage file with enough content for agents to review."""
    pid = context.piece_id
    draft = """# The Test Story

Dr. Aris Thorne stared at the monitor, his coffee growing cold beside him. The data streams
were wrong. Not corrupted—wrong in a way that suggested something deeper, something that
challenged everything he thought he knew about cellular intelligence.

"Look at this pattern," he said to Lena, who was examining the tissue culture under the
microscope. "The bioelectric signals are coordinating across the entire specimen. No single
cell is driving the pattern—it's emergent."

Lena looked up, her eyes widening. "That's not possible without a central nervous system."

"And yet," Aris said, pointing at the screen, "there it is. The cells are solving problems
together. Problems that no individual cell could solve alone."

The implications were staggering. If non-neural tissue could exhibit collective intelligence,
then everything they thought they knew about cognition was wrong. Intelligence wasn't about
neurons—it was about goals. About the ability to pursue outcomes even when circumstances changed.

"We need to test this," Lena said, already reaching for the pipette. "If we present them with
a novel problem—one they've never encountered—can they adapt?"

Aris nodded, feeling the familiar thrill of discovery mixed with something new: humility. His
life's work had been built on the assumption that intelligence required complexity. But what if
the simplest systems, given the right conditions, could exhibit the same problem-solving
abilities he'd attributed only to the brain?

The tissue culture glowed faintly green under the sensors, its bioelectric patterns pulsing
with an almost rhythmic certainty. Whatever was happening in that petri dish, it was alive
in a way they hadn't imagined possible.
"""
    write_stage_file(pid, "draft", draft)


@given('the review.md has runner-style content without frontmatter')
def step_runner_content(context):
    """Write review.md without frontmatter (as the runner does)."""
    pid = context.piece_id
    write_stage_file(pid, "review", "This is a review critique written by the runner.\nNo frontmatter here.", with_frontmatter=False)


@given('a piece "{piece_id}" with content in stage files')
def step_piece_with_content(context, piece_id):
    """Create a piece with content in stage files."""
    title = piece_id.replace("-", " ").title()
    pid = create_piece_via_api(context, title)
    context.piece_id = pid
    write_stage_file(pid, "brief", "# Brief\n\nA story about testing.")
    set_piece_stage(pid, "brief")


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------

@when('I create a piece with title "{title}" and genre "{genre}"')
def step_create_piece(context, title, genre):
    """Create a piece. Don't assert on status — some tests expect failure."""
    import requests
    data = {"title": title, "genre": genre, "type": "story", "audience": "test",
            "tone": "neutral", "language": "en", "target_length": "1000"}
    resp = requests.post(f"{context.api_base}/api/pieces", json=data)
    context.response = resp
    try:
        context.response_json = resp.json()
    except Exception:
        context.response_json = None
    if resp.status_code == 201:
        context.piece_id = context.response_json["id"]
        context.created_pieces.append(context.piece_id)


@when("I advance the piece")
def step_advance(context):
    api(context, "post", f"/api/pieces/{context.piece_id}/advance")


@when('I rename the piece to "{new_title}"')
def step_rename(context, new_title):
    api(context, "post", f"/api/pieces/{context.piece_id}/rename",
        json={"title": new_title})
    context.new_title = new_title


@when('I reject the piece to stage "{stage}"')
def step_reject(context, stage):
    api(context, "post", f"/api/pieces/{context.piece_id}/reject",
        json={"target": stage})


@when("I fetch the piece detail")
def step_fetch_detail(context):
    api(context, "get", f"/api/pieces/{context.piece_id}")


@when('I run the agent chain from "{stage}" with agent set "{agent_set}"')
def step_run_chain(context, stage, agent_set):
    api(context, "post", f"/api/pieces/{context.piece_id}/run",
        json={"chain": True, "stage": stage, "agent_set": agent_set})


@when('I run the agent for stage "{stage}" with agent set "{agent_set}"')
def step_run_agent(context, stage, agent_set):
    api(context, "post", f"/api/pieces/{context.piece_id}/run",
        json={"stage": stage, "agent_set": agent_set})


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------

@then('the piece "{piece_id}" exists')
def step_check_exists(context, piece_id):
    # The API slugifies titles, so check the actual piece
    resp = api(context, "get", f"/api/pieces/{context.piece_id}")
    assert resp.status_code == 200, f"Piece not found: {resp.text}"


@then('the piece is at stage "{stage}"')
@then('the piece is still at stage "{stage}"')
def step_check_stage(context, stage):
    resp = api(context, "get", f"/api/pieces/{context.piece_id}")
    assert resp.status_code == 200
    actual = context.response_json["current_stage"]
    assert actual == stage, f"Expected stage '{stage}', got '{actual}'"


@then('the piece title is "{title}"')
def step_check_title(context, title):
    resp = api(context, "get", f"/api/pieces/{context.piece_id}")
    assert resp.status_code == 200
    actual = context.response_json["title"]
    assert actual == title, f"Expected title '{title}', got '{actual}'"


@then('the meta.yaml has current_stage "{stage}"')
def step_check_meta_stage(context, stage):
    meta = read_meta(context.piece_id)
    actual = meta.get("current_stage")
    assert actual == stage, f"Expected meta current_stage '{stage}', got '{actual}'"


@then("the stage file content is preserved")
def step_check_content_preserved(context):
    """Verify the stage file wasn't overwritten by rename."""
    meta = read_meta(context.piece_id)
    stage = meta.get("current_stage")
    content = read_stage_file(context.piece_id, stage)
    # Content should exist and not be just frontmatter
    assert content.strip(), f"Stage file {stage}.md is empty after rename"
    # If it had no frontmatter before, it should still have no frontmatter
    # (runner-written files don't have frontmatter)


@then("the review.md still has no frontmatter")
def step_review_no_frontmatter(context):
    content = read_stage_file(context.piece_id, "review")
    assert not content.startswith("---"), "review.md unexpectedly has frontmatter after rename"


@then('the meta.yaml has the new title "{title}"')
def step_meta_has_title(context, title):
    meta = read_meta(context.piece_id)
    actual = meta.get("title")
    assert actual == title, f"Expected meta title '{title}', got '{actual}'"


@then('I get an error containing "{text}"')
def step_check_error(context, text):
    assert context.response_json is not None, "No response JSON"
    error = context.response_json.get("error", "")
    assert text in error, f"Expected error containing '{text}', got: {error}"


@then("the body_length is greater than 0")
def step_body_length(context):
    assert context.response_json is not None
    bl = context.response_json.get("body_length", 0)
    assert bl > 0, f"Expected body_length > 0, got {bl}"


@then("the body is not empty")
def step_body_not_empty(context):
    assert context.response_json is not None
    body = context.response_json.get("body", "")
    assert body.strip(), "Body is empty"


@then('the chain skips "{stages}"')
def step_chain_skips(context, stages):
    """Verify that certain stages were skipped in the chain results."""
    results = context.response_json.get("results", [])
    ran_stages = [r["stage"] for r in results]
    for stage in stages.split(", "):
        stage = stage.strip().strip('"')
        assert stage not in ran_stages, f"Expected '{stage}' to be skipped, but it ran"


@then('the chain runs "{stages}"')
def step_chain_runs(context, stages):
    """Verify that certain stages ran in the chain."""
    results = context.response_json.get("results", [])
    ran_stages = [r["stage"] for r in results]
    for stage in stages.split(", "):
        stage = stage.strip().strip('"')
        assert stage in ran_stages, f"Expected '{stage}' to run, but it wasn't in results: {ran_stages}"


@then('the piece reaches stage "{stage}"')
def step_reaches_stage(context, stage):
    resp = api(context, "get", f"/api/pieces/{context.piece_id}")
    assert resp.status_code == 200
    actual = context.response_json["current_stage"]
    assert actual == stage, f"Expected piece to reach '{stage}', but it's at '{actual}'"


@then("I get an error about no agent prompts")
def step_no_agent_error(context):
    assert context.response_json is not None
    error = context.response_json.get("error", "") or ""
    results = context.response_json.get("results", [])
    # Either a direct error or results with all errors
    has_error = "no agent" in error.lower() or "no prompt" in error.lower()
    has_error = has_error or any(r.get("error") for r in results)
    assert has_error, f"Expected error about no agent prompts, got: {context.response_json}"


@then('the review.md contains clean markdown critique')
def step_review_clean(context):
    content = read_stage_file(context.piece_id, "review")
    assert content.strip(), "review.md is empty"
    # Should not be wrapped in JSON
    assert not content.strip().startswith("```json"), "review.md starts with JSON code fence"


@then('the review.md has no JSON code fences')
def step_no_json_fences(context):
    content = read_stage_file(context.piece_id, "review")
    assert "```json" not in content, "review.md contains JSON code fences"


@then('the review.md does not contain "{text}"')
@then('the review.md does not contain the string "{text}"')
def step_review_not_contains(context, text):
    content = read_stage_file(context.piece_id, "review")
    assert text not in content, f"review.md contains forbidden text: '{text}'"


@then("the review.md does not contain JSON decision block")
def step_no_json_decision(context):
    content = read_stage_file(context.piece_id, "review")
    assert '"decision":' not in content, "review.md contains JSON decision block"
    assert '"decision" :' not in content, "review.md contains JSON decision block"
