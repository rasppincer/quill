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

12-stage pipeline with automated loopback decision stages:

```
brief → outline → research → draft → review → review_decision → revise → humanize → validate → validate_decision → polish → done
         content   special    content  feedback    decision        content   content   feedback      decision          content
                                                    ↓ reject                                          ↓ reject
                                                   revise ──────────────────────────────────────── polish
```

Decision stages evaluate feedback and either advance the pipeline or loop back for revision.

### Stage Modes

Each stage has a `mode` declared in `workflows/default.yaml`:

- **`content`** (default): Single-call returning `ContentStageOutput` (containing the generated text/JSON), saved to `<stage>.json` and `<stage>.md`. Used for outline, draft, revise, humanize, polish.
- **`feedback`**: Single-call returning `FeedbackStageOutput` (containing the critique), saved to `<stage>.json` and `<stage>.md`. Used for review, validate.
- **`decision`**: Single-call returning `DecisionStageOutput` (`decision: advance|reject`, `reason`). Inspects the preceding feedback stage and routes the pipeline accordingly. Used for `review_decision` and `validate_decision`.
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

> [!NOTE]
> `api_base`, `api_key`, and `model` are strictly derived from environment variables (`QUILL_API_BASE`, `QUILL_API_KEY`, and `QUILL_API_MODEL`/`QUILL_TEST_LLM_MODEL` in `.env`) rather than being editable via `model.yaml` or the UI. The model configuration UI and update endpoints were removed because model setup needs to be associated with a user management/multi-tenant system in the future, at which point it will be stored in the database instead of a global configuration file.

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

### Loop Tracking & Guardrails

Loop counts are tracked per stage in the database (`StageState.loop_count`). Decision stages (`review_decision`, `validate_decision`) increment the loop count of their feedback group on `reject` and reset it on `advance`. Each loop run writes versioned files (`.L1.md`, `.L2.md`, etc.) to the filesystem so all iterations are preserved for diagnostics. If the loop count reaches `max_loops`, the decision stage bypasses the LLM call and forces `advance`.

## Research Stage

Between outline and draft. Fetches reference material from SearXNG:

1. LLM generates 3-5 search queries from brief + outline
2. SearXNG executes queries, results deduplicated by URL
3. Results saved as-is to `research.md` (1-hour cache TTL)
4. Draft agent receives research.md as input alongside outline and brief

Configured per flavor via `research.enabled` and `research.required` in config.yaml.

## Workflow Engine & Execution Coordination

Quill orchestrates pipelines via a database-centric persistent state machine (`WorkflowEngine` in [engine.py](file:///home/bob/projects/quill/src/quill/engine.py)) and asynchronous Celery tasks.

### Stateless Central Coordination

To avoid circular imports and worker-to-worker process contention, workers do not trigger evaluations directly. Instead, when a Celery task finishes execution, it sends a POST request callback to the centralized Flask coordination endpoint at `/api/workflow/callback`. The Flask handler updates the DB state and invokes `workflow_engine.evaluate_and_dispatch(session, node_id, stage)` to determine the next step in the pipeline.

```
┌─────────────────┐      delay      ┌───────────────┐
│ WorkflowEngine  │────────────────▶│ Celery Worker │
│                 │                 │ (StageRunner) │
└─────────────────┘                 └───────────────┘
         ▲                                  │
         │          POST callback           │
         └──────────────────────────────────┘
```

### Sequential Chapter Progression

* The tree hierarchy is capped at 2 levels max (`Project` -> `Chapter`).
* Early stages (brief, structure, outline, research) run on the Project node.
* Chaptered stages (draft, review, revise, humanize, validate, polish, state) run sequentially per chapter. For stage $S$, Chapter $1$ executes, then Chapter $2$, up to Chapter $N$. Once all chapters complete stage $S$, the parent project transitions to stage $S+1$, which starts executing again sequentially from Chapter $1$.

### Revision Loop Strategies

When a parent decision stage (e.g. `review_decision`) decides to `reject`, the project transitions to a revision stage (e.g. `revise`) and applies one of three configurable revision strategies on the chapter nodes:
* `full`: Re-runs all chapters sequentially.
* `surgical`: Re-runs only the chapters explicitly flagged by chapter numbers or names in the critique text.
* `cascade` (Default): Re-runs the earliest flagged chapter and all downstream chapters to maintain context consistency.
* **Global Critique Fallback**: If the parent review does not identify specific chapters (general feedback), the engine defaults to Chapter 1, effectively running a `full` sequential rewrite.

For skipped chapters under `surgical` or `cascade`, the engine copies the output of the preceding stage and automatically marks the stage state as `completed` with the copied content, preserving the full iteration history.

### Sliding Context Construction

When a chaptered stage is dispatched, a sliding context window is assembled:
1. **Distant Chapters**: Merged structured `NarrativeState` summaries from the database for chapters $1 \dots N-2$.
2. **Close Neighbor**: Full text output of chapter $N-1$ to avoid seams.
3. **Forward Outlines**: Outlines for chapters $N+1$ and $N+2$ extracted from the structure output.
4. **Parent Brief**: Top-level brief text.


## File Structure & Persistence

The database is the absolute source of truth for all piece metadata, stage states, loop iterations, and content output text. The filesystem `output/` directory is utilized for legacy compatibility, local exports, and local debugging dumps.

Content stages write their output directly to the `StageState.output_text` field in the database. Serialized proxy properties on `StageState` map `body`, `critique`, and `decision` to/from a single text or JSON payload transparently.


## Database

Quill uses **PostgreSQL** (required — no SQLite fallback). `DATABASE_URL` must be set in the environment. The schema is managed via SQLAlchemy + Flask-Migrate (Alembic).

```
postgresql://user:pass@host:5432/quill
```

Schema ([models.py](file:///home/bob/projects/quill/src/quill/models.py)):

- **Project**: Top-level piece metadata (title, genre, type, constraints, target length, trigger, agent_set, revision_strategy).
- **DocumentNode**: Hierarchical tree structure with self-referential parent-child relationships. Capped at 2 levels: Project → Chapter.
- **StageState**: Workflow state (`fresh`/`new`, `processing`, `completed`), content body, loop count/iteration, and decision/critique for each stage of a node.
- **Metrics**: Per-stage mechanical readability scores and word counts.
- **AgentLog**: Append-only execution record of LLM calls, prompts, character/token counts, costs, and critiques.

## Observability

- **Run log**: JSONL per piece, every LLM call logged with timestamp, stage, char counts
- **SSE events**: Live stream during runs (`stage_start`, `stage_llm_call`, `chain_complete`)
- **Debug prompts**: `GET /api/pieces/<id>/prompt/<stage>` shows composed prompts without calling LLM
- **Metrics**: Per-stage readability (Flesch, grade, word count, passive voice %) stored as `.metrics.yaml`

## Testing

**447 pytest tests** — all passing (5 skipped without live external services).

```bash
pytest                          # backend unit + integration tests (~32s)
npm test                        # frontend JSDOM unit tests
```

Test suite uses `sqlite:///:memory:` via `QUILL_TESTING=1` for fast isolated runs without a live Postgres instance.

## Dependencies

- Flask (API + Jinja2 template server)
- PyYAML (frontmatter + meta.yaml parsing)
- SQLAlchemy + Flask-SQLAlchemy + Flask-Migrate (PostgreSQL ORM + migrations)
- psycopg2-binary (PostgreSQL driver)
- Werkzeug ProxyFix (nginx reverse proxy support)
- Jinja2 (prompt template rendering)
- LiteLLM (unified LLM provider interface, retries, cost auditing)
- Celery + redis-py (distributed task queue — worker optional, see Ticket 74)
- tenacity (retry logic for LLM calls)
