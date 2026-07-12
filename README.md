# Quill — Agentic Writing Workflow Engine

A structured pipeline for producing long-form content: stories, articles, blogs, editorials, essays. Turns the one-shot "dump 10K words" approach into a multi-stage workflow with **autonomous agent-driven review, revision, and validation**.

## Origin

Born from the Gold Collapse experience (~/stories/poe2-gold-collapse.md) — a 10,000+ word Bulgarian-language short story written in a single session. The story worked conceptually but the process had no review cycle, no fact-checking, no humanize pass, and the word count target drove padding over quality.

## The Pivot

Quill started as a **tracking pipeline** — manual advance/reject buttons, no automation. Now it's an **agentic writing app**: agents critique, decide, and loop autonomously. The user only touches the final product (publish or scrap). Everything in between is agent-driven.

## Workflow

```
┌─────────┐   ┌──────────┐   ┌────────┐   ┌───────┐   ┌────────┐   ┌──────────────┐   ┌────────┐   ┌──────────┐   ┌──────────────┐   ┌───────┐   ┌──────┐
│  BRIEF  │──▶│ OUTLINE  │──▶│ DRAFT  │──▶│ REVIEW│──▶│REVIEW  │──▶│    REVISE    │──▶│HUMANIZE│──▶│ VALIDATE │──▶│  VALIDATE    │──▶│ POLISH│──▶│ DONE │
│         │   │          │   │        │   │       │   │DECISION│   │              │   │        │   │          │   │  DECISION    │   │       │   │      │
│ Topic   │   │ Sections │   │ Write  │   │ Read +│   │advance │   │ Apply        │   │ Strip  │   │ Fact-    │   │ advance      │   │ Final │   │      │
│ Audience│   │ Pacing   │   │ chunks │   │ annotate  │ reject─┐│   │ feedback     │   │ AI-isms│   │ check    │   │ reject─┐     │   │ pass  │   │      │
│ Tone    │   │ Flow     │   │        │   │ Flag  │   │        ││   │              │   │        │   │          │   │        │     │   │       │   │      │
│ Length  │   │ Beats    │   │        │   │ issues│   └────────┘│   │              │   │        │   │          │   └────────┘     │   │       │   │      │
└─────────┘   └──────────┘   └────────┘   └───────┘            │   └──────────────┘   └────────┘   └──────────┘                  │   └───────┘   └──────┘
                                                                └──────────────────────────────────────────────────────────────────────▶ (back to REVISE)
                                                                                                                                     └──▶ (back to POLISH)
```

Each stage is **atomic** — one concern per stage, one file per stage. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

### Stages

1. **Brief** — Define what you're writing (topic, audience, tone, constraints)
2. **Outline** — Structure before prose (sections, pacing, beats, arcs)
3. **Draft** — Write in chunks (follow outline, allow organic detours)
4. **Review** — Read and annotate (pacing, logic, consistency, completeness)
5. **Review Decision** — LLM evaluates review critique: `advance` → Revise, `reject` → loop back
6. **Revise** — Apply review feedback to produce revised draft
7. **Humanize** — Strip AI-isms, inject personality, match language voice
8. **Validate** — Domain-specific fact checking (game refs, trading logic, cultural details)
9. **Validate Decision** — LLM evaluates validate critique: `advance` → Polish, `reject` → loop back
10. **Polish** — Final line-level edits (word choice, rhythm, formatting)
11. **Done** — Published version

### Automated Loopback

Decision stages (`review_decision`, `validate_decision`) automate the revision loop. They call an LLM to evaluate the preceding feedback stage and return `advance` or `reject`. On `reject`, loop counts increment and each pass is preserved with versioned file suffixes (`.L1.md`, `.L2.md`, ...). Once `max_loops` is reached, the pipeline advances regardless.

## Agent System

All stages (outline through polish) are **agent-driven**. The chain can run from brief→done fully automated. Each stage executes as a **single LLM call** returning structured JSON:

- **Content stages** (outline, draft, revise, humanize, polish) — return `ContentStageOutput`, written to `{stage}.md`.
- **Feedback stages** (review, validate) — return `FeedbackStageOutput` with a detailed critique, written to `{stage}.md`.
- **Decision stages** (review_decision, validate_decision) — return `DecisionStageOutput` with `decision: advance|reject` and a `reason`, routing the pipeline.

Loop versioning preserves all iterations: `.L1.md`, `.L2.md`, etc. are written on each loop pass so no generated content is lost.


### Template Variables

Prompt templates use Jinja2 syntax. Available variables:

| Variable | Description |
|----------|-------------|
| `{{CONTENT}}` | Input content (previous stage output, loop context) |
| `{{TITLE}}` | Piece title |
| `{{GENRE}}` | fiction / non-fiction |
| `{{TYPE}}` | blog / story / essay / editorial / analysis / tutorial |
| `{{LANGUAGE}}` | en / bg / mixed |
| `{{STAGE}}` | Current stage name |
| `{{PIECE_ID}}` | Piece ID |
| `{{METRICS}}` | Text metrics block (Flesch, word count, etc.) |
| `{{loop_count}}` | Current loop iteration (0 on first run) |
| `{{is_looping}}` | Boolean — true when loop_count > 0 |

Conditional blocks: `{% if is_looping %}...{% endif %}` inject context only during loop iterations.

The user is only involved at the publish/scrap decision. Everything else is autonomous.

### Agent Sets

Agents are **swappable** — different agent sets for different genres or quality levels:

```
quill/agents/
├── default/                ← Generic — works for any genre
│   ├── config.yaml
│   └── *.prompt.md
├── fiction/                ← Narrative-focused (stories, creative writing)
│   ├── config.yaml
│   └── *.prompt.md
└── non-fiction/            ← Argument-focused (blogs, essays, analysis)
    ├── config.yaml
    └── *.prompt.md
```

Different pieces can use different agent sets. The prompt templates are fully editable via the dashboard.

### Trigger Modes

- **`run_on_advance`** — agent runs when you click "Run Agent" (manual trigger)
- **`full_auto`** — agent runs automatically on stage completion, chains through all remaining stages

### Heuristic Parser

When the LLM returns malformed JSON, `agent.py` falls back to heuristic parsing. The parser uses regex with **negative lookahead** to avoid matching "loop_back" in instructional or example text within the content itself.

### LLM Client

OpenAI-compatible API client (`src/quill/llm.py`) — works with any provider (OpenAI, Anthropic via proxy, local models via llama.cpp, etc.). Zero external dependencies, uses `urllib`.

## File Structure

```
quill/
├── src/quill/
│   ├── app.py           ← Flask API + dashboard routes
│   ├── piece.py         ← Piece loader (meta.yaml + per-stage files)
│   ├── pipeline.py      ← Stage definitions, advance/reject logic
│   ├── agent.py         ← Agent config loader, response parser
│   ├── llm.py           ← OpenAI-compatible LLM client (urllib)
│   ├── runner.py        ← Stage executor (critique → decide → loop)
│   ├── celery_app.py    ← Celery app + run_stage_task (broker/backend via REDIS_URL)
│   ├── templates/       ← Dashboard HTML templates
│   └── static/          ← CSS, JS assets
├── agents/
│   └── default/         ← Default agent set (config + prompts)
├── output/
│   └── <piece-id>/      ← Piece directories
│       ├── meta.yaml    ← Source of truth (current_stage, metadata)
│       ├── brief.md     ← Brief content
│       ├── outline.md   ← Structure, arcs, pacing map
│       ├── outline.decision.md  ← Evaluation of outline
│       ├── draft.md     ← The raw prose
│       ├── draft.decision.md    ← Evaluation of draft
│       ├── review.md    ← Reviewer annotations
│       ├── revise.md    ← Revised per review feedback
│       ├── revise.decision.md   ← Evaluation of revision
│       ├── humanize.md  ← De-AI'd version
│       ├── validate.md  ← Fact-checked version
│       ├── polish.md    ← Final line edits
│       └── done.md      ← Published version
├── docs/
│   └── ARCHITECTURE.md  ← Full architecture documentation
└── pyproject.toml       ← Project config
```

## API

### Pieces

```
GET  /api/pieces                    — list all pieces + current stages
GET  /api/pieces/<id>               — piece detail (metadata, stages, progress)
POST /api/pieces                    — create new piece from brief
POST /api/pieces/<id>/advance       — advance to next stage
POST /api/pieces/<id>/reject        — revert to previous stage
GET  /api/pipeline                  — pipeline stage definitions
GET  /health                        — health check
```

### Agents

```
GET  /api/agents                    — list all agent sets
GET  /api/agents/<set>              — agent set config + prompts
GET  /api/agents/<set>/<stage>/prompt  — read prompt template
PUT  /api/agents/<set>/<stage>/prompt  — update prompt template
POST /api/pieces/<id>/run           — run agent (sync, blocks until done)
POST /api/pieces/<id>/run {"chain": true}  — run all remaining stages (sync)
POST /api/pieces/<id>/run-async     — run agent (async, returns run_id)
GET  /api/pieces/<id>/runs/<run_id>/events — SSE live progress stream
GET  /api/pieces/<id>/prompt/<stage> — debug: show composed prompt
```

### CLI Commands

#### Sync Legacy Pieces
To import existing pieces stored under the `output/` directory into the database:
```bash
PYTHONPATH=src .venv/bin/flask --app quill.app sync-legacy [--force]
```
Options:
* `--force` / `-f`: Force update/overwrite existing database records from filesystem files.
* Safe by default: Checks the database first and skips any pieces that are actively in progress (stage state is `generating`).


## Dashboard

Frontend lives in the One Ring dashboard at `/quill/dashboard`. Four pages:

- **Pieces** — overview with stats cards, stage badges, progress bars
- **Piece detail** — pipeline visualization, advance/reject buttons, **Run Agent** button with live critique display
- **Agents** — agent set browser, config viewer, prompt editor
- **Pipeline** — stage definitions, file structure, conventions

## Conventions

- PostgreSQL database is the single source of truth for all piece metadata, stage states, loop iterations, and content output text.
- Directories with `meta.yaml` + per-stage files are used for local exports and legacy compatibility.
- Content stages produce two outputs: `{stage}.md` (generated text) and `{stage}.decision.md` (evaluation), mapped to the database.
- Feedback stages produce one output: `{stage}.md` (critique, clean markdown).
- Output files are prefixed with stage numbers: `01_brief.md`, `03_draft.md`, `09_done.md`.
- Prompt templates use Jinja2 syntax with `{% if is_looping %}` conditionals.
- Debug: `debug_prompts: true` in model.yaml dumps actual prompts to files at runtime.
- Structured output: `structured_output: true` in model.yaml requests JSON from provider.
- Async: Celery queue handles execution with coordination HTTP callbacks.
- Works standalone (port 8325) or via nginx (`/quill/`).
- ProxyFix handles `X-Forwarded-Prefix` for correct URL generation behind nginx.
- Agent loop history and revision loop strategies are managed directly in the database.
- Text metrics (Flesch Reading Ease, word count, etc.) are computed per-stage.

## Celery Workers

Async stage runs are fully offloaded to Celery task workers with Redis as the broker/backend. When execution completes, workers hit the central coordinator endpoint (`/api/workflow/callback`) to trigger the stateless `WorkflowEngine` transition evaluation.

### Setup

1. **Configure Redis URL** — copy `.env.example` to `.env` and set:

   ```dotenv
   # Local Redis (no auth)
   REDIS_URL=redis://localhost:6379/0

   # LAN Redis with password (no username)
   REDIS_URL=redis://:yourpassword@192.168.1.50:6379/0
   ```

2. **Start a worker** — from the repo root:

   ```bash
   REDIS_URL=redis://:yourpassword@192.168.1.50:6379/0 \
     .venv/bin/celery -A quill.celery_app worker --loglevel=info
   ```

   Expected output:

   ```
   [tasks]
     . quill.celery_app.run_stage_task

   [2026-...] Connected to redis://...
   celery@hostname ready.
   ```

   Worker concurrency is controlled by the `QUILL_MAX_WORKERS` env var (default: 2).

### Enqueue a task

```python
from quill.celery_app import run_stage_task

# Single stage
result = run_stage_task.delay(piece_id, stage, agent_set="default", chain=False)
print(result.get(timeout=120))   # blocks until done

# Full chain from a given stage
result = run_stage_task.delay(piece_id, stage, agent_set="default", chain=True)
```

The task returns a dict with `stage`, `decision`, `critique`, `loop_count`, and `error` keys.

### Connectivity tests

```bash
# Verify Redis is reachable (opt-in, skipped in normal suite)
QUILL_TEST_REDIS_LIVE=1 pytest tests/test_redis_connectivity.py -v
```

---

## Testing

**447 pytest tests** — all passing.

### Pytest

Unit and integration tests covering the API, pipeline, piece management, and agent system.

### Frontend Vitest Tests

Unit and JSDOM integration tests covering piece state updates, dynamic agent loading, and EventSource (SSE) stream handling.

```bash
npm test                          # run frontend unit tests
pytest                            # run backend unit + integration tests
```

## Dependencies

- Flask (API + template server)
- PyYAML (frontmatter + meta.yaml parsing)
- SQLAlchemy + Flask-SQLAlchemy + Flask-Migrate (PostgreSQL ORM + migrations)
- psycopg2-binary (PostgreSQL driver)
- LiteLLM (unified LLM provider interface)
- Celery + redis-py (distributed task queue — worker optional)
- Werkzeug ProxyFix (reverse proxy support)
- tenacity (retry logic for LLM calls)
