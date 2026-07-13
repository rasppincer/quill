# Ticket 81: Refactor StageRunner and Orchestrator Decoupling

## Description
Refactor `src/quill/runner.py` and `src/quill/orchestrator.py` to decouple stage-routing logic (determining if a piece has chapters and delegating to the orchestrator) from single-piece execution logic (executing a stage on one specific file/node).

Currently, `StageRunner.run_stage()` routes to `Orchestrator`, while `Orchestrator` calls back to `StageRunner.run_stage()` to execute on child chapters. This creates a circular dependency resolved by passing a magic `_orchestrator_active` flag in the template `extra_context` to bypass recursion.

We need a cleaner, decoupled architecture:
1. `StageRunner.run_stage(...)` remains the public API and routes execution (delegating to `Orchestrator` if the target piece has chapters and is a chaptered stage, otherwise executing on the parent piece directly).
2. The core execution logic inside `StageRunner.run_stage` is separated into an internal method, e.g. `StageRunner._run_single_piece_stage(...)`.
3. `Orchestrator._run_stage_on_child(...)` is updated to invoke `StageRunner._run_single_piece_stage(...)` directly.
4. The recursion bypass flag `_orchestrator_active` is completely removed from the code.

## Status
**Unstarted.** The temporary routing delegation and recursion bypass flag are implemented and verified by tests, but need to be refactored into the clean decoupled structure described above.

## Tasks
- [ ] In [runner.py](file:///home/bob/projects/quill/src/quill/runner.py), extract the actual execution logic from `run_stage(...)` (the code following the orchestrator delegation check) into a new internal method `_run_single_piece_stage(self, piece_id: str, stage: str, output_dir: Path | None = None, event_queue=None, trace_id: str | None = None, force_advance: bool = False, extra_context: dict | None = None, custom_prompt: str | None = None) -> AgentDecision`.
- [ ] Simplify `StageRunner.run_stage(...)` so it only performs the `_has_chapters()` routing check:
  * If the piece has chapters and the stage is chaptered, call `Orchestrator.run_stage(...)`.
  * Otherwise, call `self._run_single_piece_stage(...)`.
- [ ] In [orchestrator.py](file:///home/bob/projects/quill/src/quill/orchestrator.py), update `_run_stage_on_child(...)` to call `runner._run_single_piece_stage(...)` instead of `runner.run_stage(...)`.
- [ ] Remove the insertion and checking of `_orchestrator_active` from both `runner.py` and `orchestrator.py`.
- [ ] Update the unit tests in [test_orchestrator.py](file:///home/bob/projects/quill/tests/test_orchestrator.py#L869-L933) to verify that `StageRunner.run_stage` delegates correctly to `Orchestrator` for parent runs, but child runs bypass it by calling `_run_single_piece_stage` directly.

## Success Criteria
- [ ] Circular dependency and recursion risks between `StageRunner` and `Orchestrator` are resolved cleanly without context flags.
- [ ] Multi-chapter asynchronous runs and synchronous runs continue to delegate correctly to the `Orchestrator` for parent pieces.
- [ ] Child chapter runs correctly bypass delegation and run on their single folder structure.
- [ ] All unit and integration tests in the test suite pass successfully.

## Priority
High — technical debt clean-up to ensure clear system architecture before building subsequent workflow features.
