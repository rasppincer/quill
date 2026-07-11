# TICK-004: Execution Runner & Orchestration Integration

## Goal
Connect the pipeline and prompting changes to the main execution loop and handle loop state.

## Tasks
- [ ] **Modify `src/quill/runner.py`**: 
    - Update `auto_advance` evaluation to only trigger if the piece's overall setting is `auto`.
    - Implement handling for `"decision"` mode stages: check loop count bounds before making LLM calls, and bypass if limits are exceeded.

- [ ] **Modify `src/quill/chain_orchestrator.py`**: 
    - Integrate decision transitions: extract the returned decision from the runner output and query `pipeline.next_stage(current, decision)`.
    - Track and increment loop counts for the current loop group on `reject` decisions.

## Acceptance Criteria
- The system automatically advances in `auto` mode using the new decision logic.
- Loop counts are correctly incremented upon rejection.
- Execution stops if a loop limit is reached.
