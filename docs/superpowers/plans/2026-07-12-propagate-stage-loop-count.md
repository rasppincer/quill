# Propagate Stage Loop Count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correctly resolve stage filenames using their respective `loop_count` to ensure looped stages like Revise and Polish render correctly in the UI and are passed properly as inputs to subsequent stages.

**Architecture:** We will propagate loop count query lookups using `piece.stage_file()` and `piece.get_loop_count()` across context assembly, endpoint blueprints, orchestrators, and services.

**Tech Stack:** Python 3, Flask, SQLAlchemy, pytest

## Global Constraints
- Preserve existing comment style, formatting, and exception handling.
- Always use `piece.stage_file(stage)` or `piece.stage_file()` instead of manual `/` path joins with `_stage_filename(stage)` unless loop count is intentionally fixed at 0.

---

### Task 1: Context Assembler Input Resolution

**Files:**
- Modify: [src/quill/context_assembler.py](file:///home/bob/projects/quill/src/quill/context_assembler.py#L137-L162)
- Test: [tests/test_phase2b_task1_read_inputs.py](file:///home/bob/projects/quill/tests/test_phase2b_task1_read_inputs.py)

**Interfaces:**
- Consumes: `Piece.get_loop_count(stage: str) -> int`
- Produces: `ContextAssembler.read_inputs(piece: Piece, stage: str, pipeline, loop_count: int = 0) -> str` (with correct resolution of loop-versioned inputs)

- [ ] **Step 1: Write the failing test**
  Add a new test inside `tests/test_phase2b_task1_read_inputs.py` to verify that `read_inputs` fetches versioned files.
  ```python
  def test_read_inputs_resolves_looped_inputs(tmp_path):
      from quill.piece import Piece, _stage_filename
      from quill.context_assembler import ContextAssembler
      from quill.pipeline import Pipeline, Stage
      
      # Setup a dummy piece with loops
      piece = Piece(id="test_piece")
      piece._path = tmp_path
      
      # Mock loop count database lookup
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
  ```
- [ ] **Step 2: Run test to verify it fails**
  Run: `.venv/bin/pytest tests/test_phase2b_task1_read_inputs.py -k test_read_inputs_resolves_looped_inputs`
  Expected: FAIL with assertion error (either `(no input files found)` or wrong content)
- [ ] **Step 3: Modify [src/quill/context_assembler.py](file:///home/bob/projects/quill/src/quill/context_assembler.py#L137-L162)**
  Change `read_inputs` to pass `loop_count` to `_stage_filename`:
  ```python
          else:
              # Stage-specific inputs
              stage_inputs = pipeline.stage_inputs if pipeline else {}
              if stage in stage_inputs:
                  for input_stage in stage_inputs[stage]:
                      input_stage_name = input_stage.replace(".md", "")
                      fpath = stage_dir / _stage_filename(input_stage_name, loop_count=piece.get_loop_count(input_stage_name))
                      if fpath.exists():
                          text = fpath.read_text(encoding="utf-8")
                          m = _FRONTMATTER_RE.match(text)
                          inputs.append(f"=== {fpath.name} ===\n{text[m.end():] if m else text}")
              else:
                  # Default: read previous stage's output
                  stage_order = pipeline.stage_order if pipeline else []
                  if stage in stage_order:
                      idx = stage_order.index(stage)
                      if idx > 0:
                          prev_stage = stage_order[idx - 1]
                          prev_file = stage_dir / _stage_filename(prev_stage, loop_count=piece.get_loop_count(prev_stage))
                          if prev_file.exists():
                              text = prev_file.read_text(encoding="utf-8")
                              m = _FRONTMATTER_RE.match(text)
                              inputs.append(
                                  f"=== {prev_file.name} ===\n"
                                  f"{text[m.end():] if m else text}"
                              )
  ```
- [ ] **Step 4: Run test to verify it passes**
  Run: `.venv/bin/pytest tests/test_phase2b_task1_read_inputs.py`
  Expected: PASS
- [ ] **Step 5: Commit changes**
  ```bash
  git add src/quill/context_assembler.py
  git commit -m "feat: resolve looped stage inputs in ContextAssembler"
  ```

---

### Task 2: Blueprint Endpoints Update

**Files:**
- Modify: [src/quill/blueprints/pieces.py](file:///home/bob/projects/quill/src/quill/blueprints/pieces.py#L253)
- Modify: [src/quill/blueprints/pieces.py](file:///home/bob/projects/quill/src/quill/blueprints/pieces.py#L508-L531)
- Modify: [src/quill/blueprints/pieces.py](file:///home/bob/projects/quill/src/quill/blueprints/pieces.py#L613-L627)
- Modify: [src/quill/blueprints/pieces.py](file:///home/bob/projects/quill/src/quill/blueprints/pieces.py#L655-L680)
- Modify: [src/quill/blueprints/pieces.py](file:///home/bob/projects/quill/src/quill/blueprints/pieces.py#L703-L717)
- Modify: [src/quill/blueprints/dashboard.py](file:///home/bob/projects/quill/src/quill/blueprints/dashboard.py#L36)

**Interfaces:**
- Consumes: `Piece.stage_file(stage: str) -> Path`
- Produces: API endpoints returning correctly versioned stage files.

- [ ] **Step 1: Modify [src/quill/blueprints/pieces.py](file:///home/bob/projects/quill/src/quill/blueprints/pieces.py)**
  Replace occurrences of `piece.stage_dir() / _stage_filename(stage)` with `piece.stage_file(stage)`.
  1. Line 253 (in `pieces_get`):
     ```python
     stage_file = piece.stage_file(piece.current_stage)
     ```
  2. Line 508 (in `pieces_advance`):
     ```python
     old_stage_file = piece.stage_file(old_stage)
     ```
  3. Line 518 (in `pieces_advance`):
     ```python
     next_stage_file = piece.stage_file(next_stage)
     ```
  4. Line 529 (in `pieces_advance`):
     ```python
     old_stage_file = piece.stage_file(old_stage)
     ```
  5. Line 613 (in `pieces_reject`):
     Update deletion logic to handle versioned files if necessary, but at least update revert check to:
     ```python
     stage_file = piece.stage_file(s)
     ```
  6. Line 623 (in `pieces_reject`):
     ```python
     target_file = piece.stage_file(target)
     ```
  7. Line 655 (in `pieces_stage_navigate`):
     ```python
     stage_file = piece.stage_file(stage)
     ```
  8. Line 665 (in `pieces_stage_navigate`):
     ```python
     json_file = piece.stage_dir() / _stage_filename(stage, ".json", loop_count=piece.get_loop_count(stage))
     ```
  9. Line 703 (in `pieces_stage_save`):
     ```python
     if state == "fresh" or not piece.stage_file(stage).exists():
     ```
  10. Line 716 (in `pieces_stage_save`):
     ```python
     target_file = piece.stage_file(target_stage)
     ```
- [ ] **Step 2: Modify [src/quill/blueprints/dashboard.py](file:///home/bob/projects/quill/src/quill/blueprints/dashboard.py)**
  Change line 36 to:
  ```python
  stage_file = piece.stage_file(piece.current_stage)
  ```
- [ ] **Step 3: Run existing unit tests**
  Run: `.venv/bin/pytest tests/test_navigation.py`
  Expected: PASS
- [ ] **Step 4: Commit changes**
  ```bash
  git add src/quill/blueprints/pieces.py src/quill/blueprints/dashboard.py
  git commit -m "feat: propagate loop count in blueprint routes"
  ```

---

### Task 3: Orchestrator Outputs Assembly

**Files:**
- Modify: [src/quill/orchestrator.py](file:///home/bob/projects/quill/src/quill/orchestrator.py#L341)
- Modify: [src/quill/orchestrator.py](file:///home/bob/projects/quill/src/quill/orchestrator.py#L615-L666)

**Interfaces:**
- Consumes: `Piece.stage_file(stage: str) -> Path`

- [ ] **Step 1: Modify [src/quill/orchestrator.py](file:///home/bob/projects/quill/src/quill/orchestrator.py)**
  1. Line 341 (in `run_stage` on children):
     ```python
                 child_piece = load_piece(child_dir)
                 output_file = child_piece.stage_file(stage)
     ```
  2. Modify `_assemble_outputs` (lines 615-666) to fetch loop counts of parent and children:
     ```python
         @staticmethod
         def _assemble_outputs(
             child_ids: list[str], stage: str, base: Path,
         ) -> None:
             from .piece import _stage_filename, load_piece
     
             if not child_ids:
                 return
     
             parent_id = child_ids[0].rsplit("-chapter-", 1)[0]
             parent_dir = base / parent_id
             
             if parent_dir.exists():
                 parent_piece = load_piece(parent_dir)
                 loop_count = parent_piece.get_loop_count(stage)
             else:
                 try:
                     child_dir = base / child_ids[0]
                     child_piece = load_piece(child_dir)
                     loop_count = child_piece.get_loop_count(stage)
                 except Exception:
                     loop_count = 0
     
             stage_file = _stage_filename(stage, loop_count=loop_count)
             parts = []
     
             for child_id in child_ids:
                 child_dir = base / child_id
                 if child_dir.exists():
                     child_piece = load_piece(child_dir)
                     child_file = child_piece.stage_file(stage)
                 else:
                     child_file = child_dir / stage_file
     
                 if child_file.exists():
                     text = child_file.read_text(encoding="utf-8")
                     m = _FRONTMATTER_RE.match(text)
                     body = text[m.end():] if m else text
                     if body.strip():
                         parts.append(body.strip())
     
             if not parts:
                 return
     
             if not parent_dir.exists():
                 parent_dir.mkdir(parents=True, exist_ok=True)
     
             assembled = "\n\n---\n\n".join(parts)
             output_file = parent_dir / stage_file
             output_file.write_text(assembled, encoding="utf-8")
     
             logger.info(
                 "Orchestrator: assembled %d chapters into %s", len(parts), output_file,
             )
     ```
- [ ] **Step 2: Run tests**
  Run: `.venv/bin/pytest tests/test_orchestrator.py`
  Expected: PASS
- [ ] **Step 3: Commit changes**
  ```bash
  git add src/quill/orchestrator.py
  git commit -m "feat: support looped stages in orchestrator output assembly"
  ```

---

### Task 4: Metrics, Export Services, and Run Logger

**Files:**
- Modify: [src/quill/metrics_service.py](file:///home/bob/projects/quill/src/quill/metrics_service.py#L30)
- Modify: [src/quill/metrics_service.py](file:///home/bob/projects/quill/src/quill/metrics_service.py#L65-L77)
- Modify: [src/quill/metrics_service.py](file:///home/bob/projects/quill/src/quill/metrics_service.py#L96)
- Modify: [src/quill/metrics_service.py](file:///home/bob/projects/quill/src/quill/metrics_service.py#L143)
- Modify: [src/quill/comic.py](file:///home/bob/projects/quill/src/quill/comic.py#L356)
- Modify: [src/quill/blueprints/export.py](file:///home/bob/projects/quill/src/quill/blueprints/export.py#L27-L31)
- Modify: [src/quill/run_logger.py](file:///home/bob/projects/quill/src/quill/run_logger.py#L78)

**Interfaces:**
- Consumes: `Piece.stage_file(stage: str) -> Path`

- [ ] **Step 1: Modify [src/quill/metrics_service.py](file:///home/bob/projects/quill/src/quill/metrics_service.py)**
  1. Line 30: `stage_file = piece.stage_file(stage)`
  2. Line 65: `stage_file = piece.stage_file(input_stage)`
  3. Line 77: `current_stage_file = piece.stage_file(stage)`
  4. Line 96: `stage_file = piece.stage_file(stage)`
  5. Line 143: `stage_file = piece.stage_file(stage)`
- [ ] **Step 2: Modify [src/quill/comic.py](file:///home/bob/projects/quill/src/quill/comic.py)**
  1. Line 356: `stage_file = piece.stage_file(try_stage)`
- [ ] **Step 3: Modify [src/quill/blueprints/export.py](file:///home/bob/projects/quill/src/quill/blueprints/export.py)**
  1. Line 27: `stage_file = piece.stage_file(stage)`
  2. Line 31: `stage_file = piece.stage_file("polish")`
- [ ] **Step 4: Modify [src/quill/run_logger.py](file:///home/bob/projects/quill/src/quill/run_logger.py)**
  1. Line 78:
     ```python
             debug_file = piece.stage_dir() / _stage_filename(stage, f".{call_type}-prompt.md", loop_count=piece.get_loop_count(stage))
     ```
- [ ] **Step 5: Run tests**
  Run: `.venv/bin/pytest tests/`
  Expected: PASS
- [ ] **Step 6: Commit changes**
  ```bash
  git add src/quill/metrics_service.py src/quill/comic.py src/quill/blueprints/export.py src/quill/run_logger.py
  git commit -m "feat: update metrics, export, comic, and loggers to use versioned stage files"
  ```
