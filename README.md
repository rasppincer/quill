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

Stages 4-8 (review through polish) are **agent-driven**. Each stage has a prompt template and an LLM agent that:

1. **Reads** the previous stage's output
2. **Critiques** it (structured JSON response: advance/loop_back, summary, critique text)
3. **Decides** — advance to next stage, or loop back to redo the current stage
4. **Loops** up to `max_loops` times per stage (default: 3)

The user is only involved at the publish/scrap decision. Everything else is autonomous.

### Agent Sets

Agents are **swappable** — different agent sets for different genres or quality levels:

```
quill/agents/
└── default/
    ├── config.yaml              ← model, api_key, max_loops, trigger mode
    ├── review.prompt.md         ← review agent prompt
    ├── revise.prompt.md         ← revise agent prompt
    ├── humanize.prompt.md       ← humanize agent prompt
    ├── validate.prompt.md       ← validate agent prompt
    └── polish.prompt.md         ← polish agent prompt
```

- **Default set** — general-purpose writing critique
- **Sci-fi set** — stricter world-building validation, consistency checks
- **Editorial set** — publication-ready tone, fact-checking emphasis

Different pieces can use different agent sets. The prompt templates are fully editable via the dashboard.

### Trigger Modes

- **`run_on_advance`** — agent runs when you click "Run Agent" (manual trigger)
- **`full_auto`** — agent runs automatically on stage completion, chains through all remaining stages

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
│       ├── draft.md     ← The raw prose
│       ├── review.md    ← Reviewer annotations
│       ├── revise.md    ← Revised per review feedback
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
- Stage files contain only content (no YAML frontmatter)
- The API is pure JSON — dashboard templates are rendered by Flask
- Works standalone (port 8325) or via nginx (`/quill/`)
- ProxyFix handles `X-Forwarded-Prefix` for correct URL generation behind nginx
- Agent loop history tracked in `meta.yaml` under `loop_history`

## Dependencies

- Flask (API + template server)
- PyYAML (frontmatter + meta.yaml parsing)
- Werkzeug ProxyFix (reverse proxy support)
- No external LLM client dependencies — uses stdlib `urllib`
