# Ticket 79: Delegate Chaptered Stage Execution to Orchestrator in StageRunner

## Description
Modify `StageRunner.run_stage` in `src/quill/runner.py` to delegate execution to `Orchestrator` when running a chaptered stage on a multi-chapter piece.

## Background
Currently, asynchronous runs, chain runs, and behave scenarios call `StageRunner.run_stage` directly. If the piece is chaptered, it bypasses the `Orchestrator` and runs standard single-call execution on the parent piece, causing LLM timeout/truncation issues in stages after `draft`.

## Tasks
- [ ] Update `StageRunner.run_stage` in `src/quill/runner.py` to check if `extra_context` is not present, and try running via `Orchestrator.run_stage`.
- [ ] If `Orchestrator.run_stage` returns a decision, return it immediately to bypass standard execution.

## Success Criteria
- [ ] Multi-chapter pieces run via async, chain, or BDD execute chapter-by-chapter across all prose stages.
- [ ] All unit and integration tests pass.

## Priority
High

---
**Next Expected Ticket Number**: 80
