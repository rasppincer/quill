# Architecture — Quill Writing Workflow Engine

## Overview

Quill is an **agentic writing workflow engine**. It runs long-form content through a multi-stage pipeline where content and feedback stages run as single LLM calls returning schema-guaranteed structured JSON. The user provides the brief and makes the final publish/scrap decision — everything in between is agent-driven.

```
┌─────────────────────────────────────────────┐
│  Dashboard                                  │  /quill/ (Jinja2 templates)
│  Pieces, agents, run log, metrics           │
├─────────────────────────────────────────────┤
│  API Server (Flask, port 8325)              │  app.py (thin glue)
│  Blueprints: pieces, agents, runs, export   │  blueprints/*.py
├─────────────────────────────────────────────┤
│  Agent Runner                               │  runner.py (facade)
│  ┌─────────────────────────────────────┐    │
│  │ StageRunner (LLMCaller)             │    │  stage_runner.py
│  │ Single-call structured execution    │    │
│  │ Chaptered generation for long-form  │    │
│  ├─────────────────────────────────────┤    │
│  │ ChainOrchestrator                   │    │  chain_orchestrator.py
│  │ Auto pipeline, interrupt, chain     │    │
│  ├─────────────────────────────────────┤    │
│  │ ContextAssembler                    │    │  context_assembler.py
│  │ Prompt composition, stage inputs    │    │
│  └─────────────────────────────────────┘    │
├─────────────────────────────────────────────┤
│  LLM Client                                 │  llm.py
│  OpenAI-compatible, LiteLLM client          │
├─────────────────────────────────────────────┤
│  Pipeline Engine                            │  pipeline.py
│  Stage definitions, transitions, mode       │
├─────────────────────────────────────────────┤
│  Research Service                           │  research_service.py
│  SearXNG search, LLM query generation       │
├─────────────────────────────────────────────┤
│  Piece Storage                              │  piece.py
│  Directory-per-piece, meta.yaml + stage .md │
│  Stage states, trigger, can_navigate        │
├─────────────────────────────────────────────┤
│  Logging                                    │  logging_config.py
│  Per-piece logs, common log, 3-day rotation │
├─────────────────────────────────────────────┤
│  Instrumentation                            │  timeit.py
│  @timeit decorator, LLM call timing         │
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

- **`content`** (default): Single-call returning `ContentStageOutput` (containing the generated text/JSON), saved to `<stage>.json` and `<stage>.md`. Used for outline, draft, revise, humanize, polish.
- **`feedback`**: Single-call returning `FeedbackStageOutput` (containing the critique and advancement decision), saved to `<stage>.json` and `<stage>.md`. Used for review, validate.
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

- **Arbitrary Jumps**: users/agents can transition arbitrarily between any two distinct stages defined in the pipeline.
- **Supersede**: running a stage resets all subsequent stages to `fresh` and unlinks their generated files.

### Stage States

Each stage has a state tracked in `meta.yaml`:

```yaml
stage_states:
  brief: ready
  outline: ready
  research: ready
  draft: generating
```

States: `fresh` (not yet completed/empty/superseded), `generating` (agent running), `completed` (completed/ready). Legacy state strings are dynamically mapped on-the-fly for backward compatibility.

### Trigger Modes

Per-piece trigger setting controls agent behavior on advance:

- **`manual`** (default): advance moves to next stage, agent does NOT run
- **`on_advance`**: advance moves + runs agent automatically
- **`auto`**: chain mode — runs all remaining stages without user intervention

### Chaptered Generation

For long-form content (10k+ words), the draft stage detects multi-part outlines and generates each chapter separately:

1. Parse outline/brief for `## Part N: Title` headers
2. Extract character sheet from brief for persistent context
3. Generate each chapter as separate LLM call (~2000 words each) using single-call content schemas
4. Concatenate chapters into single draft file

Chapter detection falls back through: outline headers → brief headers → brief bullet points (`- Part N: Description`).

## Agent System

### Single-Call Execution

Content and Feedback stages execute as a single LLM call per stage.

```
┌──────────┐    ┌─────────────┐    ┌──────────────┐
│ Load     │───▶│ Single-Call │───▶│ Save         │
│ prompt + │    │ LLM request │    │ content/crit │
│ context  │    │ (structured)│    │ to disk/db   │
└──────────┘    └─────────────┘    └──────────────┘
```

- **Content Stages**: Request `ContentStageOutput` structured JSON format (containing `content` string), saved to `<stage>.json` (raw JSON) and `<stage>.md` (parsed markdown).
- **Feedback Stages**: Request `FeedbackStageOutput` structured JSON format (containing `critique` string and transition `decision`), saved to `<stage>.json` (raw JSON) and `<stage>.md` (parsed critique markdown).

The LLM output is parsed directly into structured Pydantic models to guarantee response shape.

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

### Loop Tracking & Guardrails (Removed)

With the pipeline pivot to single-call execution, loop-back checks, loop counts, loop tracking, and loop guardrails have been removed. Stages advance immediately to `completed` upon run completion.

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
    ├── meta.yaml              ← source of truth (current_stage, metadata, loops, stage_states, trigger)
    ├── 01_brief.md            ← brief content (with YAML frontmatter)
    ├── 02_outline.md          ← structure, arcs, pacing map
    ├── 02_outline.decision.md ← evaluation of outline
    ├── 03_research.md         ← web research results (if research stage ran)
    ├── 04_draft.md            ← the actual prose (chaptered: ## Part N headers)
    ├── 04_draft.decision.md   ← evaluation of draft (JSON decision + critique)
    ├── 04_draft.generate_ch1-prompt.md  ← debug: per-chapter prompts
    ├── 05_review.md           ← reviewer annotations + feedback
    ├── 06_revise.md           ← draft revised per review feedback
    ├── 06_revise.decision.md  ← evaluation of revision
    ├── 07_humanize.md         ← de-AI'd version
    ├── 08_validate.md         ← fact-checked version
    ├── 09_polish.md           ← final line edits
    ├── 09_done.md             ← published version
    ├── *.metrics.yaml         ← per-stage readability metrics
    └── run-log.jsonl          ← append-only run history
```

Content stages produce two files:
- `{stage}.md` — generated content (prose/markdown)
- `{stage}.json` — raw structured JSON output

### Logging

Two-tier logging in `logs/`:

```
logs/
├── quill.log                    ← common log (startup, config, non-piece events)
├── quill.log.2026-06-27         ← rotated (3 days retention)
└── pieces/
    ├── my-story_20260627.log    ← per-piece log (stage transitions, LLM calls)
    └── ...
```

`PieceLogHandler` routes records with `piece_id` to per-piece files. `TimedRotatingFileHandler` for daily rotation. Old piece logs auto-cleaned after 3 days. No stdout — logs only. `QUILL_LOG_LEVEL` env var (default INFO).

## Database Schema

Quill uses a relational database schema (implemented via SQLAlchemy in [models.py](file:///home/bob/projects/quill/src/quill/models.py)) to replace `meta.yaml` and filesystem-based frontmatter/metrics tracking:

- **Project**: Holds top-level piece metadata (title, genre, type, constraints, target length, trigger, agent_set).
- **DocumentNode**: Represents files, chapters, or scenes in a hierarchical tree structure with self-referential parent-child relationships.
- **StageState**: Tracks workflow state (`fresh`, `generating`, `completed`), content body, and critiques for each stage of a `DocumentNode`.
- **Metrics**: Holds per-stage mechanical readability scores and word counts.
- **AgentLog**: Append-only execution record of LLM calls, prompts, character/token counts, costs, and critiques.

## Observability

- **Run log**: JSONL per piece, every LLM call logged with timestamp, stage, char counts
- **SSE events**: Live stream during runs (`stage_start`, `stage_llm_call`, `chain_complete`)
- **Debug prompts**: `GET /api/pieces/<id>/prompt/<stage>` shows composed prompts without calling LLM
- **Metrics**: Per-stage readability (Flesch, grade, word count, passive voice %) stored as `.metrics.yaml`

## Testing

**440 pytest tests + 32 behave BDD scenarios** — all passing.

```bash
pytest                          # unit tests (2.5s)
behave features/api/            # BDD scenarios (hit running API)
```

## Dependencies

- Flask (API + Jinja2 template server)
- PyYAML (frontmatter + meta.yaml parsing)
- Werkzeug ProxyFix (nginx reverse proxy support)
- Jinja2 (prompt template rendering)
 - **LiteLLM client** — advanced routing, built-in retries, cost auditing
- **No external search dependencies** — stdlib urllib for SearXNG
