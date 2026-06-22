# Architecture — Quill Writing Workflow Engine

## Overview

Quill is an **agentic writing workflow engine**. It runs long-form content through a multi-stage pipeline where content stages use a two-call approach: one call generates content, a separate call evaluates and decides. The user provides the brief and makes the final publish/scrap decision — everything in between is agent-driven.

```
┌─────────────────────────────────────────────┐
│  Dashboard                                  │  /quill/ (Jinja2 templates)
│  Pieces, agents, run log, metrics           │
├─────────────────────────────────────────────┤
│  API Server (Flask, port 8325)              │  app.py (thin glue)
│  Blueprints: pieces, agents, runs, export   │  blueprints/*.py
├─────────────────────────────────────────────┤
│  Agent Runner                               │  runner.py
│  Two-call: generate → evaluate → decide     │
├─────────────────────────────────────────────┤
│  LLM Client                                 │  llm.py
│  OpenAI-compatible, urllib, zero deps       │
├─────────────────────────────────────────────┤
│  Pipeline Engine                            │  pipeline.py
│  Stage definitions, transitions, mode       │
├─────────────────────────────────────────────┤
│  Research Service                           │  research_service.py
│  SearXNG search, LLM query generation       │
├─────────────────────────────────────────────┤
│  Piece Storage                              │  piece.py
│  Directory-per-piece, meta.yaml + stage .md │
└─────────────────────────────────────────────┘
```

## Pipeline

10-stage linear pipeline:

```
brief → outline → research → draft → review → revise → humanize → validate → polish → done
         content   special    content  feedback  content   content   feedback   content
```

### Stage Modes

Each stage has a `mode` declared in `workflows/default.yaml`:

- **`content`** (default): Two-call approach — generate content, then evaluate with separate LLM call. Used for outline, draft, revise, humanize, polish.
- **`feedback`**: Single call — LLM reads content and produces critique/decision. Used for review, validate.
- **`research`**: Special stage — LLM generates search queries, SearXNG fetches results, saved as-is to `research.md`.

### Stage Inputs

Declared in `workflows/default.yaml` under `stage_inputs`:

```yaml
stage_inputs:
  outline: [brief.md]
  research: [outline.md, brief.md]
  draft: [outline.md, brief.md, research.md]
  revise: [draft.md, review.md]
  polish: [humanize.md, validate.md]
```

Stages without explicit inputs fall back to reading the previous stage's output.

### Transitions

- **Advance**: moves to next stage, preserves old stage file
- **Reject**: reverts to allowed previous stage
- **Loop**: content stages can loop back on negative evaluation (max_loops configurable per flavor)

## Agent System

### Two-Call Approach (Content Stages)

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Load     │───▶│ Generate │───▶│ Save     │───▶│ Evaluate │───▶│ Decide   │
│ prompt + │    │ call     │    │ content  │    │ call     │    │ advance  │
│ prev     │    │ (produce │    │ to stage │    │ (JSON    │    │ or loop  │
│ content  │    │  content)│    │ .md file │    │  decision)│    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                                    │
                                                          ┌─────────┴─────────┐
                                                          │                   │
                                                     advance             loop_back
                                                     (next stage)        (retry ≤ max_loops)
```

**Generate call**: LLM produces stage content → saved to `{stage}.md` immediately.
**Evaluate call**: Separate LLM call inspects the saved content → writes `{stage}.decision.md`.

The evaluator receives the full generated text via `{{GENERATED}}` — not a summary. Content is persisted before evaluation — if evaluate fails, the draft survives.

### Agent Config Hierarchy

```
agents/model.yaml              → global defaults (api_base, model, temperature, max_tokens)
agents/<flavor>/config.yaml    → flavor overrides + per-stage config
agents/<flavor>/<stage>.prompt.md → prompt templates (Jinja2)
```

Resolution: `stage config > flavor config > global config > defaults`

`api_key` is loaded from `QUILL_API_KEY` env var (not in YAML).

### Flavor Config (`agents/<flavor>/config.yaml`)

```yaml
description: "Non-fiction agents for blog posts, essays, articles"
temperature: 0.7
max_tokens: 12288
max_loops: 3
trigger: "on_advance"
research:
  enabled: true
  required: true

stages:
  draft:
    name: "Draft Agent"
    temperature: 0.7
  review:
    name: "Review Agent"
    temperature: 0.5
```

### Response Format

Agents return structured JSON:

```json
{
  "decision": "advance",
  "loop_count": 1,
  "critique": "Full analysis text..."
}
```

If the LLM returns malformed JSON, `agent.py` falls back to heuristic parsing with negative lookahead to avoid matching "loop_back" in instructional text.

### Loop Tracking

Loop history is recorded in `meta.yaml`:

```yaml
loops:
  review: 1
  validate: 2
```

### Loop Guardrails

`MetricsService` detects metric degradation across loop iterations:
- Word count drops >30%
- Readability shifts >15 points
- Vocabulary diversity drops >10%
- Passive voice increases >10 percentage points

Forces advance if degradation detected, preventing runaway loops.

## Research Stage

Between outline and draft. Fetches reference material from SearXNG:

1. LLM generates 3-5 search queries from brief + outline
2. SearXNG executes queries, results deduplicated by URL
3. Results saved as-is to `research.md` (1-hour cache TTL)
4. Draft agent receives research.md as input alongside outline and brief

Configured per flavor via `research.enabled` and `research.required` in config.yaml.

## File Structure

Each piece lives in its own directory under `output/`:

```
quill/output/
└── <piece-id>/
    ├── meta.yaml              ← source of truth (current_stage, metadata, loops)
    ├── 01_brief.md            ← brief content (with YAML frontmatter)
    ├── 02_outline.md          ← structure, arcs, pacing map
    ├── research.md            ← web research results (if research stage ran)
    ├── 03_draft.md            ← the actual prose
    ├── 03_draft.decision.md   ← evaluation of draft (JSON decision + critique)
    ├── 04_review.md           ← reviewer annotations + feedback
    ├── 05_revise.md           ← draft revised per review feedback
    ├── 05_revise.decision.md  ← evaluation of revision
    ├── 06_humanize.md         ← de-AI'd version
    ├── 07_validate.md         ← fact-checked version
    ├── 08_polish.md           ← final line edits
    ├── 09_done.md             ← published version
    ├── *.metrics.yaml         ← per-stage readability metrics
    └── run-log.jsonl          ← append-only run history
```

Content stages produce two files:
- `{stage}.md` — generated content (persisted immediately after generate call)
- `{stage}.decision.md` — evaluation result (decision + critique)

## Observability

- **Run log**: JSONL per piece, every LLM call logged with timestamp, stage, char counts
- **SSE events**: Live stream during runs (`stage_start`, `stage_llm_call`, `loop_guardrail`, `chain_complete`)
- **Debug prompts**: `GET /api/pieces/<id>/prompt/<stage>` shows composed prompts without calling LLM
- **Metrics**: Per-stage readability (Flesch, grade, word count, passive voice %) stored as `.metrics.yaml`

## Testing

**311 pytest tests + 32 behave BDD scenarios** — all passing.

```bash
pytest                          # unit tests (2.5s)
behave features/api/            # BDD scenarios (hit running API)
```

## Dependencies

- Flask (API + Jinja2 template server)
- PyYAML (frontmatter + meta.yaml parsing)
- Werkzeug ProxyFix (nginx reverse proxy support)
- Jinja2 (prompt template rendering)
- **No external LLM client dependencies** — stdlib urllib
- **No external search dependencies** — stdlib urllib for SearXNG
