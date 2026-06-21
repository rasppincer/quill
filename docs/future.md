# Future Ideas

## Advanced Mode — Atomic Agent Controls

**Status:** Shelved (not a task, revisit later)

The two-call approach (generate → evaluate) is architecturally sound but currently opaque to the user. An "Advanced" toggle on the piece detail page would expose the inner workings:

### What it does

When enabled, the single "Run Agent" button splits into atomic controls:

- **Run Generate** — fills the generate prompt template, calls LLM, writes to `{stage}.md`. No evaluation, no decision. User can inspect the output before proceeding.
- **Run Evaluate** — takes the current `{stage}.md`, fills the evaluate prompt template with the generated text, calls LLM, writes to `{stage}.decision.md`. Returns the decision (advance/loop_back) with critique.

This gives the user full control over the generate-evaluate loop:
1. Run generate → inspect output → if happy → run evaluate
2. If evaluate says loop_back → tweak the generate prompt → run generate again
3. If evaluate is too harsh → tweak the evaluate prompt → run evaluate again

### Why it matters

- **Debugging**: When loop_back happens, the user can see exactly what was generated and exactly what the evaluator judged. No black box.
- **Prompt iteration**: Separate generate and evaluate prompts means separate iteration cycles. Fix the writing prompt or fix the judging prompt — different concerns.
- **Trust**: The two-call approach was chosen for objectivity (LLMs are bad at grading their own work in one pass). Hiding one call undermines the design rationale.
- **Cost control**: User can generate once, evaluate multiple times with different evaluate prompts, or vice versa.

### Implementation sketch

- Global "Advanced" toggle (persisted in localStorage or user prefs)
- When ON: "Run Agent" becomes two buttons: "▶ Generate" and "⚖ Evaluate"
- New API endpoints: `POST /api/pieces/<id>/generate` and `POST /api/pieces/<id>/evaluate`
- Debug panel below the buttons shows the composed prompts (generate and evaluate)
- Evaluate prompt panel populates after generate completes (needs the generated text)
- The evaluate prompt should also be visible post-hoc: store it in `{stage}.evaluate-prompt.md` alongside the decision file

### Open questions

- Should "Advanced" mode also expose the evaluate prompt template for editing inline? (Like the prompt editor on the Agents page, but scoped to the current piece/stage)
- Should there be a "Run Both" button that does the full two-call in one click, even in advanced mode?
- Should the evaluate prompt be per-piece or per-flavor? (Currently per-flavor via `evaluate.prompt.md`)
