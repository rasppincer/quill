# Quill — TODO

## Phase 1: Core Pipeline (MVP)
- [ ] Create piece metadata format (YAML frontmatter spec)
- [ ] Build CLI tool: `quill new` (from brief template), `quill status`, `quill advance`
- [ ] Implement stage tracking (piece progresses through brief→outline→draft→review→humanize→validate→polish→done)
- [ ] Import Gold Collapse as first piece (retrofit brief + outline from existing text)

## Phase 2: API Server
- [ ] Flask API on designated port (JSON only, no frontend)
- [ ] Endpoints: CRUD pieces, stage management, review notes
- [ ] /health endpoint
- [ ] Systemd user service
- [ ] nginx proxy_pass config

## Phase 3: Review Automation
- [ ] Script: run humanizer checklist against a draft (regex + pattern matching for AI-isms)
- [ ] Script: word count per section vs outline estimates
- [ ] Script: consistency check (names, places, dates mentioned in text)
- [ ] Script: vocabulary diversity score (flag overused words)

## Phase 4: One Ring Integration
- [ ] Dashboard widget showing pieces + their current stage
- [ ] Stage progress bars per piece
- [ ] Quick-advance buttons from dashboard

## Backlog
- [ ] Voice-to-brief pipeline (speak a concept → structured brief)
- [ ] Export to formats (PDF, EPUB, HTML)
- [ ] Multi-author workflow (assign review stages to different agents)
- [ ] Template library for different genres (thriller, blog, editorial, technical)
