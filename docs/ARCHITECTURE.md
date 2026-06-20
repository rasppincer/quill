# Architecture — Quill Writing Workflow Engine

## Overview

Quill is an **agentic writing workflow engine**. It runs long-form content through a multi-stage pipeline where stages 4-8 (review through polish) are executed by autonomous LLM agents. The user provides the brief and makes the final publish/scrap decision — everything in between is agent-driven.

**This is a pure API server** — no frontend. The UI lives in the One Ring dashboard.

```
┌─────────────────────────────────────────────┐
│  Dashboard (One Ring)                       │  /quill/dashboard
│  Jinja templates, served by Flask           │
├─────────────────────────────────────────────┤
│  API Server (Flask, port 8325)              │  app.py
│  JSON endpoints for pieces, agents, runs    │
│  Standalone: http://localhost:8325/api/     │
│  Via nginx:  /quill/api/                    │
├─────────────────────────────────────────────┤
│  Agent Runner                               │  runner.py
│  Critique → decide → loop logic             │
├─────────────────────────────────────────────┤
│  LLM Client                                 │  llm.py
│  OpenAI-compatible, urllib, zero deps       │
├─────────────────────────────────────────────┤
│  Pipeline Engine                            │  pipeline.py
│  Stage definitions, transitions, validation │
├─────────────────────────────────────────────┤
│  Piece Storage                              │  piece.py
│  Directory-per-piece, meta.yaml + stage .md │
└─────────────────────────────────────────────┘
```

## Pipeline

9-stage linear pipeline with iterate loop from polish→validate:

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

### Stage Responsibilities

Each stage is **atomic** — one concern per stage, one file per stage.

| Stage | File | Input | Output | Concern | Mode |
|-------|------|-------|--------|---------|------|
| brief | `brief.md` | — | metadata + constraints | Define what you're writing | manual |
| outline | `outline.md` | brief | structure, arcs, pacing | Structure before prose | manual |
| draft | `draft.md` | outline | raw prose | Write in chunks | manual |
| review | `review.md` | draft | annotations, feedback | Read, flag, annotate | **agent** |
| revise | `revise.md` | draft + review | revised prose | Apply review feedback | **agent** |
| humanize | `humanize.md` | revise | de-AI'd prose | Strip AI-isms, add voice | **agent** |
| validate | `validate.md` | humanize | fact-checked prose | Domain accuracy | **agent** |
| polish | `polish.md` | validate | final prose | Line-level edits | **agent** |
| done | `done.md` | polish | published version | Complete | manual |

### Transitions

- **Advance**: moves to next stage, preserves old stage file
- **Reject**: reverts to allowed previous stage, loads that stage's body
- **Loop**: polish can bounce back to validate for iterative refinement
- **Agent run**: agent critiques current stage, decides advance or loop_back

### Reject Paths

```
review   → draft
revise   → review, draft
humanize → revise
validate → humanize, revise
polish   → validate
```

## Agent System

The agent system is the core of Quill's evolution from a tracking tool to an autonomous writing app.

### Flow

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Load     │───▶│ Call LLM │───▶│ Parse    │───▶│ Decide   │
│ prompt + │    │ (critique│    │ response │    │ advance  │
│ prev     │    │  stage)  │    │ (JSON)   │    │ or loop  │
│ content  │    │          │    │          │    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                      │
                                            ┌─────────┴─────────┐
                                            │                   │
                                       advance             loop_back
                                       (next stage)        (retry ≤ max_loops)
```

### Agent Config (`agents/<set>/config.yaml`)

```yaml
name: default
model: "gpt-4o"
api_base: "https://api.openai.com/v1"
api_key: "[REDACTED]"
max_loops: 3
trigger:
  review: run_on_advance
  revise: run_on_advance
  humanize: run_on_advance
  validate: run_on_advance
  polish: run_on_advance
```

- **`model`** — any OpenAI-compatible model name
- **`api_base`** — works with OpenAI, Anthropic (via proxy), local (llama.cpp server, vLLM)
- **`max_loops`** — max retries per stage before forcing advance (default: 3)
- **`trigger`** — per-stage mode: `run_on_advance` (manual) or `full_auto` (chain on completion)

### Prompt Templates (`agents/<set>/<stage>.prompt.md`)

Each agent stage has a prompt template with `{content}` and `{context}` placeholders. Templates are fully editable via the dashboard or API (`PUT /api/agents/<set>/<stage>/prompt`).

### LLM Client (`llm.py`)

- OpenAI-compatible chat completions API
- Uses stdlib `urllib` — **zero external dependencies**
- Configurable `api_base` for any provider
- Streaming not required (critique responses are short)

### Response Format

Agents return structured JSON:

```json
{
  "action": "advance",        // or "loop_back"
  "loop_count": 1,
  "summary": "Brief summary of what was done",
  "critique": "Full analysis text..."
}
```

If the LLM returns malformed JSON, `agent.py` falls back to heuristic parsing (looks for "advance" or "loop_back" keywords).

### Loop Tracking

Loop history is recorded in `meta.yaml`:

```yaml
loop_history:
  review:
    - loop: 1
      action: advance
      summary: "Prose is solid, minor pacing issues noted"
  validate:
    - loop: 1
      action: loop_back
      summary: "Found inconsistent currency references"
    - loop: 2
      action: advance
      summary: "All references verified"
```

## File Structure

Each piece lives in its own directory under `output/`:

```
quill/output/
└── <piece-id>/
    ├── meta.yaml        ← source of truth (current_stage, metadata, loop_history)
    ├── brief.md         ← brief content
    ├── outline.md       ← structure, arcs, pacing map
    ├── draft.md         ← the actual prose
    ├── review.md        ← reviewer annotations + feedback
    ├── revise.md        ← draft revised per review feedback
    ├── humanize.md      ← de-AI'd version
    ├── validate.md      ← fact-checked version
    ├── polish.md        ← final line edits
    └── done.md          ← published version
```

### meta.yaml

Single source of truth for piece metadata and current stage. Updated on every save and agent run.

```yaml
id: gold-collapse
title: Gold Collapse
genre: fiction
type: story
audience: PoE 2 gamers, Bulgarian readers
tone: thriller
language: bg
target_length: "10000+"
constraints: []
current_stage: review
agent_set: default
created: '2026-06-19'
updated: '2026-06-19'
loop_history: {}
```

### Stage Files

Each `<stage>.md` contains the content for that stage. No YAML frontmatter needed — metadata lives in `meta.yaml`. The body is everything in the file.

### Backward Compatibility

Legacy single-file pieces (`output/<id>.md`) are still supported. The loader detects format automatically:
- Directory with `meta.yaml` → new format
- Single `.md` file → legacy format

## API Endpoints

### Pieces

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Redirect to dashboard |
| `/health` | GET | Health check |
| `/api/pieces` | GET | List all pieces + current stages |
| `/api/pieces/<id>` | GET | Piece detail (metadata, stages, progress) |
| `/api/pieces` | POST | Create new piece from brief |
| `/api/pieces/<id>/advance` | POST | Advance to next stage |
| `/api/pieces/<id>/reject` | POST | Revert to previous stage (JSON body: `target`) |
| `/api/pipeline` | GET | Pipeline stage definitions |

### Agents

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agents` | GET | List all agent sets |
| `/api/agents/<set>` | GET | Agent set config + prompt list |
| `/api/agents/<set>/<stage>/prompt` | GET | Read prompt template |
| `/api/agents/<set>/<stage>/prompt` | PUT | Update prompt template |
| `/api/pieces/<id>/run` | POST | Run agent on current stage |
| `/api/pieces/<id>/run` | POST | Run all stages (`{"chain": true}`) |

## Dependencies

- Flask (API + template server)
- PyYAML (frontmatter + meta.yaml parsing)
- Werkzeug ProxyFix (nginx reverse proxy support)
- Systemd (service management)
- nginx (reverse proxy at `/quill/`)
- **No external LLM client dependencies** — stdlib urllib
