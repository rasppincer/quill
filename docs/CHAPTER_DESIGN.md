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

## Domain Knowledge Integration

*Design discussion — 2026-06-24*

### Problem

When a chapter involves a specific technical domain (intricate welding, neurosurgery, cryptographic protocols), the LLM needs domain knowledge to write credibly. Generic summaries aren't enough — the reader (or the evaluate call) will spot vague descriptions that lack specific parameters, named techniques, or scientific principles.

The user may have source material (research papers, technical manuals, reference documents) that contains the exact knowledge needed. How do we get that knowledge into the generation prompt?

### Approaches Considered

#### 1. Dump full text into prompt

**Verdict: Works for short sources, fails for anything substantial.**

A typical SAGE journal paper is 8-15K words (~12-20K tokens). With a 36K context window and ~14K tokens already allocated (system prompt, brief, outline, narrative state, chapter summaries, style guide, max_tokens for output), a full paper barely fits — and with 2 sources, it doesn't.

Deeper problem: even when it fits, the model treats the full paper as background noise. It doesn't know which parts are relevant to *this specific scene*. It skims the surface rather than diving into the parameters that matter.

**Good for:** 1-2 page reference snippets, short technical excerpts manually curated.

#### 2. Dump summary into prompt

**Verdict: Loses exactly what you need.**

For technical writing, the details ARE the point. A summary of a welding paper says "various additive manufacturing techniques are compared" — but what the chapter needs is "WAAM with GMAW uses 1.2mm wire at 180-220A, layer height 1.5mm, and interpass temperature must stay below 150°C for Inconel 718." Summaries strip the specifics that make technical writing credible.

**Good for:** Plot-level context ("Character X is a welder who specializes in aerospace repair"). Bad for domain knowledge.

#### 3. RAG with pre-extraction (query from outline)

**Verdict: Good retrieval, wrong timing.**

The problem is: *extract based on what?* At chapter generation time, you have an outline that says "Chapter 3: Marcus performs the critical weld repair on the reactor vessel." Queries derived from this are vague ("welding reactor vessel"). The actual chapter might need specific info about *Inconel 718 interpass temperatures* — which the outline doesn't mention.

The queries are derived from the outline (vague), not from the actual content being written (specific). You're predicting what the model will need before it writes.

**Good for:** When the outline is very detailed and you can predict exact technical needs. Requires significant manual curation.

#### 4. Generate → analyze → RAG → revise loop ← **recommended**

**Verdict: Best fit.**

This inverts the problem. Instead of predicting what knowledge the model needs before writing, you let the model *attempt* the chapter, then analyze what it got wrong or left vague, then retrieve exactly those specifics.

```
Generate draft → LLM identifies gaps ("I wrote 'the weld needed careful
temperature control' but I don't know the actual temperatures") →
queries RAG for "Inconel 718 interpass temperature GMAW" →
retrieves precise data → revises with specifics
```

**Why this works:** LLMs are much better at *recognizing* gaps in their own output than *predicting* gaps before writing. The generate step creates a "scaffold" that identifies exactly what domain details are needed. The RAG query is now precise (not a guess from the outline), and the revision is targeted.

### How It Maps to Quill's Architecture

This is just the existing two-call loop with a RAG pass between iterations.

```
Chapter 3 generation:
  Loop 0:
    Generate call → draft (with domain summary as context)
    Evaluate call → "The welding description is vague. Lacks specific
                     parameters. Temperature references are generic."
                     decision: loop_back

  Loop 1 (RAG-augmented):
    Analyze draft + critique → extract queries:
      "Inconel 718 GMAW parameters"
      "wire feed speed 1.2mm"
      "interpass temperature limits"
    RAG retrieval from domain KB → specific passages
    Generate call → revised draft (with RAG passages injected)
    Evaluate call → "Technical details now specific and credible."
                     decision: advance
```

No new pipeline stages needed. The RAG retrieval happens in the loop_back path of the runner — between the evaluate call returning `loop_back` and the next generate call.

### Implementation

#### Source Ingestion (one-time, at attach)

When the user attaches source files to a piece:

1. Extract text from PDF (pymupdf / marker-pdf)
2. Chunk into sections (~500-1000 tokens each), preserving section headers
3. Embed and store in a per-piece vector store
   - MVP: store as indexed markdown chunks with section headers (no embedding, keyword search)
   - Full: LanceDB with local embeddings (same infrastructure as transcript-wiki)
4. Generate a lightweight domain summary (~500 tokens) — key topics, techniques, terminology covered

Source metadata in `meta.yaml`:
```yaml
domain_sources:
  - path: welding-paper.pdf
    title: "Welding-Based Additive Manufacturing Processes"
    authors: "Rathinasuriyan et al."
    summary: "Reviews WAAM, GMAW, and laser welding for metallic part fabrication..."
    chunks: 47           # number of indexed chunks
    ingested: 2026-06-24
```

#### Context Assembly (updated)

The chapter context gains a `domain_context` slot:

```python
context = (
    story_outline                          # ~500 tokens
    + chapter_outlines[N-1:N+1]           # ~400 tokens
    + narrative_state.summary()            # ~300 tokens
    + previous_sections_in_chapter[:M]     # ~1000 tokens
    + chapter_summaries[N-3:N-1]          # ~200 tokens
    + style_guide                         # ~200 tokens
    + domain_context                      # ~500-2000 tokens (RAG-retrieved)
)
```

`domain_context` content varies by loop iteration:
- **Loop 0:** Domain summary only (~500 tokens). Gives the model a general awareness without overwhelming the context.
- **Loop 1+:** Domain summary + RAG-retrieved chunks from the previous critique. Precise, targeted passages.

#### RAG Retrieval Step (between evaluate and next generate)

On `loop_back` with domain sources attached:

```python
def _retrieve_domain_context(self, piece, stage, draft_text, critique):
    """Extract queries from draft + critique, retrieve from domain store."""
    if not piece.has_domain_sources():
        return ""

    # Extract key terms from critique (what the evaluator flagged as vague)
    queries = self._extract_domain_queries(draft_text, critique)
    # queries = ["Inconel 718 interpass temperature",
    #            "GMAW wire feed speed parameters",
    #            "WAAM layer height specifications"]

    # Retrieve relevant chunks
    chunks = piece.domain_store.search(queries, top_k=5, max_tokens=2000)

    # Format as context block
    if not chunks:
        return ""
    block = "=== Domain Reference Material ===\n\n"
    for chunk in chunks:
        block += f"**{chunk.section_header}** ({chunk.source_title})\n"
        block += chunk.text + "\n\n"
    return block
```

Query extraction can be:
- **MVP:** Regex extraction of technical-sounding noun phrases from the critique ("lacks specific parameters", "temperature references are generic") + named entities from the draft
- **Full:** Lightweight LLM call: "Given this critique, what specific technical details should I search for in my reference materials?" → returns a JSON array of search queries

#### Template Variable

New template variable: `{{DOMAIN_CONTEXT}}`

In generate prompts:
```markdown
{% if DOMAIN_CONTEXT %}
## Domain Reference Material
The following technical details from reference sources may be relevant.
Use them to add specificity and accuracy to the writing.

{{DOMAIN_CONTEXT}}
{% endif %}
```

### MVP vs Full

| Aspect | MVP | Full |
|--------|-----|------|
| Source format | PDF text extraction only | PDF, URL, markdown, plain text |
| Chunking | By paragraph/section headers | Semantic chunking (embedding-aware) |
| Search | Keyword matching on chunks | Vector similarity (LanceDB + embeddings) |
| Query extraction | Regex + named entities | LLM call (structured JSON queries) |
| Domain summary | Manual (user writes it) | LLM-generated from source |
| Storage | Markdown files in piece dir | LanceDB collection per piece |
| Context injection | Only on loop_back | Summary on loop_0, RAG on loop_back |

### Integration with Chapter Pipeline

The domain knowledge system layers onto the chapter architecture with minimal changes:

```
brief → outline → research → [domain_ingest] → [draft_ch1, draft_ch2, ...] → compose → review → ...
```

- `domain_ingest` is a preprocessing step (not a pipeline stage) — triggered when the user attaches sources
- Chapter draft loop naturally incorporates domain context via the existing loop_back mechanism
- Narrative state can track domain facts: "Marcus used GMAW with 1.2mm Inconel wire" — preventing the next chapter from contradicting the technical details
- Review/validate stages can flag domain inconsistencies: "Chapter 5 says MIG welding but Chapter 3 established GMAW"

### Edge Cases

- **Source too large to chunk** (>100 pages) → split into sections, each indexed separately
- **Source in non-English** → extract in original language, translate chunks at retrieval time if `language` differs
- **No domain sources** → `domain_context` is empty string, zero impact on existing behavior
- **RAG retrieves irrelevant chunks** → cap at 2000 tokens, evaluate call will flag if context was unhelpful
- **Domain summary is wrong** → user can edit it manually in `meta.yaml` or re-generate
- **Multiple sources contradict** → retrieve from both, let the model (and evaluate call) reconcile
- **User attaches sources mid-pipeline** → ingest runs on next stage execution, domain context available from that point forward

### What This Does NOT Change

- The two-call approach (generate → evaluate)
- The existing research stage (SearXNG web search)
- The trigger system
- The pipeline YAML structure
- Pieces without domain sources — zero impact

### Open Questions

1. **OKF / transcript-wiki integration** — if transcript-wiki uses LanceDB for YouTube transcripts, should domain sources for chapters share the same LanceDB instance? Per-piece isolation vs shared knowledge base.
2. **Source curation UX** — should the user be able to select specific chapters/sections of a source as relevant, or is automatic retrieval sufficient?
3. **Domain fact tracking** — should the narrative state machine track technical facts established in earlier chapters? ("Chapter 3 established GMAW at 180A — Chapter 7 must not contradict this.")
4. **Multi-modal sources** — some reference material has diagrams, tables, figures. How to handle non-text content in domain retrieval?

## Future: DSPy Integration

The prose generation step could benefit from DSPy's automatic prompt optimization. If we collect 3-5 example chapters with quality ratings, DSPy could optimize the generation prompt automatically. Worth exploring after Phase 1 is stable.
