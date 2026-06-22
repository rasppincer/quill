# ADR-003 Addendum: Further Decomposition

**Date:** 2026-06-22

## Identified Issues

### 1. No data models — everything is strings and dicts

`Piece` exists but meta.yaml operations (loop count, stage advance) are on
StageRunner, not on Piece. Pipeline stages are bare strings — no object that
knows "am I a content stage or feedback stage?". Agent configs are loaded
ad-hoc, not modeled.

**Fix:** Enrich Piece with loop/stage methods. Create Stage model. AgentConfig
already exists but isn't used consistently.

### 2. Duplicated setup in compose_prompt + run_stage

Both methods:
1. Load pipeline (4 lines)
2. Resolve output_dir, check piece exists (8 lines)
3. Load agent config, validate (4 lines)
4. Read inputs, build metrics, build context, render prompt (6 lines)
5. Build system prompts for generate/evaluate (15 lines)

That's ~37 lines duplicated. The only difference is compose_prompt returns
a dict, run_stage calls the LLM.

**Fix:** Extract `_prepare_stage(piece_id, stage, output_dir)` → returns
(StageContext | error_dict). Both methods call it.

### 3. No stage classification model

`content_stages = {"outline", "draft", "revise", "humanize", "polish"}`
appears in 3 places. The pipeline's StageDef has `mode` (feedback/autonomous)
but runner.py uses a hardcoded set instead.

**Fix:** Use `stage_def.mode` from the pipeline config. If mode isn't set,
fall back to the hardcoded set.

### 4. File I/O not isolated

`_write_output`, `_write_critique`, `_write_decision`, `_advance_meta` all
touch the filesystem directly. ADR-003 says "Only RunLogger and MetricsService
touch the filesystem" — violated.

**Fix:** Create `StageFileWriter` or add to `Piece` class.

### 5. System prompt construction duplicated

The strings "You are a {stage} agent for a {piece.genre} {piece.type}..."
appear in both compose_prompt and run_stage. Should be a method on
PromptBuilder.

**Fix:** `PromptBuilder.system_prompt(stage, piece, call_type)`.
