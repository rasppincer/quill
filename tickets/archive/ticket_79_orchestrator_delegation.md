# Ticket 79: Per-Chapter Execution for All Prose Stages

## Description
Extend per-chapter execution beyond draft generation to all prose stages (review, revise, humanize, polish), so that multi-chapter pieces are processed chapter-by-chapter with sliding context at every stage.

## Status
**Unstarted.** The current state:
- Draft stage: chapters are split from outline/structure text and generated individually by `LLMCaller._generate_chaptered`, then concatenated into the parent's draft file. This is a flat text split — it does not use child DB nodes.
- All other stages (review, revise, humanize, polish): execute once on the full parent piece file. No per-chapter breakdown.
- `DocumentNode` children exist in the DB schema but are not populated during draft generation — the runner never creates child piece records.

## Dependency
**Depends on Ticket 78** — the `ChapterOrchestrator` must exist before this ticket can be implemented. This ticket is the "wire it up to all stages" step after Ticket 78 builds the per-chapter execution core.

## Remaining Tasks
- [ ] During draft generation, create a child `DocumentNode` record for each chapter in the DB (written by `ChapterOrchestrator`).
- [ ] For each non-draft prose stage, `StageRunner.run_stage` detects parent pieces with children and delegates to `ChapterOrchestrator`.
- [ ] `ChapterOrchestrator` assembles sliding context per-chapter:
  - Full text of the previous chapter's stage output (chapter N-1)
  - NarrativeState summaries for chapters 1..N-2
  - Outline sketches for chapters N+1, N+2
  - Character sheet from parent brief
- [ ] Write per-chapter stage output to child piece records; concatenate to parent's stage file as a view artifact.
- [ ] Ensure chain runs (`run_chain`) work correctly for parent pieces with children.

## Success Criteria
- [ ] Multi-chapter pieces run review, revise, humanize, polish per-chapter.
- [ ] Each chapter's output is stored on the child `DocumentNode`.
- [ ] The parent piece's stage file is a concatenation of all child outputs.
- [ ] Sliding context prevents seams between chapters.

## Priority
High — depends on Ticket 78

---
**Next Expected Ticket Number**: 80
