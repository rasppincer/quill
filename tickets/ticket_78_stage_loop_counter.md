# Ticket 78: Stage-level Loop Counter Refactor

## Description
Refactor the loop count tracker to make the loop counts belong strictly to the stage, preserving history across revision waves instead of resetting loop counts to `0` upon advancing a loop group. This will allow the system to directly resolve versioned filenames like `08_revise.L3.md` and `12_polish.L1.md` without requiring a directory scan / disk fallback hack.

## Status
**Proposed.** The current disk fallback check in `Piece.stage_file()` functions as a temporary compatibility layer (hack) but should be removed in favor of stage-scoped loop counters.

## Proposed Design
1. **Runner loop count logic (`src/quill/runner.py`):**
   Remove the loop count resetting code inside the `advance` branch of `run_stage()`:
   ```python
   # Remove this block
   for s in loop_stages:
       piece.set_loop_count(s, 0)
   ```
   This will keep the loop count at its highest number (e.g. `3`) so subsequent reads look up `08_revise.L3.md` directly.
   
2. **Rejection/Loop-back preservation:**
   If a later stage rejects back to `revise`, the counter can either continue incrementing (e.g., to `L4`) to preserve all history without overwriting earlier loop iterations, or be handled deterministically.

3. **Cleanup of filesystem fallback:**
   Remove the fallback search logic (`default_path.exists()` check and glob-based search) from `Piece.stage_file()` in `src/quill/piece.py` once stage-level counters are implemented.

## Priority
Medium — The filesystem fallback hack works for immediate needs, but refactoring the loop count behavior is cleaner and prevents future file overwrites on multi-rejections.

---
**Next Expected Ticket Number**: 79
