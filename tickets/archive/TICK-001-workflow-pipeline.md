# TICK-001: Workflow Definition & Pipeline Logic

## Goal
Update the core definitions and pipeline resolution to support decision-based transitions.

## Tasks
- [x] **Modify `workflows/default.yaml`**: 
    - Add `review_decision` (between `review` and `revise`) and `validate_decision` (between `validate` and `polish`).
    - Set `mode: decision` for these new stages.
    - Define the `next` mapping for decisions:
      ```yaml
      next:
        advance: humanize
        reject: revise
      ```
    - Route `revise` back to `review` and `polish` back to `validate`.

- [x] **Modify `src/quill/pipeline.py`**: 
    - Update `Pipeline.next_stage` to accept an optional `decision: str | None` argument.
    - Implement lookup logic to resolve the next stage based on the provided decision string when the transition is a dictionary.

## Acceptance Criteria
- Pipeline can resolve the next stage given a decision string (e.g., "advance" or "reject").
- Workflow YAML reflects the new decision stages and loopback paths.
