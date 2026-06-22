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
- [x] Two-call approach — generate → evaluate, separate files ({stage}.md + {stage}.decision.md)
- [x] Configurable evaluate prompts per flavor (evaluate.prompt.md)
- [x] Jinja2 prompt templates — `{% if is_looping %}` conditionals, `_render_prompt()` with fallback
- [x] Two-file output — generated text and evaluation stored separately
- [x] Prefixed output filenames — 01_brief.md through 09_done.md, sorted by execution order
- [x] Debug prompt dump — `debug_prompts: true` writes actual prompts to files at runtime
- [x] Template variables — {{loop_count}}, {{is_looping}}, {{max_loops}} for loop-aware prompts
- [x] Debug prompt endpoint — GET /api/pieces/<id>/prompt/<stage> shows composed prompts
- [x] Metrics flow — removed from generate prompt, added to evaluate prompt for data-driven decisions

## Phase 5 — Polish

- [ ] Trigger mode: run_chain on "Run Agent" — one click runs all remaining stages (review→done). User writes brief→outline→draft manually, then agent pipeline handles the rest.
- [ ] Agent run history (per-piece run log in meta.yaml, toggle via config)
- [ ] Agent set management via API (create/delete sets) — low priority
- [x] **Chain run error UX** — Chain now skips stages without agent prompts and continues to the next stage. Errors only if ALL remaining stages lack prompts.
- [x] **Word count preservation in agent prompts** — Added "expand rather than condense" instructions to revise/humanize prompts in both default and fiction agent sets.
- [x] **Outline/draft agent prompts** — Created outline.prompt.md and draft.prompt.md for both default and fiction agent sets, updated config.yaml files, added to runner content_stages + _STAGE_INPUTS.
- [x] **Review agent output format** — Added _format_feedback() method that strips JSON code fences, writes clean markdown to review.md.
- [x] **Reading level regression** — Added Flesch-Kincaid grade 8-10 target instruction to humanize prompts in both agent sets.
- [x] **body_length=0 in piece detail API** — Fixed: falls back to latest stage file with content when current stage file is missing. Regression test added.
- [x] Text metrics — per-stage, stored as `{stage}.metrics.yaml` alongside each stage file
  - Metrics: Flesch Reading Ease, Flesch-Kincaid Grade, word count, avg sentence length, type-token ratio, passive voice %
  - Computed mechanically (no LLM), injected into agent prompts so agents can react to readability regressions
  - Trigger: on advance or run_agent, compare `{stage}.md` mtime vs `{stage}.metrics.yaml` — recompute if content changed
  - UI: piece detail shows metrics for current stage only
  - Content stages only (draft, revise, humanize, polish) — feedback stages (review, validate) don't need metrics

## Phase 6 — Quality

- [x] Backend unit tests (276 tests, pytest, 2.2s)
- [x] Dashboard E2E tests (Playwright) — 28 tests: dashboard, piece detail, agents page, JS errors, API paths, interaction

## Phase 7 — Architecture (from DESIGN_REPORT.md)

### High Priority
- [x] **Content stripping safety** — `_strip_json_block()` now only strips trailing JSON decision blocks using `rfind`. JSON code examples in content preserved.
- [x] **Structured JSON outputs** — `response_format: {"type": "json_object"}` support via `structured_output: true` in model.yaml. Falls back to regex parsing.
- [x] **Async execution worker** — RunManager with ThreadPoolExecutor(2), SSE at `/runs/<id>/events`, live log panel in dashboard.

### Low Priority
- [ ] **Move stage inputs to pipeline config** — `_STAGE_INPUTS` in runner.py is hardcoded Python. Move to `workflows/default.yaml` so custom stages (Research, SEO) get proper input routing without code changes.
- [x] **Loop guardrails** — Metric degradation detection across loop iterations. Saves baseline snapshot on first loop, compares on subsequent loops. Forces advance if word count drops >30%, readability shifts >15pts, vocab diversity drops >10%, or passive voice increases >10pp.
- [ ] **Prompt git-history in dashboard** — Show git diffs of `.prompt.md` files in the Agents tab so writers can rollback templates without leaving the UI.

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
