"""Step definitions for research stage tests."""
import yaml
from pathlib import Path
from behave import given, when, then, use_step_matcher

use_step_matcher("parse")

WORKFLOWS_DIR = Path.home() / "projects" / "quill" / "workflows"
AGENTS_DIR = Path.home() / "projects" / "quill" / "agents"


@when('I query the pipeline info')
def step_query_pipeline(context):
    import requests
    resp = requests.get(f"{context.api_base}/api/pipeline")
    assert resp.status_code == 200
    context.pipeline_data = resp.json()


@then('the pipeline has {count:d} stages')
def step_pipeline_stage_count(context, count):
    assert len(context.pipeline_data["stages"]) == count


@then('"{stage}" is between "{before}" and "{after}" in the stage order')
def step_stage_between(context, stage, before, after):
    order = [s["key"] for s in context.pipeline_data["stages"]]
    idx_before = order.index(before)
    idx_stage = order.index(stage)
    idx_after = order.index(after)
    assert idx_before < idx_stage < idx_after, \
        f"Expected {before}({idx_before}) < {stage}({idx_stage}) < {after}({idx_after})"


@when('I load the research config for agent set "{agent_set}"')
def step_load_research_config(context, agent_set):
    from quill.agent import load_research_config
    context.research_cfg = load_research_config(agent_set)


@then('research is enabled')
def step_research_enabled(context):
    assert context.research_cfg["enabled"] is True


@then('research is required')
def step_research_required(context):
    assert context.research_cfg["required"] is True


@then('research is not required')
def step_research_not_required(context):
    assert context.research_cfg["required"] is False


@given('the pipeline stage_inputs configuration')
def step_load_stage_inputs(context):
    data = yaml.safe_load((WORKFLOWS_DIR / "default.yaml").read_text())
    context.stage_inputs = data.get("stage_inputs", {})


@then('"{stage}" stage inputs include "{filename}"')
def step_stage_inputs_include(context, stage, filename):
    assert stage in context.stage_inputs, f"No stage_inputs for '{stage}'"
    assert filename in context.stage_inputs[stage], \
        f"'{filename}' not in {context.stage_inputs[stage]}"
