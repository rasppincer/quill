# Architecture — Quill Writing Workflow

## Overview

Quill is a writing workflow engine. It tracks long-form content through a multi-stage pipeline: brief → outline → draft → review → humanize → validate → polish → done.

**This is a pure API server** — no frontend. The UI lives in the One Ring dashboard.

```
┌─────────────────────────────────────────────┐
│  API Server (Flask, port TBD)               │  app.py
│  JSON endpoints for pieces, stages, review  │
│  Standalone: http://localhost:<port>/api/   │
│  Via nginx:  /quill/api/                    │
├─────────────────────────────────────────────┤
│  Pipeline Engine                            │  pipeline.py
│  Stage tracking, transitions, validation    │
├─────────────────────────────────────────────┤
│  Review Scripts                             │  scripts/
│  Humanizer checklist, consistency, vocab    │
├─────────────────────────────────────────────┤
│  Piece Storage                              │  output/
│  Markdown with YAML frontmatter             │
│  Brief + outline + draft + review notes     │
└─────────────────────────────────────────────┘
```

## Piece Format

Each piece is a markdown file with YAML frontmatter:

```yaml
---
title: "Златото на Заклинателя"
genre: fiction
type: story
audience: PoE 2 gamers, Bulgarian readers
tone: thriller
language: bg
target_length: "10000+"
current_stage: draft
created: "2026-06-11"
updated: "2026-06-11"
---
```

## Stage Transitions

```
brief ──▶ outline ──▶ draft ──▶ review ──▶ humanize ──▶ validate ──▶ polish ──▶ done
                                                        ▲                │
                                                        └────────────────┘
                                                          (iterate if needed)
```

- Each transition is explicit (API call or CLI command)
- Review can bounce back to draft
- Humanize can bounce back to review
- Validate can bounce back to humanize or draft

## API Endpoints (planned)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service info + available endpoints |
| `/health` | GET | Health check |
| `/api/pieces` | GET | List all pieces + current stages |
| `/api/pieces/<id>` | GET | Piece detail (brief, outline, draft, notes) |
| `/api/pieces` | POST | Create new piece from brief |
| `/api/pieces/<id>/advance` | POST | Advance to next stage |
| `/api/pieces/<id>/review` | GET | Get review checklist status |
| `/api/pieces/<id>/review` | POST | Submit review notes |
| `/api/pieces/<id>/validate` | POST | Run validation checks |

## Dependencies

- Flask (API server)
- PyYAML (frontmatter parsing)
- Pytest (tests)
- Systemd (service management)
- nginx (reverse proxy via One Ring pattern)
