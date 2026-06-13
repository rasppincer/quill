# Quill — Writing Workflow Engine

A structured pipeline for producing long-form content: stories, articles, blogs, editorials, essays. Turns the one-shot "dump 10K words" approach into a multi-stage workflow with review, edit, and validation passes.

## Origin

Born from the Gold Collapse experience (~/stories/poe2-gold-collapse.md) — a 5,162-word Bulgarian-language short story written in a single voice-to-text session. The story worked conceptually but the process had no review cycle, no fact-checking, no humanize pass, and the word count target drove padding over quality.

## Workflow

```
┌─────────┐    ┌──────────┐    ┌───────┐    ┌────────┐    ┌──────────┐    ┌──────────┐    ┌───────┐
│  BRIEF  │───▶│ OUTLINE  │───▶│ DRAFT │───▶│ REVIEW │───▶│ HUMANIZE │───▶│ VALIDATE │───▶│ POLISH│
│         │    │          │    │       │    │        │    │          │    │          │    │       │
│ Topic   │    │ Sections │    │ Write │    │ Struct │    │ Strip    │    │ Fact-    │    │ Final │
│ Audience│    │ Pacing   │    │ chunks│    │ Pacing │    │ AI-isms  │    │ check   │    │ pass  │
│ Tone    │    │ Flow     │    │       │    │ Logic  │    │ Add voice│    │ Domain  │    │       │
│ Length  │    │ Beats    │    │       │    │ Quality│    │          │    │ accuracy│    │       │
└─────────┘    └──────────┘    └───────┘    └────────┘    └──────────┘    └──────────┘    └───────┘
     │                                                       │                │
     │              ◀──── iterate if needed ─────────────────┘                │
     │              ◀─────────────────────────────────────────────────────────┘
```

### 1. BRIEF
Define what you're writing before writing it.
- **Topic/subject** — what is this piece about?
- **Genre** — fiction (thriller, sci-fi, literary), non-fiction (blog, editorial, analysis, tutorial)
- **Audience** — who reads this? gamers? traders? general public?
- **Tone** — thriller, casual, academic, investigative, personal essay
- **Target length** — word count range (not a hard ceiling — substance over padding)
- **Language** — English, Bulgarian, mixed?
- **Key constraints** — must include X, must avoid Y, must be Z

### 2. OUTLINE
Structure before prose. Prevents the "write and hope" pattern.
- Chapter/section titles with 1-2 sentence descriptions
- Pacing notes (where to accelerate, where to slow down)
- Key beats per section (what happens, what's revealed)
- Character/argument arcs across sections
- Estimated word count per section (loose guide)

### 3. DRAFT
Write in chunks, not all at once.
- One section at a time using `write_file` (first) + `patch` (subsequent)
- Verify no truncation after each write
- Follow the outline but allow organic detours
- Use long-form-writing skill patterns for chunk management

### 4. REVIEW
Structural and quality review. This is where most one-shot writing fails.
- **Pacing** — does the story/article breathe? Too rushed? Too slow?
- **Logic** — do events/arguments follow? Plot holes? Missing links?
- **Character/voice consistency** — does the protagonist sound the same throughout?
- **Completeness** — are all outline beats hit? Anything missing?
- **Redundancy** — repeated scenes, arguments, or phrases?
- **Ending** — does it land? Is it earned?

### 5. HUMANIZE
Strip AI-isms and inject personality. Uses the humanizer skill (29 patterns).
- Remove AI vocabulary (tapestry, delve, vibrant, pivotal, etc.)
- Remove structural tells (rule of three, em dash overuse, bold headers)
- Add voice (opinions, varied rhythm, specific feelings)
- Match the target language's natural prose (not translated-from-English)
- Final anti-AI audit pass

### 6. VALIDATE
Domain-specific fact checking.
- **Fiction** — game references correct? Trading terminology accurate? Cultural details right?
- **Non-fiction** — sources cited? Claims verifiable? Numbers accurate?
- **Language** — native speaker review for non-English text
- **Consistency** — names, dates, places consistent throughout?

### 7. POLISH
Final pass before considering the piece done.
- Line-level edits (word choice, rhythm, flow)
- Formatting (headers, breaks, emphasis)
- Title and opening paragraph (the most important 200 words)
- Final word count (don't pad — if it's 7K and complete, it's 7K)

## API (planned)

Track pieces through the pipeline:
```
GET  /api/pieces                    — list all pieces + their current stage
GET  /api/pieces/<id>               — piece detail (brief, outline, current draft)
POST /api/pieces                    — create new piece from brief
PUT  /api/pieces/<id>/stage         — advance to next stage
GET  /api/pieces/<id>/review        — get review notes
POST /api/pieces/<id>/validate      — run validation checks
```

## Directory Structure

```
quill/
├── README.md              ← you are here
├── TODO.md                ← outstanding tasks
├── app.py                 ← Flask API server (port TBD)
├── docs/
│   └── ARCHITECTURE.md    ← technical details
├── templates/
│   ├── brief.md           ← brief template
│   ├── outline.md         ← outline template
│   └── review.md          ← review checklist template
├── workflows/
│   └── default.yaml       ← configurable pipeline stages
├── scripts/
│   └── ...                ← utility scripts
└── output/
    └── ...                ← completed pieces (markdown)
```

## Conventions

- Pieces are markdown files with YAML frontmatter (metadata + stage tracking)
- Each stage produces a review artifact (notes, checklist results)
- The API is pure JSON — no frontend (One Ring dashboard owns UI)
- Works standalone or via nginx
