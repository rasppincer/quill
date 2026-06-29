"""Step definitions for orchestrator.feature."""

import json
from pathlib import Path

import yaml
from behave import given, when, then, use_step_matcher

use_step_matcher("parse")

OUTPUT_DIR = Path.home() / "projects" / "quill" / "output"


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


def write_stage_file(piece_id, stage, content):
    """Write content to a stage file directly on disk."""
    from quill.piece import _stage_filename
    stage_dir = OUTPUT_DIR / piece_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / _stage_filename(stage)
    path.write_text(content, encoding="utf-8")


@given('the piece has structure with {n:d} segments')
def step_has_structure(context, n):
    """Write a structure.md file with N segment headers."""
    pid = context.piece_id
    segments = "\n".join(f"## Segment {i+1}: Chapter {i+1}" for i in range(n))
    write_stage_file(pid, "structure", segments)


@given("the piece has outline and brief content")
def step_has_outline_and_brief(context):
    """Write outline and brief content for the piece."""
    pid = context.piece_id
    write_stage_file(pid, "brief", "# Brief\n\nA test story about a heist gone wrong.")
    write_stage_file(pid, "outline", "# Outline\n\n## Part 1: Setup\nThe team assembles.\n## Part 2: Conflict\nThings go wrong.\n## Part 3: Resolution\nEscape.")


@when('I run the orchestrator for stage "{stage}" with agent set "{agent_set}"')
def step_run_orchestrator(context, stage, agent_set):
    """Run the orchestrator via the API."""
    resp = api(context, "post", f"/api/pieces/{context.piece_id}/run",
               json={"stage": stage, "agent_set": agent_set, "chain": False})
    context.response_json = resp.get_json() if resp.status_code == 200 else {"error": resp.get_json().get("error", "unknown")}


@then('the piece "{piece_id}" has {n:d} children')
def step_has_children(context, piece_id, n):
    """Verify a piece has N children."""
    resp = api(context, "get", f"/api/pieces/{piece_id}")
    data = resp.json()
    children = data.get("children", [])
    assert len(children) == n, f"Expected {n} children, got {len(children)}: {children}"


@then('each child has a parent field pointing to "{parent_id}"')
def step_children_have_parent(context, parent_id):
    """Verify each child piece has the correct parent field."""
    resp = api(context, "get", f"/api/pieces/{parent_id}")
    parent_data = resp.json()
    children = parent_data.get("children", [])
    for child_id in children:
        resp = api(context, "get", f"/api/pieces/{child_id}")
        child_data = resp.json()
        assert child_data.get("parent") == parent_id, \
            f"Child {child_id} has parent '{child_data.get('parent')}', expected '{parent_id}'"
