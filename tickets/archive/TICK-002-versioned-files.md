# TICK-002: Versioned File Handling & Context Assembly

## Goal
Implement the "version-preserved" filesystem approach for loopbacks to ensure diagnostics are available.

## Tasks
- [ ] **Modify `src/quill/piece.py`**: 
    - Update `Piece.stage_file` to append `.L{loop_count}` suffixes when `loop_count > 0`.
    - Ensure automated loops update `current_stage` directly without invoking clearing/purging operations (no auto-reset on reverts).

- [ ] **Modify `src/quill/context_assembler.py`**: 
    - Update `ContextAssembler.read_inputs` to dynamically map inputs based on loop index:
        - `review`: Loop 0 $\rightarrow$ `draft.md`; Loop $N > 0 \rightarrow$ `revise.LN.md`.
        - `revise`: Loop 1 $\rightarrow$ `draft.md` + `review.md`; Loop $N > 1 \rightarrow$ `revise.L{N-1}.md` + `review.L{N-1}.md`.
        - Apply similar logic for `validate` and `polish` stages.

## Acceptance Criteria
- Files are written with `.L1`, `.L2` etc. suffixes when in a loop.
- The correct versioned files are loaded as context for subsequent loop iterations.
- Previous versions of files remain on disk during the process.
