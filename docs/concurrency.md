# Concurrency Model

## Overview

Quill supports async agent runs (background LLM calls) while the user continues browsing. This document explains how concurrent operations are protected.

## Components

### RunManager (run_manager.py)
- Singleton with `ThreadPoolExecutor(max_workers=2)`
- Tracks runs in `_runs` dict: `run_id → {status, result, piece_id, stage, ...}`
- Run lifecycle: `running` → `complete` (or `error`)
- Auto-cleanup after 5 minutes

### Piece detail API (`GET /api/pieces/<id>`)
- Returns `running: true/false` field
- Frontend uses this on page load to detect active runs

## Protection Mechanisms

### 1. Piece-level run blocking

**Where:** `POST /run-async`, `POST /advance`, `POST /reject`

**Logic:** `RunManager.is_piece_running(piece_id)` checks if any run for this piece has `status == "running"`. If yes → 409.

**Prevents:**
- Starting two runs on the same piece simultaneously
- Advancing while an agent is still generating
- Rejecting while an agent is still generating

**Does NOT prevent:**
- Starting runs on different pieces (allowed — different piece locks)
- Advancing after a run completes (allowed — run is done)

### 2. Frontend run state detection

**Where:** piece detail page, on `DOMContentLoaded`

**Logic:** Fetches piece detail API, checks `running` field. If true:
- Disables "Run Agent" button
- Shows "⏳ Running..." state
- Polls every 2s until `running` becomes false
- Auto-reloads page to show new stage

**Purpose:** UX only — not a safety mechanism. Prevents confusion after F5 refresh during a run.

### 3. Run status transitions

```
start_run() → status = "running"
                ↓
run_stage() completes → status = "complete"
                ↓
        SSE sentinel (None) → event queue signals done
                ↓
        Cleanup after 5 minutes → removed from _runs dict
```

## Race Condition Scenarios

### Scenario 1: User clicks "Run Agent" twice fast
- First call: `start_run()` → returns `run_id`, status = "running"
- Second call: `is_piece_running()` → True → 409 response
- ✅ Protected

### Scenario 2: User clicks "Advance" while run is in progress
- `is_piece_running()` → True → 409 response
- ✅ Protected

### Scenario 3: User hits F5 during run
- Page reloads → piece detail API returns `running: true`
- Frontend shows "⏳ Running..." and polls
- Run completes → frontend detects `running: false` → auto-reloads
- ✅ UX handled

### Scenario 4: Run completes, user clicks "Advance"
- `is_piece_running()` → False → advance allowed
- Run already wrote output and advanced the piece internally
- User's advance moves to the next stage (correct behavior)
- ✅ Safe — no race

### Scenario 5: Slow LAN LLM, user navigates away and back
- Run is still "running" in RunManager
- Page loads → sees `running: true` → polls
- ✅ UX handled

## Configuration

| Config | Location | Effect |
|--------|----------|--------|
| `debug_prompts: true` | agents/model.yaml | Dumps full prompts to `{stage}.{call}-prompt.md` files |
| `debug_prompts: false` | agents/model.yaml | Only writes run-log.jsonl metadata |

## Files Written During a Run

| File | When | Content |
|------|------|---------|
| `run-log.jsonl` | Always | Timestamp, stage, call type, char counts, decision, critique |
| `{stage}.generate-prompt.md` | debug_prompts=true | Full generate system + user prompt |
| `{stage}.evaluate-prompt.md` | debug_prompts=true | Full evaluate system + user prompt |
| `{stage}.agent-prompt.md` | debug_prompts=true | Full feedback stage system + user prompt |
| `{stage}.md` | On generate complete | Generated content |
| `{stage}.decision.md` | On evaluate complete | Decision + critique |
| `{stage}.metrics.yaml` | On advance | Readability metrics |
