# Quill — TODO

## Phase 1 — Core Pipeline MVP ✓

- [x] YAML metadata format (meta.yaml per piece)
- [x] Stage tracking (current_stage in meta.yaml)
- [x] Gold Collapse imported and run through full 9-stage pipeline
- [ ] CLI tool (`quill new`, `quill status`, `quill advance`)

## Phase 2 — API Server ✓

- [x] Flask API on port 8325
- [x] CRUD endpoints (list, detail, create, advance, reject)
- [x] /health endpoint
- [x] Systemd service (quill.service)
- [x] Nginx proxy at /quill/

## Phase 3 — Dashboard ✓

- [x] Pieces overview (stats cards, stage badges, progress bars)
- [x] Piece detail (pipeline visualization, advance/reject)
- [x] Pipeline info page
- [x] Create piece modal
- [x] Agents page (config viewer, prompt editor)
- [x] Run Agent button on piece detail

## Phase 4 — Agentic Pipeline ✓

- [x] Agent config loader (agent.py)
- [x] OpenAI-compatible LLM client — urllib, zero deps (llm.py)
- [x] Stage executor with critique-decide-loop (runner.py)
- [x] Default agent set (config.yaml + 5 prompt templates)
- [x] Agent API endpoints (list, config, prompt CRUD, run)
- [x] Loop tracking in meta.yaml (loop_history)
- [x] Response parser with JSON + heuristic fallback
- [ ] Agent execution testing with real API key
- [ ] Trigger mode: full_auto (chain on completion)
- [ ] Agent swap per piece (select agent set in meta.yaml)

## Phase 5 — Polish

- [ ] Agent run history page (dashboard: per-piece run log)
- [ ] Agent set management (create/delete sets via API)
- [ ] Prompt template versioning (git-backed)
- [ ] Bulk operations (run agent on all pieces at stage X)
- [ ] Export formats (PDF, EPUB, HTML)

## Backlog

- [x] Google Docs connector — push finished pieces to Google Docs (API auth, formatting, link sharing)
- [ ] Voice-to-brief pipeline (mic → Whisper → brief.md)
- [ ] Multi-author workflow (shared pieces, roles)
- [ ] Template library (brief templates per genre)
- [ ] Humanizer checklist script (word count vs outline)
- [ ] Consistency check (character names, timeline)
- [ ] Vocabulary diversity score
