# Quill Architectural Review

*Reviewed: 2026-06-22*

## Executive Summary

**Grade: B+**

Quill is a well-engineered agentic writing pipeline with a clean two-call agent pattern, declarative workflow config, and solid observability. The ADR-003 refactoring extracted 5 focused service classes from a monolith, and the recent research stage addition demonstrates the pipeline's extensibility.

However, `app.py` at 1183 lines is a god object, `CONTENT_STAGES` is hardcoded inconsistently in two files, the evaluate call silently advances on failure, and `ARCHITECTURE.md` is significantly outdated. The 300-line limit from ADR-003 is violated by 4 files.

---

## What's Working Well

### 1. Two-Call Agent Pattern

The generate→evaluate split is correctly implemented:

- **Generate** (`runner.py:344-375`): LLM writes content → saved to `{stage}.md` immediately
- **Evaluate** (`runner.py:682-756`): Separate LLM call critiques the saved content → `{stage}.decision.md`

The evaluator receives the **full generated text** via `{{GENERATED}}` in the evaluate template, not a summary. Content is persisted before evaluation — if evaluate fails, the draft survives.

Self-evaluation leak prevention is solid:
- Generate prompt says "Do NOT include any JSON or decision blocks" (prompt_builder.py:93-94)
- `_strip_json_block` (agent.py:182-213) only strips trailing JSON with `"decision"` key, preserving mid-content JSON examples

### 2. Declarative Pipeline Config

`workflows/default.yaml` defines stages, transitions, and input routing:

```yaml
stage_inputs:
  draft: [outline.md, brief.md, research.md]
  revise: [draft.md, review.md]
  polish: [humanize.md, validate.md]
```

This is loaded by `Pipeline` and used by `StageRunner._read_inputs()`. Changing what a stage reads requires zero Python changes.

### 3. Loop Guardrails

`MetricsService.check_guardrail()` (metrics_service.py:88-137) detects metric degradation across loop iterations:
- Word count drops >30%
- Readability shifts >15 points
- Vocabulary diversity drops >10%
- Passive voice increases >10 percentage points

Saves a baseline snapshot on first loop, compares on subsequent loops. Forces advance if degradation detected. This is a sophisticated pattern that prevents runaway loops.

### 4. Module Extraction (ADR-003)

5 focused classes extracted from the monolithic runner:

| Class | File | Lines | Responsibility |
|-------|------|-------|----------------|
| RunLogger | run_logger.py | 66 | JSONL append logging |
| MetricsService | metrics_service.py | 159 | Loop guardrails + metrics |
| PromptBuilder | prompt_builder.py | 138 | Template rendering + context |
| RunManager | run_manager.py | 207 | Async executor + SSE |
| Piece enrichment | piece.py | 416 | Data model + file I/O |

Each has a single clear responsibility. Dependency direction is correct — leaf services know nothing about each other.

### 5. Observability Stack

- **Run logging**: Every LLM call appends a JSONL entry with timestamp, stage, call type, char counts
- **SSE events**: Rich event stream (`stage_start`, `stage_llm_call`, `loop_guardrail`, `chain_complete`, etc.)
- **Debug prompt endpoint**: `GET /api/pieces/<id>/prompt/<stage>` shows composed prompts without calling LLM
- **Metrics tracking**: Per-stage readability stored as `.metrics.yaml`

### 6. Error Handling (Mostly)

| Scenario | Handling | Correct? |
|----------|----------|----------|
| LLM generate fails | `decision="error"` | ✓ |
| SearXNG down | Returns `[]`, logs warning | ✓ |
| Missing piece | Returns error decision | ✓ |
| Max loops reached | Forces advance | ✓ |
| Loop guardrail | Forces advance + logs | ✓ |
| Malformed JSON | Heuristic fallback parser | ✓ |

---

## What Needs Improvement

### P0 — Critical

#### 1. `app.py` is a God Object (1183 lines)

Contains health/pipeline/pieces CRUD (467 lines), dashboard routes, agent CRUD + prompt management, debug endpoints, run/chain/async endpoints, Google Docs export, comic generation, audio endpoints, and model config. Should be split into Flask blueprints: `pieces_api.py`, `agents_api.py`, `dashboard.py`, `export_api.py`.

#### 2. `CONTENT_STAGES` Hardcoded Inconsistently

**runner.py:37:**
```python
CONTENT_STAGES = {"outline", "draft", "revise", "humanize", "polish"}
```

**piece.py:62:**
```python
CONTENT_STAGES = {"draft", "revise", "humanize", "polish", "done"}
```

These are **different sets** — `piece.py` includes `done` and excludes `outline`. This controls whether a stage uses the two-call or single-call pattern. Adding a custom content stage requires editing Python in two places.

**Fix:** Add `mode: content | feedback` to workflow YAML stage definitions. Pipeline class exposes `is_content_stage(key)`. Remove both hardcoded sets.

#### 3. Evaluate Failure Silently Advances

`runner.py:745-750`:
```python
except ConnectionError:
    return AgentDecision(
        decision="advance",
        critique="Evaluation call failed, advancing by default.",
        output="",
    )
```

If the LLM is down during evaluation, the piece advances anyway. This should return `decision="error"` (like the generate handler does) or at minimum log at WARNING level.

#### 4. `ARCHITECTURE.md` is Outdated

Claims 9 stages (actual: 10), shows `action: advance` (actual: `decision`), says `api_key: "[REDACTED]"` in config (actual: env var only), claims no frontmatter needed (actual: stage files have frontmatter). First doc newcomers read — it's wrong.

### P1 — Important

#### 5. `_STAGE_PREFIXES` Hardcoded in piece.py

```python
_STAGE_PREFIXES = {
    "brief": "01", "outline": "02", "draft": "03",
    "review": "04", "revise": "05", "humanize": "06",
    "validate": "07", "polish": "08", "done": "09",
}
```

Custom stages won't get numeric prefixes. Should be derived from `pipeline.stage_order`.

#### 6. Zero Integration Tests Against a Real LLM

Every LLM call is mocked. Prompt templates are never validated against a real model. JSON response format assumptions are never tested end-to-end. At minimum, one `@pytest.mark.slow` smoke test that hits the local LLM.

#### 7. ADR-003 Line Limit Violations

| File | Lines | Limit | Ratio |
|------|-------|-------|-------|
| app.py | 1183 | 300 | 3.9x |
| runner.py | 756 | 300 | 2.5x |
| comic.py | 627 | 300 | 2.1x |
| piece.py | 416 | 300 | 1.4x |

`comic.py` embeds ~250 lines of inline CSS/HTML — should be a Jinja2 template.

#### 8. Research Stage Input Parsing is Fragile

`runner.py:444-449` splits input content on `"=== "` prefix strings to extract brief/outline text. This couples research to `_read_inputs`'s exact output format. If the separator changes, research breaks silently.

#### 9. No Config Caching

`load_model_config()` reads and parses `model.yaml` on every call (agent.py:30-35). The pipeline is loaded once at module level (app.py:57) — no hot-reload on YAML changes.

#### 10. `run_chain` Breaks on Any Error

`runner.py:579`: `if result.error: break` — a single LLM timeout aborts the entire chain. Consider retry logic or configurable error policy (skip/abort/retry).

### P2 — Nice to Have

- **No log rotation** for `run-log.jsonl` — grows unboundedly
- **No request tracing** — no correlation ID across a chain run
- **No YAML schema validation** — typos in config keys silently fall back to defaults
- **No context window budget checking** — long pieces could silently truncate
- **`max_workers=2` hardcoded** in run_manager.py — should be configurable
- **Deferred imports throughout app.py** — suggests circular import issues
- **`_piece_locks` dict grows unboundedly** in run_manager.py — minor memory leak

---

## Best Practices for Agentic Apps

### 1. Separate Generate and Evaluate — ✓ Quill does this

The two-call approach prevents self-evaluation bias. Content is saved before evaluation. Keep it.

### 2. Persist Intermediate Outputs — ✓ Quill does this

Generated content is written to disk before evaluation. If evaluation fails, the draft survives. This is the right pattern for any multi-step LLM pipeline.

### 3. Declarative Pipeline Config — ✓ Mostly done

`workflows/default.yaml` with `stage_inputs` is good. Push further: make `CONTENT_STAGES` a pipeline property, not a Python constant. Make stage prefixes derivable from pipeline order.

### 4. Loop Guardrails — ✓ Quill does this well

Metrics-based degradation detection is sophisticated. More agentic apps should do this. The baseline snapshot + comparison pattern is reusable.

### 5. Debug Transparency — ✓ Quill does this well

Debug prompt endpoint and prompt dumping are excellent for LLM development. Users can see exactly what the model receives. This should be standard in all agentic apps.

### 6. Observability from Day 1 — ✓ Mostly done

JSONL run logging, SSE events, per-stage metrics. Missing: request tracing, token counting, cost estimation.

### 7. Fail-Safe Defaults — ⚠ Partially

Most error paths return error decisions. But evaluate failure silently advances — this violates the fail-safe principle.

---

## Prioritized Action Items

### P0 — Fix Now

1. **Split `app.py` into blueprints** — pieces, agents, dashboard, export, model config. Each <200 lines.
2. **Make `CONTENT_STAGES` declarative** — add `mode: content | feedback` to pipeline YAML. Remove hardcoded sets from runner.py and piece.py.
3. **Fix evaluate failure policy** — return `decision="error"` instead of silent advance.
4. **Update `ARCHITECTURE.md`** — fix pipeline size, response format keys, file structure, env var docs.

### P1 — Next Sprint

5. **Derive `_STAGE_PREFIXES` from pipeline order** — remove hardcoded dict from piece.py.
6. **Add one real LLM integration test** — `@pytest.mark.slow`, validates prompt rendering + JSON parsing.
7. **Extract inline CSS from `comic.py`** — Jinja2 template, reduces to ~350 lines.
8. **Add retry logic to `run_chain`** — configurable: abort/skip/retry for transient LLM failures.
9. **Add config caching** — mtime check for `load_model_config()`.
10. **Make `max_workers` configurable** — model.yaml or env var.

### P2 — Backlog

11. Log rotation for `run-log.jsonl`
12. Request tracing (correlation ID per chain run)
13. YAML schema validation (pydantic/marshmallow)
14. Context window budget checking
15. Clean up deferred imports in app.py
