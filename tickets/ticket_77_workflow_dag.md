# Ticket 77: Dynamic Workflow DAG Parser

## Description
Evolve `src/quill/pipeline.py` beyond an ordered list to support arbitrary graph-shaped workflows with conditional branching and parallel paths.

## Status
**Partially addressed.** The `new_pipe_implementation_plan` work added decision-stage dict transitions:
```python
next: str | dict[str, str] | None  # e.g. {"advance": "humanize", "reject": "revise"}
```
This supports conditional branching at decision stages and is working in production. However, the pipeline is still fundamentally an ordered list (`stage_order: list[str]`) — parallel paths, non-linear fan-out, and cycle validation are not implemented.

## What Was Done
- [x] `Stage.next` accepts `dict[str, str]` for decision-based transitions.
- [x] `Pipeline.next_stage(current, decision=None)` resolves both string and dict next values.
- [x] `default.yaml` uses dict `next:` for `review_decision` and `validate_decision`.

## Remaining Tasks (larger refactor — future scope)
- [ ] Replace `stage_order: list[str]` with an edge-based adjacency structure parsed from YAML.
- [ ] Implement DAG validation on workflow load (cycle detection, unreachable stage detection).
- [ ] Support fan-out / parallel stage execution (e.g. run `review` and `validate` in parallel).
- [ ] Update `progress()` to work without a linear index (e.g. topological distance from start).
- [ ] Update `default.yaml` schema to use edge declarations if/when the DAG parser is added.

## Priority
Low — current decision-stage branching covers immediate needs. Full DAG is a larger architectural investment with no blocking use-case yet.

---
**Next Expected Ticket Number**: 78
