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

- [x] Trigger mode: run_chain on "Run Agent" — one click runs all remaining stages (review→done). User writes brief→outline→draft manually, then agent pipeline handles the rest.
- [x] Agent run history — RunLogger class, run-log.jsonl per piece, /api/pieces/<id>/run-log endpoint, UI toggle for visibility
- [x] Agent set management via API — POST /api/agents (create), DELETE /api/agents/<name> (delete), clone_from support
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
- [x] **Move stage inputs to pipeline config** — `stage_inputs` now lives in `workflows/default.yaml` and is loaded by `Pipeline` class. `_STAGE_INPUTS` removed from runner.py. Custom workflows can define their own input routing without code changes.
- [x] **Loop guardrails** — Metric degradation detection across loop iterations. Saves baseline snapshot on first loop, compares on subsequent loops. Forces advance if word count drops >30%, readability shifts >15pts, vocab diversity drops >10%, or passive voice increases >10pp.
- ~~**Prompt git-history in dashboard**~~ — Killed. Git CLI covers this.

## Phase 8 — Codebase Health

- [x] **OOP refactor of runner.py** — See docs/ADR-003-module-structure.md. Extracted 5 classes: RunLogger (66), MetricsService (159), PromptBuilder (137), RunManager (207), Piece enrichment. runner.py: 1103 → 648 lines. Each class in its own file under src/quill/.
- [ ] **Spike: expose system prompt to user** — System prompt includes date context, genre/type instructions, JSON decision format. Worth surfacing in the Run Log or debug panel? Spike to assess value vs. complexity.
- [x] **Research stage** — New pipeline stage between outline and draft. Fetches reference material from SearXNG. LLM generates search queries from brief+outline, results saved as-is to research.md. Configurable per flavor: non-fiction (required), fiction/default (optional). 1-hour cache TTL. Files: search_client.py, research_service.py, _run_research() in runner.py.

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

## Backlog (from research stage review)

- [ ] **Source verification stage** — New stage after research that validates whether the URLs in research.md actually contain the claimed content. Prevents the draft agent from citing snippets that misrepresent the source. Could use web_extract to fetch and compare.

## Issues from Ferret Protocol (10k word generation)

### Pipeline state management

- [ ] **Reject doesn't reset stage_states** — When rejecting a piece back to an earlier stage (e.g. done → draft), the stage_states for subsequent stages remain "ready". The advance endpoint sees them as complete and skips through without running agents. Reject needs to clear stage_states for all stages after the target.
- [ ] **Pipeline skips stages with stale "ready" state** — Related to above. After reject + re-advance, the pipeline auto-advances through review/revise/humanize because their stage_states say "ready". Each advance should re-run the agent if the stage file only has frontmatter (no body content).
- [ ] **run endpoint only runs on current_stage** — `POST /run` always runs on the piece's current_stage. There's no way to run a specific stage via the API (e.g. "re-run review even though I'm at polish"). Needed for re-running individual stages without reject+advance.

### Chaptered generation

- [ ] **Outline format varies between agent calls** — The outline agent generates different formats: `## I. Part 1: Title`, `## 1. Narrative Arc`, or `## Part 1: Title`. The chapter parser needs 3 fallback regexes. Should standardize the outline prompt to always use `## Part N: Title` format.
- [ ] **Outline dump becomes first chapter** — When `sc.input_content` contains the outline + brief + previous decisions, `_parse_chapters` splits on `## Part N` and the context assembler's separator (`=== 02_outline.md ===`) becomes the first chapter heading. Fixed with filter but fragile.
- [ ] **Bullet chapters have empty bodies** — `_parse_bullet_chapters` extracts headings from brief bullets but the body is empty (brief is just a list). The outline content should fill in the chapter bodies. Currently the LLM generates from the heading alone.
- [ ] **No section layer under chapters** — For 10k+ words, chapters themselves could benefit from scene breaks (### Scene 1, ### Scene 2). Would need another generation layer: chapter → sections → concatenate. Not recursive — hardcoded 2 levels max.
- [ ] **Research results not passed to chapter generation** — The research stage finds references, but these aren't included in per-chapter prompts. Each chapter gets the outline context but not the research findings.
- [ ] **No progress feedback during chaptered generation** — 5 chapters × 30-40s = 3 minutes of blocking API response. The user sees no intermediate progress. Should emit SSE events per chapter completion (already has `stage_llm_call` events but UI doesn't show them).

### Word count and quality

- [ ] **Per-chapter word count target too low** — With 5 chapters at `target_length / num_chapters` = 2000 words each, actual output averages ~1700. Need to bump the per-chapter target by 20% (e.g. 2400 for a 10k target).
- [ ] **Agent evaluates total word count, not per-chapter** — The evaluate call sees the full 8627-word draft and says "too short" (target 10k). But the issue is per-chapter length, not total. The evaluate prompt should note "this was generated as N chapters, each targeting M words."
- [ ] **debug_prompts clutters output** — Each chapter generates a separate prompt file (generate_ch1-prompt.md, generate_ch2-prompt.md, etc.). Should be a single combined debug file or use a subdirectory.

### Content quality observations

- [ ] **First chapter often starts with weather/atmosphere** — Multiple runs produced "The rain..." or "The midnight air..." openings. The generate prompt should include "start with action or dialogue, not weather description" for thriller genre.
- [ ] **Character names not carried between chapters** — Each chapter generation is independent. The LLM might use slightly different character descriptions across chapters. Should pass character sheet as persistent context.
- [ ] **Ending feels rushed** — Part 5 (The Retirement) is the shortest chapter. The LLM tends to compress resolutions. Should add "expand the ending — give each character a final moment" to the retirement chapter prompt.
