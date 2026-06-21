# Quill — TODO

## Phase 1 — Core Pipeline MVP ✓

- [x] YAML metadata format (meta.yaml per piece)
- [x] Stage tracking (current_stage in meta.yaml)
- [x] Gold Collapse imported and run through full 9-stage pipeline

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
- [x] Agent swap per piece (agent_set in meta.yaml, dropdown on piece detail)
- [x] Non-fiction agent set (separate prompts for blog/essay review, validate, humanize, polish)
- [x] Global model config (agents/model.yaml) — decoupled from agent sets
- [x] Model selector on Agents tab (fetches models from LLM server)
- [x] Agent flavor selector on piece detail (dropdown, filtered by stage)

## Phase 5 — Polish

- [ ] Trigger mode: run_chain on "Run Agent" — one click runs all remaining stages (review→done). User writes brief→outline→draft manually, then agent pipeline handles the rest.
- [ ] Agent run history (per-piece run log in meta.yaml, toggle via config)
- [ ] Agent set management via API (create/delete sets) — low priority
- [x] Text metrics — per-stage, stored as `{stage}.metrics.yaml` alongside each stage file
  - Metrics: Flesch Reading Ease, Flesch-Kincaid Grade, word count, avg sentence length, type-token ratio, passive voice %
  - Computed mechanically (no LLM), injected into agent prompts so agents can react to readability regressions
  - Trigger: on advance or run_agent, compare `{stage}.md` mtime vs `{stage}.metrics.yaml` — recompute if content changed
  - UI: piece detail shows metrics for current stage only
  - Content stages only (draft, revise, humanize, polish) — feedback stages (review, validate) don't need metrics

## Phase 6 — Quality

- [x] Backend unit tests (109 tests, pytest, 0.67s)

## Backlog

- [x] Google Docs connector — push finished pieces to Google Docs (API auth, formatting, link sharing)
- [x] .env for secrets — api_key via QUILL_API_KEY env var, not in yaml
- [ ] Export formats (PDF, EPUB, HTML) — lowest priority, Google Docs covers most needs
- [ ] Multi-author workflow (shared pieces, roles) — lowest priority
- [x] Prompt template docs — how to view git history, roll back to earlier version (docs/PROMPTS.md)

## Killed (won't do)

- ~~CLI tool~~ — dashboard + API replace this
- ~~Prompt template versioning (git-backed)~~ — git already does this; add docs instead
- ~~Bulk operations~~ — no demand
- ~~Frontend behavioral tests~~ — tracked in one-ring project
- ~~Voice-to-brief~~ — tracked separately (STT/TTS pipeline)
- ~~Template library~~ — overlaps with agent sets
- ~~Humanizer checklist~~ — agent handles this in prompt
- ~~Consistency check~~ — agent handles this in prompt
