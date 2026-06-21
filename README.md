# Quill — Agentic Writing Workflow Engine

A structured pipeline for producing long-form content: stories, articles, blogs, editorials, essays. Turns the one-shot "dump 10K words" approach into a multi-stage workflow with **autonomous agent-driven review, revision, and validation**.

## Origin

Born from the Gold Collapse experience (~/stories/poe2-gold-collapse.md) — a 10,000+ word Bulgarian-language short story written in a single session. The story worked conceptually but the process had no review cycle, no fact-checking, no humanize pass, and the word count target drove padding over quality.

## The Pivot

Quill started as a **tracking pipeline** — manual advance/reject buttons, no automation. Now it's an **agentic writing app**: agents critique, decide, and loop autonomously. The user only touches the final product (publish or scrap). Everything in between is agent-driven.

## Workflow

```
┌─────────┐   ┌──────────┐   ┌───────┐   ┌────────┐   ┌────────┐   ┌──────────┐   ┌──────────┐   ┌───────┐   ┌──────┐
│  BRIEF  │──▶│ OUTLINE  │──▶│ DRAFT │──▶│ REVIEW │──▶│ REVISE │──▶│ HUMANIZE │──▶│ VALIDATE │──▶│ POLISH│──▶│ DONE │
│         │   │          │   │       │   │        │   │        │   │          │   │          │   │       │   │      │
│ Topic   │   │ Sections │   │ Write │   │ Read + │   │ Apply  │   │ Strip    │   │ Fact-    │   │ Final │   │      │
│ Audience│   │ Pacing   │   │ chunks│   │ annotate│  │ feedback│  │ AI-isms  │   │ check   │   │ pass  │   │      │
│ Tone    │   │ Flow     │   │       │   │ Flag   │   │ Revise │   │ Add voice│   │ Domain  │   │       │   │      │
│ Length  │   │ Beats    │   │       │   │ issues │   │ draft  │   │          │   │ accuracy│   │       │   │      │
└─────────┘   └──────────┘   └───────┘   └────────┘   └────────┘   └──────────┘   └──────────┘   └───────┘   └──────┘
                                                                              │                    ▲
                                                                              └── iterate ────────┘
```

Each stage is **atomic** — one concern per stage, one file per stage. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

### Stages

1. **Brief** — Define what you're writing (topic, audience, tone, constraints)
2. **Outline** — Structure before prose (sections, pacing, beats, arcs)
3. **Draft** — Write in chunks (follow outline, allow organic detours)
4. **Review** — Read and annotate (pacing, logic, consistency, completeness)
5. **Revise** — Apply review feedback to produce revised draft
6. **Humanize** — Strip AI-isms, inject personality, match language voice
7. **Validate** — Domain-specific fact checking (game refs, trading logic, cultural details)
8. **Polish** — Final line-level edits (word choice, rhythm, formatting)
9. **Done** — Published version

### Iterate Loop

Polish can bounce back to validate for iterative refinement. Each pass tightens the text without changing scope.

## Agent System

All stages (outline through polish) are **agent-driven**. The chain can run from brief→done fully automated. Each stage has a prompt template and an LLM agent that uses a **two-call approach**:

1. **Generate call** — reads the previous stage's output and produces the content for the current stage (e.g., outline from brief, draft from outline, review from draft). The generated text is written to `{stage}.md` immediately.
2. **Evaluate call** — a separate LLM call evaluates the generated content and returns a structured JSON decision: `advance` or `loop_back`, plus critique. The evaluation is written to `{stage}.decision.md`.
3. **Decides** — advance to next stage, or loop back to redo the current stage
4. **Loops** up to `max_loops` times per stage (default: 3)

On **loop_back**, the next iteration receives both the previous generated text (`{stage}.md`) and the evaluation feedback (`{stage}.decision.md`), so the agent can see what it wrote and what was wrong with it.

This two-file design eliminates the risk of losing generated content on loop_back and prevents LLM-generated content from accidentally triggering decisions via instructional text.

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
POST /api/pieces/<id>/run           — run agent on current stage
POST /api/pieces/<id>/run {"chain": true}  — run all remaining stages
```

## Dashboard

Frontend lives in the One Ring dashboard at `/quill/dashboard`. Four pages:

- **Pieces** — overview with stats cards, stage badges, progress bars
- **Piece detail** — pipeline visualization, advance/reject buttons, **Run Agent** button with live critique display
- **Agents** — agent set browser, config viewer, prompt editor
- **Pipeline** — stage definitions, file structure, conventions

## Conventions

- Pieces are directories with `meta.yaml` + per-stage `.md` files
- `meta.yaml` is the single source of truth for metadata and current stage
- Content stages produce two files: `{stage}.md` (generated text) and `{stage}.decision.md` (evaluation)
- Feedback stages produce one file: `{stage}.md` (critique, clean markdown)
- The API is pure JSON — dashboard templates are rendered by Flask
- Works standalone (port 8325) or via nginx (`/quill/`)
- ProxyFix handles `X-Forwarded-Prefix` for correct URL generation behind nginx
- Agent loop history tracked in `meta.yaml` under `loop_history`
- Text metrics (Flesch Reading Ease, word count, etc.) computed per-stage as `.metrics.yaml` files

## Testing

**233 pytest tests + 16 behave BDD scenarios** — all passing.

### Pytest

Unit and integration tests covering the API, pipeline, piece management, and agent system.

### Behave BDD

```
features/api/
├── pieces.feature          ← 8 scenarios (CRUD, rename, advance, reject, body length, duplicates)
├── agents.feature          ← 5 scenarios (chain runs, skip logic, output format)
├── steps/
│   └── pieces_steps.py     ← step definitions
└── environment.py          ← test hooks / cleanup
```

13 scenarios, 69 steps, all passing. Run with:

```bash
pytest                          # unit + integration tests
behave features/api/            # BDD scenarios
```

## Dependencies

- Flask (API + template server)
- PyYAML (frontmatter + meta.yaml parsing)
- Werkzeug ProxyFix (reverse proxy support)
- No external LLM client dependencies — uses stdlib `urllib`
