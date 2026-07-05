# Ticket 78: Merge Orchestrator & StageRunner into Node Runner

## Description
Unify `Orchestrator` and `StageRunner` into a single Node Runner. Deprecate separate child folders on disk and flat chapter split fallbacks.

## Background
The duplication of chapter draft processing (LLMCaller sequential generation vs. Orchestrator child-piece spawning) is a major architectural weakness. By using database nodes, the stage runner can execute directly on any tree node.

## Tasks
- [ ] Unify `runner.py` and `orchestrator.py` into a streamlined node execution engine.
- [ ] Implement generic stage execution: running a stage on a node executes on its children if chaptered, assembling sliding context dynamically from peer nodes in the database.
- [ ] Deprecate child directories and copy-propagation from parent folders on disk.

## Success Criteria
- [ ] Chaptered runs work seamlessly during asynchronous/chain execution without file duplication.
- [ ] No duplicate folder generation or flat chapter splits exist in code.
- [ ] All behave BDD scenarios pass.

## Priority
High

---
**Next Expected Ticket Number**: 79
