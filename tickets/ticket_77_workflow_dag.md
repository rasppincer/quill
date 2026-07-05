# Ticket 77: Dynamic Workflow DAG Parser (Refactor Pipeline YAML)

## Description
Refactor `src/quill/pipeline.py` to parse arbitrary Directed Acyclic Graph (DAG) state transitions from workflow files instead of expecting a linear order.

## Background
Currently, pipelines are linear sequences with a simple `next` property. To support parallel reviews, branching, and complex loop routes, the pipeline must behave as a true DAG.

## Tasks
- [ ] Update `workflows/default.yaml` to specify workflow transitions as an adjacency list of edges (from -> to) or conditional branches.
- [ ] Update the `Pipeline` class to construct a DAG and compute valid execution paths.
- [ ] Implement cycle/DAG validation on workflow load to ensure no infinite loops.

## Success Criteria
- [ ] Pipeline loading validates DAG configuration.
- [ ] Transition engine supports branching stage routes and conditional jumps.

## Priority
Medium

---
**Next Expected Ticket Number**: 78
