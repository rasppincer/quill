# Chapter-Aware Long-Form Generation

*Design document — 2026-06-24*

## Problem

LLMs degrade on long outputs. A single draft call for a 10K+ word piece produces:
- Degraded quality in later sections (model "forgets" earlier setup)
- Context window pressure (outline + brief + research + prompt + max_tokens compete)
- No way to critique individual chapters in isolation
- Character/plot inconsistencies across sections

## Core Insight

The bottleneck is **generation**, not critique. Review/revise stages read and critique — they don't generate 10K words. So we only need to break up the generation, not the whole pipeline.

The real problem isn't "how to split text" — it's **context management across a long narrative**. Each chapter needs enough awareness of previous chapters to be coherent, without overwhelming the context window.

## Architecture

Three layers:

### 1. Narrative State Machine

Structured data that tracks the story — not just freeform text.

```python
@dataclass
class NarrativeState:
    characters: dict[str, Character]   # name, description, relationships, arc
    locations: dict[str, Location]     # name, description, significance
    plot_threads: list[PlotThread]     # status: open/resolved/abandoned
    timeline: list[Event]              # chronological events so far
    style_profile: str                 # extracted writing style from first chapter
    unresolved: list[str]              # open questions, foreshadowing
```

Maintained as a JSON file alongside the piece. After each chapter, an LLM call updates it. This is the "memory" that prevents inconsistency — character deaths, location details, plot threads.

### 2. Hierarchical Generation

```
Story concept (user input in brief)
    → Story outline (LLM: 3-5 paragraph synopsis)
        → Chapter outlines (LLM: one per chapter, 200-400 words each)
            → Section outlines (LLM: per section within chapter)
                → Prose generation (LLM: per section, 1000-2000 words)
```

Each level is a separate LLM call with bounded output. Outline levels are cheap (few tokens) and give user control points — edit at any level before proceeding.

### 3. Context Assembly

For generating chapter N, section M:

```
context = (
    story_outline                          # ~500 tokens — the big picture
    + chapter_outlines[N-1:N+1]           # ~400 tokens — adjacent chapter outlines
    + narrative_state.summary()            # ~300 tokens — structured memory
    + previous_sections_in_chapter[:M]     # ~1000 tokens — what came before in this chapter
    + chapter_summaries[N-3:N-1]          # ~200 tokens — recent chapter summaries
    + style_guide                         # ~200 tokens — extracted style
)
# Total: ~2600 tokens — leaving plenty of room for output
```

Key: never put full text of previous chapters in context. Use structured state + summaries. The narrative state machine gives precision (character names, plot points) while summaries give flow.

## Pipeline Integration with Quill

### Option A: Single piece, chapter-aware draft (recommended start)

```
brief → outline → research → [draft_ch1, draft_ch2, ..., draft_chN] → compose → review → revise → ... → polish
```

- Outline produces chapter structure (markers like `## Chapter 1: Title`)
- Draft stage detects chapters and generates per-chapter with context assembly
- Each chapter gets generate → evaluate (two-call approach)
- Per-chapter summary generated after each draft (lightweight LLM call)
- Chapters composed into `03_draft.md` after all complete
- Review/revise run on composed draft (they're feedback stages, not generation)

**Per-chapter context window:**
```
system prompt (~500 tokens)
+ chapter outline section (~300 tokens)
+ previous chapter summaries (~400 tokens)
+ brief excerpt (~200 tokens)
+ narrative state summary (~300 tokens)
+ max_tokens for output (~4000 tokens)
= ~5700 tokens total
```

**Files per piece:**
```
03_draft_ch01.md           # individual chapter drafts
03_draft_ch02.md
03_draft_ch01.summary.md   # chapter summaries (context for next)
03_draft_ch02.summary.md
narrative_state.json       # structured story memory
03_draft.md                # composed full draft
```

### Option B: Collection of pieces (more complex, more flexible)

- A "collection" piece defines the overall story structure
- Each chapter is a separate Quill piece linked to the collection
- Each chapter gets its own full pipeline run
- Context passed via: master outline + narrative state + previous chapter summaries
- After all chapters polished, a "compose" step assembles them

More flexible but requires managing relationships between pieces and a coordination layer.

### Option C: Hybrid — single piece with per-chapter feedback

- Draft generates per-chapter (same as Option A)
- Review/revise also run per-chapter (not on full file)
- Each chapter gets its own critique loop
- Final polish runs on assembled file

Best quality but most complex. Each chapter gets full two-call treatment at every stage.

## Implementation Plan

### Phase 1: Chapter-aware draft (Option A)

| Change | Where | Effort |
|---|---|---|
| `chapters: true` field in meta.yaml | `piece.py` | Small |
| `parse_chapters(outline)` utility | New `chapter_parser.py` | Medium |
| `summarize_chapter(chapter_text)` utility | `chapter_parser.py` | Small |
| `NarrativeState` dataclass + update | New `narrative_state.py` | Medium |
| Chapter-aware draft logic in `_run_content_stage` | `runner.py` | Medium |
| Compose step after all chapters | `runner.py` new `_compose_chapters` | Small |
| Chapter progress in SSE events | `run_manager.py` | Small |
| UI: chapter progress indicator | `piece.html` | Small |

### Phase 2: Narrative state tracking

| Change | Where | Effort |
|---|---|---|
| State extraction from brief + outline | `narrative_state.py` | Medium |
| State update after each chapter | `narrative_state.py` | Medium |
| State summary injection into prompts | `runner.py` | Small |
| Consistency check stage (optional) | New stage or sub-call | Medium |

### Phase 3: Quality & UX

| Change | Where | Effort |
|---|---|---|
| Per-chapter critique loop | `runner.py` | Medium |
| Style extraction from first chapter | `narrative_state.py` | Small |
| Chapter-level advance/reject | `piece.html` | Medium |
| Chapter comparison view | `piece.html` | Medium |

## Edge Cases

- **Outline has no chapter markers** → falls back to normal single draft
- **Chapter too short (< 200 words)** → merge with next chapter
- **Chapter summary fails** → use last 200 words of chapter as summary
- **`chapters: false`** (default) → normal behavior, zero impact
- **Narrative state update fails** → use previous state, log warning
- **Context still too long** → truncate oldest chapter summaries first

## What This Does NOT Change

- The outline stage (already produces sections)
- The research stage
- The trigger behavior
- The two-call approach (each chapter still gets generate → evaluate)
- The review/revise/humanize/validate/polish stages (run on composed draft)

## Key Design Decisions

1. **Opt-in via `chapters: true`** — zero impact on existing pieces
2. **Structured state, not just text** — JSON narrative state prevents "dead character returns" bugs
3. **Sliding window context** — each chapter gets bounded, precise context
4. **Compose before feedback** — review/revise run on full draft (they're readers, not generators)
5. **Per-chapter summaries** — lightweight LLM call after each chapter, feeds next chapter's context
6. **No framework dependency** — Python + LLM API, ~500 lines of new code

## Future: DSPy Integration

The prose generation step could benefit from DSPy's automatic prompt optimization. If we collect 3-5 example chapters with quality ratings, DSPy could optimize the generation prompt automatically. Worth exploring after Phase 1 is stable.
