# Design Spec: Stage Loop Counter Refactor
Date: 2026-07-12
Status: Proposed

## Objective
Refactor the loop count tracking mechanism so that loop counts belong strictly to their respective Stage objects and persist in the database, preserving history across revision waves instead of resetting loop counts to `0` upon advancing a loop group. This allows the system to resolve versioned filenames like `08_revise.L3.md` directly and simplifies state transition logic.

## Proposed Changes

### 1. Piece Model (`src/quill/piece.py`)
- **Introduce `handle_revert(target_stage: str)`**:
  - Encapsulate index comparison and loop group logic.
  - If `target_stage` is earlier in the pipeline order than `self.current_stage` and it is *not* a loop-revert within the active loop group (`{"review", "review_decision", "revise"}` or `{"validate", "validate_decision", "polish"}`), call `self.supersede_from(target_stage)`.
- **Simplify `stage_file(stage: str | None = None)`**:
  - Remove the disk-based search fallback (glob-based search for `.L*.md` files).
  - Resolve paths directly via `_stage_filename(stage, loop_count=loop_count)`.

### 2. Runner Stage Execution Logic (`src/quill/runner.py`)
- **Stop Resetting Loop Counts**:
  - Remove the block of code in `StageRunner.run_stage()` that resets loop counts of the group stages to `0` upon `advance`.

### 3. API Runs Blueprint (`src/quill/blueprints/runs.py`)
- **Delegate Transition Logic**:
  - Remove the low-level index comparisons and hardcoded loop groups from the `/api/pieces/<piece_id>/run` endpoint.
  - Replace them with a single call to `piece.handle_revert(target_stage)`.

## Verification Plan

### Automated Tests
- Update loop count assertions in `tests/test_decision_stages.py` and `tests/test_runner.py` to match the new behavior where loop counts are not reset to 0 after advancing.
- Add tests for `piece.handle_revert(target_stage)` covering:
  - Reverting inside the active loop group (should NOT call `supersede_from`).
  - Reverting outside the active loop group (should call `supersede_from`).
- Ensure all tests pass via `uv run pytest`.
