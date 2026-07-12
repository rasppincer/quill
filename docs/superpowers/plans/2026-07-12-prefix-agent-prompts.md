# Prefix Agent Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename agent prompt templates under `agents/` directories to include numeric prefixes corresponding to their pipeline execution order, and update the prompt-loading backend/frontend/tests to match.

**Architecture:** We will introduce a helper `get_prompt_filename(stage)` that maps a stage key to its prefixed template filename. The loading logic in the agent manager, orchestrator, and blueprints will call this helper. We'll strip the prefix when parsing directory contents so stage keys remain clean internally.

**Tech Stack:** Python, Flask, GFM, JavaScript

## Global Constraints
- Naming convention: `<prefix>_<stage_name>.prompt.md`
- `chapter_brief` is assigned prefix `00`
- Other stages correspond to indices in `workflows/default.yaml`

---

### Task 1: Rename Existing Prompt Templates
**Files:**
- Modify: `agents/` directories

**Interfaces:**
- Consumes: None
- Produces: Renamed prompt template files on disk

- [ ] **Step 1: Rename templates in agents/default**
  Run the following commands:
  ```bash
  git mv agents/default/chapter_brief.prompt.md agents/default/00_chapter_brief.prompt.md
  git mv agents/default/structure.prompt.md agents/default/02_structure.prompt.md
  git mv agents/default/outline.prompt.md agents/default/03_outline.prompt.md
  git mv agents/default/draft.prompt.md agents/default/05_draft.prompt.md
  git mv agents/default/review.prompt.md agents/default/06_review.prompt.md
  git mv agents/default/review_decision.prompt.md agents/default/07_review_decision.prompt.md
  git mv agents/default/revise.prompt.md agents/default/08_revise.prompt.md
  git mv agents/default/humanize.prompt.md agents/default/09_humanize.prompt.md
  git mv agents/default/validate.prompt.md agents/default/10_validate.prompt.md
  git mv agents/default/validate_decision.prompt.md agents/default/11_validate_decision.prompt.md
  git mv agents/default/polish.prompt.md agents/default/12_polish.prompt.md
  git mv agents/default/state.prompt.md agents/default/13_state.prompt.md
  ```

- [ ] **Step 2: Rename templates in agents/fiction**
  Run the following commands:
  ```bash
  git mv agents/fiction/chapter_brief.prompt.md agents/fiction/00_chapter_brief.prompt.md
  git mv agents/fiction/structure.prompt.md agents/fiction/02_structure.prompt.md
  git mv agents/fiction/outline.prompt.md agents/fiction/03_outline.prompt.md
  git mv agents/fiction/draft.prompt.md agents/fiction/05_draft.prompt.md
  git mv agents/fiction/review.prompt.md agents/fiction/06_review.prompt.md
  git mv agents/fiction/review_decision.prompt.md agents/fiction/07_review_decision.prompt.md
  git mv agents/fiction/revise.prompt.md agents/fiction/08_revise.prompt.md
  git mv agents/fiction/humanize.prompt.md agents/fiction/09_humanize.prompt.md
  git mv agents/fiction/validate.prompt.md agents/fiction/10_validate.prompt.md
  git mv agents/fiction/validate_decision.prompt.md agents/fiction/11_validate_decision.prompt.md
  git mv agents/fiction/polish.prompt.md agents/fiction/12_polish.prompt.md
  git mv agents/fiction/state.prompt.md agents/fiction/13_state.prompt.md
  ```

- [ ] **Step 3: Rename templates in agents/non-fiction**
  Run the following commands:
  ```bash
  git mv agents/non-fiction/chapter_brief.prompt.md agents/non-fiction/00_chapter_brief.prompt.md
  git mv agents/non-fiction/structure.prompt.md agents/non-fiction/02_structure.prompt.md
  git mv agents/non-fiction/outline.prompt.md agents/non-fiction/03_outline.prompt.md
  git mv agents/non-fiction/draft.prompt.md agents/non-fiction/05_draft.prompt.md
  git mv agents/non-fiction/review.prompt.md agents/non-fiction/06_review.prompt.md
  git mv agents/non-fiction/review_decision.prompt.md agents/non-fiction/07_review_decision.prompt.md
  git mv agents/non-fiction/revise.prompt.md agents/non-fiction/08_revise.prompt.md
  git mv agents/non-fiction/humanize.prompt.md agents/non-fiction/09_humanize.prompt.md
  git mv agents/non-fiction/validate.prompt.md agents/non-fiction/10_validate.prompt.md
  git mv agents/non-fiction/validate_decision.prompt.md agents/non-fiction/11_validate_decision.prompt.md
  git mv agents/non-fiction/polish.prompt.md agents/non-fiction/12_polish.prompt.md
  git mv agents/non-fiction/state.prompt.md agents/non-fiction/13_state.prompt.md
  ```

---

### Task 2: Implement Helper and Modify Prompt Loading in `src/quill/agent.py`
**Files:**
- Modify: `src/quill/agent.py`

**Interfaces:**
- Produces: `get_prompt_filename(stage: str) -> str`

- [ ] **Step 1: Add `get_prompt_filename` and modify `load_agent_config` & `list_agent_prompts`**
  Modify `src/quill/agent.py` to add `get_prompt_filename` and apply it:
  ```python
  def get_prompt_filename(stage: str) -> str:
      """Get the filename of the prompt template for a stage, including execution order prefix if applicable."""
      if stage == "chapter_brief":
          return "00_chapter_brief.prompt.md"
      try:
          from .pipeline import load_pipeline
          pipeline = load_pipeline("default")
          if stage in pipeline.stage_order:
              idx = pipeline.stage_order.index(stage)
              return f"{idx + 1:02d}_{stage}.prompt.md"
      except Exception:
          pass
      return f"{stage}.prompt.md"
  ```
  And update `load_agent_config`:
  ```python
  prompt_file = config_dir / get_prompt_filename(stage)
  ```
  And update `list_agent_prompts`:
  ```python
  def list_agent_prompts(agent_set: str) -> list[dict]:
      config_dir = AGENTS_DIR / agent_set
      if not config_dir.exists():
          return []
      prompts = []
      for f in sorted(config_dir.glob("*.prompt.md")):
          if f.name == "evaluate.prompt.md":
              stage = "evaluate"
          else:
              stage = f.name.replace(".prompt.md", "")
              if "_" in stage and stage[:2].isdigit():
                  stage = stage[3:]
          content = f.read_text(encoding="utf-8")
          title = content.split("\n")[0].lstrip("# ").strip() if content else stage
          prompts.append({
              "stage": stage,
              "file": str(f),
              "filename": f.name,
              "title": title,
              "length": len(content),
          })
      return prompts
  ```

---

### Task 3: Update Orchestrator and Blueprint Loading Logic
**Files:**
- Modify: `src/quill/orchestrator.py`
- Modify: `src/quill/blueprints/agents.py`

**Interfaces:**
- Consumes: `get_prompt_filename` from `quill.agent`

- [ ] **Step 1: Modify `src/quill/orchestrator.py`**
  In `_generate_chapter_brief`, modify lines to import and use `get_prompt_filename`:
  ```python
  from .agent import get_prompt_filename
  template_path = AGENTS_DIR / self.agent_set / get_prompt_filename("chapter_brief")
  if not template_path.exists():
      template_path = AGENTS_DIR / "default" / get_prompt_filename("chapter_brief")
  ```

- [ ] **Step 2: Modify `src/quill/blueprints/agents.py`**
  Modify endpoints to use `get_prompt_filename`:
  - In `agents_for_stage(stage)`:
    ```python
    prompt_file = d / _agent_mod.get_prompt_filename(stage)
    ```
  - In `agents_get_prompt(agent_set, stage)`:
    ```python
    prompt_file = _agent_mod.AGENTS_DIR / agent_set / _agent_mod.get_prompt_filename(stage)
    ...
    return jsonify({
        "stage": stage,
        "filename": prompt_file.name,
        "content": prompt_file.read_text(encoding="utf-8")
    })
    ```
  - In `agents_update_prompt(agent_set, stage)`:
    ```python
    prompt_file = _agent_mod.AGENTS_DIR / agent_set / _agent_mod.get_prompt_filename(stage)
    ```

---

### Task 4: Update Frontend JS Display
**Files:**
- Modify: `src/quill/static/js/agents.js`

- [ ] **Step 1: Modify `src/quill/static/js/agents.js`**
  Update list render and title render to use `filename`:
  - Line 78:
    ```javascript
    html += '<span style="color:var(--text-muted);font-size:12px;margin-left:8px">' + (p.filename || (p.stage + '.prompt.md')) + ' · ' + p.length + ' chars</span></div>';
    ```
  - Line 91:
    ```javascript
    document.getElementById('editor-title').textContent = currentSet + ' / ' + (data.filename || (stage + '.prompt.md'));
    ```

---

### Task 5: Update the Test Suite and Verify
**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_async.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/test_phase2b_task2_compose_prompt.py`

- [ ] **Step 1: Modify `tests/conftest.py`**
  Import and use `get_prompt_filename` when writing fixtures:
  ```python
  from quill.agent import get_prompt_filename
  ```
  Replace occurrences of `f"{stage}.prompt.md"` or `"review.prompt.md"` / `"revise.prompt.md"` with `get_prompt_filename(stage)`.

- [ ] **Step 2: Modify other test files**
  Use `get_prompt_filename` or updated path assertions:
  - In `tests/test_agent.py`: Import `get_prompt_filename` and replace hardcoded files with `get_prompt_filename(stage)`.
  - In `tests/test_app.py`: Import `get_prompt_filename` and replace `review.prompt.md` with `get_prompt_filename("review")`.
  - In `tests/test_async.py`: Import `get_prompt_filename` and replace mock filenames with `get_prompt_filename(stage)`.
  - In `tests/test_orchestrator.py`: Replace `chapter_brief.prompt.md` with `00_chapter_brief.prompt.md`.
  - In `tests/test_phase2b_task2_compose_prompt.py`: Import `get_prompt_filename` and write to `get_prompt_filename("structure")`.

- [ ] **Step 3: Run the test suite**
  Run: `.venv/bin/pytest`
  Expected: All 462 tests pass.
