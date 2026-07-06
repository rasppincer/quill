# Local LLM Structured Output Detection & Prompt Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proactively check if the LLM endpoint is local/LAN, and bypass structured outputs (JSON schema) for local models to prevent formatting degradation. Also complete the prompt composition simplification.

**Architecture:** We check `client.api_base` against localhost/LAN IP address ranges in `stage_runner.py`. If it matches, we set `use_structured = False`. We also refactor `ContextAssembler.compose_prompt` to return a unified single-prompt structure, updating the JS frontend and tests accordingly.

**Tech Stack:** Python 3.13, Flask, Vanilla JS, Pytest

## Global Constraints
- None

---

### Task 1: LAN API Detection in `src/quill/stage_runner.py`

**Files:**
- Modify: `src/quill/stage_runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `client.api_base`
- Produces: `is_local_api(api_base)` and override of `use_structured`

- [ ] **Step 1: Implement the LAN API detection helper and use it in `stage_runner.py`**
  Modify `src/quill/stage_runner.py` to define `is_local_api(api_base: str | None) -> bool` and update `run_stage` and `_generate_chaptered`.

  Add at the top/global level of `src/quill/stage_runner.py`:
  ```python
  def is_local_api(api_base: str | None) -> bool:
      if not api_base:
          return False
      from urllib.parse import urlparse
      try:
          parsed = urlparse(api_base)
          hostname = parsed.hostname
          if not hostname:
              return False
          hostname = hostname.lower()
          if hostname in ("localhost", "127.0.0.1", "::1"):
              return True
          if hostname.startswith("192.168.") or hostname.startswith("10."):
              return True
          if hostname.startswith("172."):
              parts = hostname.split('.')
              if len(parts) >= 2:
                  try:
                      second_octet = int(parts[1])
                      if 16 <= second_octet <= 31:
                          return True
                  except ValueError:
                      pass
      except Exception:
          pass
      return False
  ```

  Inside `run_stage` (around lines 71-73), replace:
  ```python
          cfg = load_model_config()
          use_structured = cfg.get("structured_output", False)
  ```
  with:
  ```python
          cfg = load_model_config()
          use_structured = cfg.get("structured_output", False)
          if use_structured and is_local_api(client.api_base):
              use_structured = False
  ```

  Inside `_generate_chaptered` (around lines 297-299), replace:
  ```python
          cfg = load_model_config()
          use_structured = cfg.get("structured_output", False)
  ```
  with:
  ```python
          cfg = load_model_config()
          use_structured = cfg.get("structured_output", False)
          if use_structured and is_local_api(client.api_base):
              use_structured = False
  ```

- [ ] **Step 2: Add verification test in `tests/test_runner.py`**
  Append a unit test to `tests/test_runner.py` that verifies `is_local_api` works correctly and overrides `use_structured`.

  ```python
  def test_is_local_api_detection():
      from quill.stage_runner import is_local_api
      assert is_local_api("http://localhost:11434") is True
      assert is_local_api("http://127.0.0.1:1234/v1") is True
      assert is_local_api("http://192.168.1.100:8000") is True
      assert is_local_api("https://api.openai.com/v1") is False
      assert is_local_api("https://api.anthropic.com") is False
  ```

- [ ] **Step 3: Run the tests to verify**
  Run: `.venv/bin/pytest -k test_is_local_api_detection`
  Expected: PASS

- [ ] **Step 4: Commit**
  ```bash
  git add src/quill/stage_runner.py tests/test_runner.py
  git commit -m "feat: proactively disable structured output on local/LAN endpoints"
  ```

---

### Task 2: Simplify `compose_prompt` and Update UI/Tests

**Files:**
- Modify: `src/quill/context_assembler.py`
- Modify: `src/quill/static/js/piece.js`
- Modify: `tests/test_runner.py`
- Test: `tests/test_phase2b_task2_compose_prompt.py`

**Interfaces:**
- Consumes: `ContextAssembler.compose_prompt`
- Produces: `{"prompt": {"system": ..., "user": ..., "char_count": ...}}` JSON response structure

- [ ] **Step 1: Simplify `compose_prompt` in `context_assembler.py`**
  Modify `src/quill/context_assembler.py` around line 132 to remove `is_content` branching, remove `is_content_stage` key, and return a single unified `prompt` key.

  Replace the `compose_prompt` body (from line 163 to 206) with:
  ```python
          system_prompt = PromptBuilder.system_prompt(stage, piece, "generate" if is_content else "feedback")
          base["prompt"] = {
              "system": system_prompt,
              "user": sc.prompt,
              "char_count": len(sc.prompt),
          }

          return base
  ```
  Ensure to remove `"is_content_stage": is_content,` from the `base` dict instantiation.

- [ ] **Step 2: Update `piece.js` to support new `"prompt"` key**
  In `src/quill/static/js/piece.js` (around line 107-112), update:
  ```javascript
              let promptText = '';
              if (data.generate) {
                  promptText = data.generate.user || '';
              } else if (data.single_call) {
                  promptText = data.single_call.user || '';
              }
  ```
  to:
  ```javascript
              let promptText = '';
              if (data.prompt) {
                  promptText = data.prompt.user || '';
              } else if (data.generate) {
                  promptText = data.generate.user || '';
              } else if (data.single_call) {
                  promptText = data.single_call.user || '';
              }
  ```

- [ ] **Step 3: Update `tests/test_runner.py` compose_prompt assertions**
  In `tests/test_runner.py`, update `test_compose_prompt_returns_filled_template` and `test_compose_prompt_content_stage_two_calls` to match the single prompt key schema and remove references to `is_content_stage`.

  Replace `test_compose_prompt_returns_filled_template` and `test_compose_prompt_content_stage_two_calls` (lines 606-633) with:
  ```python
      def test_compose_prompt_returns_filled_template(self, runner, sample_piece_with_review, tmp_output, monkeypatch):
          """compose_prompt returns the filled prompt template without calling LLM."""
          monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

          result = runner.compose_prompt("test-piece", "review", output_dir=tmp_output)

          assert "error" not in result
          assert result["stage"] == "review"
          assert "prompt" in result
          assert "draft content" in result["prompt"]["user"]
          assert result["prompt"]["char_count"] > 0
          assert result["template_vars"]["TITLE"] == "Test Piece"

      def test_compose_prompt_content_stage_two_calls(self, runner, sample_piece_with_review, tmp_output, monkeypatch):
          """Content stage compose_prompt returns single prompt with system and user keys."""
          monkeypatch.setattr("quill.piece.DEFAULT_OUTPUT_DIR", tmp_output)

          result = runner.compose_prompt("test-piece", "revise", output_dir=tmp_output)

          assert "error" not in result
          assert "prompt" in result
          assert "Do NOT include any JSON" in result["prompt"]["system"]
          assert result["prompt"]["char_count"] > 0
  ```

- [ ] **Step 4: Run target pytest runs to verify**
  Run: `.venv/bin/pytest tests/test_phase2b_task2_compose_prompt.py`
  Expected: PASS
  Run: `.venv/bin/pytest tests/test_runner.py -k test_compose_prompt`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add src/quill/context_assembler.py src/quill/static/js/piece.js tests/test_runner.py
  git commit -m "feat: simplify compose_prompt output structure, update frontend and tests"
  ```

---

### Task 3: Update `PIVOT.md` and Stale Docstrings

**Files:**
- Modify: `PIVOT.md`
- Modify: `src/quill/stage_runner.py`
- Modify: `src/quill/pipeline.py`

- [ ] **Step 1: Clean up stale comments in `stage_runner.py` and `pipeline.py`**
  In `src/quill/stage_runner.py` (lines 1-6), change:
  ```python
  """StageRunner — focused generate→evaluate loop for a single stage.

  Handles the LLM calls for content stages (two-call: generate + evaluate)
  and feedback stages (single call). Does NOT handle context assembly,
  state transitions, or chain orchestration — those live in runner.py.
  """
  ```
  to:
  ```python
  """StageRunner — execution engine for a single stage.

  Handles the single-call LLM execution returning schema-guaranteed JSON.
  Does NOT handle context assembly, state transitions, or chain orchestration
  — those live in runner.py.
  """
  ```

  In `src/quill/pipeline.py` (line 27), change:
  ```python
      mode: str = "content"  # "content" (two-call) or "feedback" (single-call)
  ```
  to:
  ```python
      mode: str = "content"  # "content" or "feedback"
  ```
  And in line 58, change:
  ```python
          """Check if a stage uses two-call (generate→evaluate) mode."""
  ```
  to:
  ```python
          """Check if a stage is a content generation stage."""
  ```

- [ ] **Step 2: Update `PIVOT.md` to reflect overall completion state**
  Check off Phase 2b tasks, add notes about proactive LAN IP-based local model structured output selection, and mark other completed phases.

  In `PIVOT.md`:
  - Mark Phase 2b Task 1 and Task 2 as completed:
    `- [x] **Remove loop-back block from read_inputs**...`
    `- [x] **Simplify compose_prompt**...`
  - Add a subtask under Phase 2b for local LLM check:
    `- [x] **Proactive Local LLM LAN IP check**: Automatically disable structured outputs when `api_base` points to localhost or a private LAN IP.`
  - Mark Phase 3 and Phase 4 as completed.

- [ ] **Step 3: Run the full test suite**
  Run: `.venv/bin/pytest tests/test_phase2b_task1_read_inputs.py tests/test_phase2b_task2_compose_prompt.py tests/test_runner.py`
  Expected: PASS

- [ ] **Step 4: Commit**
  ```bash
  git add PIVOT.md src/quill/stage_runner.py src/quill/pipeline.py
  git commit -m "docs: update PIVOT.md, clean up stale docstrings and comments"
  ```
