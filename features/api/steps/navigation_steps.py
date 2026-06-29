"""Step definitions for pipeline navigation and stage lifecycle tests."""
import json
import time
from pathlib import Path

import yaml
from behave import given, when, then, use_step_matcher

use_step_matcher("parse")

OUTPUT_DIR = Path.home() / "projects" / "quill" / "output"


# ---------------------------------------------------------------------------
# Helpers (reuse from pieces_steps where possible)
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


def read_meta(piece_id):
    """Read meta.yaml for a piece."""
    meta_path = OUTPUT_DIR / piece_id / "meta.yaml"
    return yaml.safe_load(meta_path.read_text()) if meta_path.exists() else {}


def write_stage_file(piece_id, stage, content):
    """Write content to a stage file directly on disk."""
    from quill.piece import _stage_filename
    stage_dir = OUTPUT_DIR / piece_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / _stage_filename(stage)
    path.write_text(content, encoding="utf-8")


def write_stage_with_frontmatter(piece_id, stage, body, title=None):
    """Write a stage file with YAML frontmatter."""
    from quill.piece import _stage_filename
    stage_dir = OUTPUT_DIR / piece_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    meta_path = stage_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text()) if meta_path.exists() else {}
    if title:
        meta["title"] = title
    fm = yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False)
    path = stage_dir / _stage_filename(stage)
    path.write_text(f"---\n{fm}---\n\n{body}", encoding="utf-8")


def create_piece_with_trigger(context, piece_id, stage, trigger="on_advance"):
    """Create a piece via API, set its stage and trigger."""
    title = piece_id.replace("-", " ").title()
    data = {"title": title, "genre": "fiction", "type": "story", "audience": "test",
            "tone": "neutral", "language": "en", "target_length": "1000"}
    resp = api(context, "post", "/api/pieces", json=data)
    assert resp.status_code == 201, f"Failed to create piece: {resp.text}"
    pid = context.response_json["id"]
    context.created_pieces.append(pid)
    context.piece_id = pid

    # Write stage files for stages BEFORE the target (not including it)
    stages = ["brief", "outline", "research", "draft", "review", "revise",
              "humanize", "validate", "polish", "done"]
    for s in stages:
        if s == stage:
            break
        write_stage_file(pid, s, f"Content for {s} stage of {title}")

    # Set stage in meta.yaml
    meta_path = OUTPUT_DIR / pid / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text()) or {}
    meta["current_stage"] = stage
    meta["trigger"] = trigger
    # Initialize stage_states for stages up to target
    if "stage_states" not in meta:
        meta["stage_states"] = {}
    for s in stages:
        meta["stage_states"][s] = "ready"
        if s == stage:
            break
    meta_path.write_text(
        yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return pid


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------

@given('a piece "{piece_id}" at stage "{stage}" with trigger "{trigger}"')
def step_piece_at_stage_with_trigger(context, piece_id, stage, trigger):
    pid = create_piece_with_trigger(context, piece_id, stage, trigger)
    context.piece_id = pid


@given("the piece has brief.md content")
def step_has_brief_content(context):
    write_stage_file(context.piece_id, "brief", "# Brief\n\nA story about testing pipeline navigation.")


@given("the piece has content in brief and outline stages")
def step_has_brief_outline(context):
    write_stage_file(context.piece_id, "brief", "# Brief\n\nA brief.")
    write_stage_file(context.piece_id, "outline", "# Outline\n\nSection 1.\nSection 2.\nSection 3.")


@given("the piece has content in brief, outline, and draft stages")
def step_has_brief_outline_draft(context):
    write_stage_file(context.piece_id, "brief", "# Brief\n\nA brief.")
    write_stage_file(context.piece_id, "outline", "# Outline\n\nSection 1.\nSection 2.")
    write_stage_file(context.piece_id, "draft", "# Draft\n\nThe story begins here with a compelling opening.")


@given("the piece has content in all stages through polish")
def step_has_all_content(context):
    for stage in ["brief", "outline", "research", "draft", "review", "revise",
                  "humanize", "validate", "polish"]:
        write_stage_file(context.piece_id, stage, f"# {stage.title()}\n\nContent for {stage}.")


@given("the piece has outline.md and research.md content")
def step_has_outline_research(context):
    write_stage_file(context.piece_id, "outline", "# Outline\n\nSection 1.\nSection 2.")
    write_stage_file(context.piece_id, "research", "# Research\n\nSource 1.\nSource 2.")


@given("the piece has brief.md and outline.md content")
def step_has_brief_and_outline(context):
    write_stage_file(context.piece_id, "brief", "# Brief\n\nA brief.")
    write_stage_file(context.piece_id, "outline", "# Outline\n\nSection 1.\nSection 2.")


@given("the piece has outline.md content")
def step_has_outline(context):
    write_stage_file(context.piece_id, "outline", "# Outline\n\nSection 1.\nSection 2.")


@given("the outline.md has auto-generated content")
def step_outline_auto_generated(context):
    write_stage_file(context.piece_id, "outline", "# Outline (auto-generated)\n\nSection 1.\nSection 2.\nSection 3.")


@given("the agent evaluate call will reject on first attempt then accept")
def step_evaluate_reject_then_accept(context):
    """Store flag for mocking — the step definition in run will configure the mock."""
    context.evaluate_reject_first = True


@given("the agent flavor has max_loops {n:d}")
def step_set_max_loops(context, n):
    """Set max_loops for the current agent set."""
    context.max_loops_override = n


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------

@when('I navigate to stage "{stage}"')
def step_navigate_to_stage(context, stage):
    api(context, "get", f"/api/pieces/{context.piece_id}/stages/{stage}")


@when('I set the piece trigger to "{trigger}"')
def step_set_trigger(context, trigger):
    api(context, "post", f"/api/pieces/{context.piece_id}/trigger",
        json={"trigger": trigger})


@when('I set piece "{piece_id}" trigger to "{trigger}"')
def step_set_piece_trigger(context, piece_id, trigger):
    api(context, "post", f"/api/pieces/{piece_id}/trigger",
        json={"trigger": trigger})


@when("I start the auto pipeline")
def step_start_auto(context):
    api(context, "post", f"/api/pieces/{context.piece_id}/auto")
    if context.response_json and "run_id" in context.response_json:
        context.auto_run_id = context.response_json["run_id"]


@when("I clear the brief content")
def step_clear_brief(context):
    from quill.piece import _stage_filename
    brief_file = OUTPUT_DIR / context.piece_id / _stage_filename("brief")
    # Write frontmatter with empty body
    meta = read_meta(context.piece_id)
    fm = yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False)
    brief_file.write_text(f"---\n{fm}---\n", encoding="utf-8")


@when('I wait until the piece reaches stage "{stage}"')
def step_wait_until_stage(context, stage):
    """Poll the piece until it reaches the target stage (max 60s)."""
    start = time.time()
    timeout = 60
    while time.time() - start < timeout:
        resp = api(context, "get", f"/api/pieces/{context.piece_id}")
        if resp.status_code == 200:
            current = context.response_json.get("current_stage", "")
            # Compare stage indices — reached means >= target
            pipeline_stages = ["brief", "outline", "research", "draft", "review",
                               "revise", "humanize", "validate", "polish", "done"]
            if current in pipeline_stages and stage in pipeline_stages:
                if pipeline_stages.index(current) >= pipeline_stages.index(stage):
                    return
        time.sleep(2)
    assert False, f"Piece did not reach stage '{stage}' within {timeout}s"


@when("I attempt to run the agent for stage \"{stage}\"")
def step_attempt_run_agent(context, stage):
    api(context, "post", f"/api/pieces/{context.piece_id}/run",
        json={"stage": stage})


@when("I interrupt the auto pipeline")
def step_interrupt(context):
    api(context, "post", f"/api/pieces/{context.piece_id}/interrupt")


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------

@then('stage "{stage}" has state "{expected_state}"')
def step_check_stage_state(context, stage, expected_state):
    meta = read_meta(context.piece_id)
    actual = meta.get("stage_states", {}).get(stage, "empty")
    assert actual == expected_state, (
        f"Stage '{stage}' state is '{actual}', expected '{expected_state}'"
    )


@then('the stage content for "{stage}" is returned')
def step_check_stage_content(context, stage):
    assert context.response_json is not None, "No response JSON"
    content = context.response_json.get("content", "")
    assert content.strip(), f"Stage '{stage}' content is empty"
    context.stage_content = content


@then('the stage metrics for "{stage}" are returned')
def step_check_stage_metrics(context, stage):
    assert context.response_json is not None, "No response JSON"
    # Metrics may be null for stages without enough content
    # Just verify the key exists
    assert "metrics" in context.response_json, "No 'metrics' in response"


@then('the piece trigger is "{expected_trigger}"')
def step_check_piece_trigger(context, expected_trigger):
    resp = api(context, "get", f"/api/pieces/{context.piece_id}")
    assert resp.status_code == 200
    actual = context.response_json.get("trigger", "")
    assert actual == expected_trigger, (
        f"Piece trigger is '{actual}', expected '{expected_trigger}'"
    )


@then('piece "{piece_id}" trigger is "{expected_trigger}"')
def step_check_specific_piece_trigger(context, piece_id, expected_trigger):
    resp = api(context, "get", f"/api/pieces/{piece_id}")
    assert resp.status_code == 200
    actual = context.response_json.get("trigger", "")
    assert actual == expected_trigger, (
        f"Piece '{piece_id}' trigger is '{actual}', expected '{expected_trigger}'"
    )


@then('no agent output exists for stage "{stage}"')
def step_no_agent_output(context, stage):
    from quill.piece import _stage_filename, _FRONTMATTER_RE
    path = OUTPUT_DIR / context.piece_id / _stage_filename(stage)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        body = text[m.end():] if m else text
        assert body.strip() == "", f"Stage '{stage}' has unexpected body content: {body[:100]}"


@then("the draft.md file is empty or missing")
def step_draft_empty_or_missing(context):
    from quill.piece import _stage_filename
    path = OUTPUT_DIR / context.piece_id / _stage_filename("draft")
    if path.exists():
        content = path.read_text().strip()
        assert content == "", f"draft.md is not empty: {content[:100]}"


@then("the outline.md file has content")
def step_outline_has_content(context):
    from quill.piece import _stage_filename
    path = OUTPUT_DIR / context.piece_id / _stage_filename("outline")
    assert path.exists(), "outline.md does not exist"
    content = path.read_text().strip()
    assert len(content) > 0, "outline.md is empty"


@then("the draft.md file has content")
def step_draft_has_content(context):
    from quill.piece import _stage_filename
    path = OUTPUT_DIR / context.piece_id / _stage_filename("draft")
    assert path.exists(), "draft.md does not exist"
    content = path.read_text().strip()
    assert len(content) > 0, "draft.md is empty"


@then('the run log records state "{state}" for stage "{stage}"')
def step_run_log_state(context, state, stage):
    log_file = OUTPUT_DIR / context.piece_id / "run-log.jsonl"
    assert log_file.exists(), "run-log.jsonl does not exist"
    entries = [json.loads(line) for line in log_file.read_text().strip().split("\n") if line]
    state_entries = [e for e in entries
                     if e.get("call") == "state_transition"
                     and e.get("state") == state
                     and e.get("stage") == stage]
    assert len(state_entries) >= 1, (
        f"No state_transition entry for stage '{stage}' state '{state}'. "
        f"Entries: {[e for e in entries if e.get('call') == 'state_transition']}"
    )


@then('the run log shows an inner evaluate "{decision}" for stage "{stage}"')
def step_run_log_inner_evaluate(context, decision, stage):
    log_file = OUTPUT_DIR / context.piece_id / "run-log.jsonl"
    assert log_file.exists(), "run-log.jsonl does not exist"
    entries = [json.loads(line) for line in log_file.read_text().strip().split("\n") if line]
    eval_entries = [e for e in entries
                    if e.get("call") == "evaluate"
                    and e.get("stage") == stage
                    and e.get("decision") == decision]
    assert len(eval_entries) >= 1, (
        f"No evaluate entry with decision '{decision}' for stage '{stage}'. "
        f"Evaluate entries: {[e for e in entries if e.get('call') == 'evaluate']}"
    )


@then('the run log shows {n:d} generate calls for stage "{stage}"')
def step_run_log_generate_count(context, n, stage):
    log_file = OUTPUT_DIR / context.piece_id / "run-log.jsonl"
    assert log_file.exists(), "run-log.jsonl does not exist"
    entries = [json.loads(line) for line in log_file.read_text().strip().split("\n") if line]
    gen_entries = [e for e in entries
                   if e.get("call") == "generate"
                   and e.get("stage") == stage]
    assert len(gen_entries) == n, (
        f"Expected {n} generate calls for stage '{stage}', got {len(gen_entries)}"
    )


@then('all content stages have state "ready"')
def step_all_content_ready(context):
    meta = read_meta(context.piece_id)
    content_stages = ["outline", "draft", "revise", "humanize", "polish"]
    stage_states = meta.get("stage_states", {})
    for stage in content_stages:
        actual = stage_states.get(stage, "empty")
        assert actual == "ready", (
            f"Content stage '{stage}' state is '{actual}', expected 'ready'"
        )


@then("the pipeline stops after the current stage completes")
def step_pipeline_stopped(context):
    """Verify the piece is not at 'done' — it stopped somewhere before."""
    resp = api(context, "get", f"/api/pieces/{context.piece_id}")
    assert resp.status_code == 200
    current = context.response_json.get("current_stage", "")
    assert current != "done", "Pipeline reached 'done' — expected it to stop earlier"
