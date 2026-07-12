# Design Spec: Prefix Agent Prompts for Order Matching Execution

## Goal
Rename the agent prompt templates under `agents/` directories to include numeric prefixes (e.g., `05_draft.prompt.md`, `00_chapter_brief.prompt.md`). This aligns their sorted alphabetical order on disk with the execution order in the pipeline.

## Proposed Naming Scheme
We will prefix the stage prompt template files in each agent set (`default`, `fiction`, `non-fiction`) using the pipeline index of each stage from `workflows/default.yaml`:

- `chapter_brief.prompt.md` $\rightarrow$ `00_chapter_brief.prompt.md`
- `structure.prompt.md` $\rightarrow$ `02_structure.prompt.md`
- `outline.prompt.md` $\rightarrow$ `03_outline.prompt.md`
- `draft.prompt.md` $\rightarrow$ `05_draft.prompt.md`
- `review.prompt.md` $\rightarrow$ `06_review.prompt.md`
- `review_decision.prompt.md` $\rightarrow$ `07_review_decision.prompt.md`
- `revise.prompt.md` $\rightarrow$ `08_revise.prompt.md`
- `humanize.prompt.md` $\rightarrow$ `09_humanize.prompt.md`
- `validate.prompt.md` $\rightarrow$ `10_validate.prompt.md`
- `validate_decision.prompt.md` $\rightarrow$ `11_validate_decision.prompt.md`
- `polish.prompt.md` $\rightarrow$ `12_polish.prompt.md`
- `state.prompt.md` $\rightarrow$ `13_state.prompt.md`
- `evaluate.prompt.md` $\rightarrow$ `evaluate.prompt.md` (remains as-is, since it has no stage matching it in `stage_order` and is a global template)

## Code Changes

### `src/quill/agent.py`
- Define `get_prompt_filename(stage: str) -> str` to handle stage-to-filename resolution.
- Modify `load_agent_config` to load template from `config_dir / get_prompt_filename(stage)`.
- Modify `list_agent_prompts` to strip the numeric prefix (e.g., `05_draft` $\rightarrow$ `draft`) so the code interacts with stages using their clean keys, but return `filename` in the dict payload.

### `src/quill/orchestrator.py`
- Modify `_generate_chapter_brief` to load template from `get_prompt_filename("chapter_brief")`.

### `src/quill/blueprints/agents.py`
- Modify endpoints (`agents_for_stage`, `agents_get_prompt`, and `agents_update_prompt`) to resolve file paths using `get_prompt_filename(stage)`.

### `src/quill/static/js/agents.js`
- Modify the display logic to render the actual template filename instead of `<stage>.prompt.md`.

### `tests/`
- Update `tests/conftest.py` to create the mock agent templates with their corresponding prefixes.
- Update `tests/test_agent.py`, `tests/test_app.py`, `tests/test_async.py`, and `tests/test_orchestrator.py` to use prefixed names when creating/checking/asserting prompt files.

## Verification Plan
1. Run all unit tests using `pytest` to verify prompt loading and mock file configurations are correct.
2. Manually verify the web UI displays the new prefixed files correctly.
