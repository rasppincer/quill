# Ticket 78: Unify Chaptered Execution into a Clean Node Runner

## Description
Consolidate the two paths for chaptered content generation — the inline `_generate_chaptered` method in `stage_runner.py` and the multi-chapter `ChainOrchestrator` — into a coherent, database-native execution model.

## Status
**Partially addressed, but messy.** The current architecture has grown organically:

- `StageRunner` (in `runner.py`) is the main facade for single-stage execution.
- `LLMCaller._generate_chaptered` (in `stage_runner.py`) handles draft-time chapter splitting inline, using LLM-based chapter detection.
- `ChainOrchestrator` (in `chain_orchestrator.py`) handles sequential stage chaining.
- There is no separate `orchestrator.py` — the multi-chapter orchestrator described in the Chapter Orchestrator design (TODO.md) was never built as a separate module.
- `DocumentNode` with `parent_id` and `children` is in the DB schema (Ticket 76 ✅), but the execution layer does not use it — chaptered draft generation still uses flat chapter splitting from the outline/structure text, not from child nodes in the database.

## The Problem
- Chaptered generation is a draft-only concern today (`_generate_chaptered`). Review, revise, humanize, polish all execute on the monolithic parent piece, not per-chapter.
- The Chapter Orchestrator design (sliding context, NarrativeState, per-chapter stage execution) was designed but never implemented.
- The DB tree model exists but the runner ignores it.

## Remaining Tasks
- [ ] Implement a `ChapterOrchestrator` that reads child `DocumentNode` records for a parent piece and runs each stage per-chapter with sliding context.
- [ ] Wire `StageRunner.run_stage` to detect chaptered pieces (parent with children in DB) and delegate to `ChapterOrchestrator` for prose stages (draft, review, revise, humanize, polish).
- [ ] Move `_generate_chaptered` out of `LLMCaller` and into `ChapterOrchestrator` as the draft execution step.
- [ ] Implement NarrativeState parsing from `state` stage output and accumulation across chapters.
- [ ] Deprecate the flat chapter-split fallback in `LLMCaller._parse_chapters` once child nodes are the authoritative source.

## Success Criteria
- [ ] Multi-chapter pieces run review, revise, humanize, polish per-chapter with sliding context.
- [ ] No duplicate execution paths for chaptered content.
- [ ] All unit and integration tests pass.

## Priority
High (long-form content quality depends on this)

---
**Next Expected Ticket Number**: 79
