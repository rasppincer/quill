# Spec: Exposing Granular Chapter Stage Details

Expose individual chapter prompt executions, outputs, raw JSON payloads, and metrics under the parent piece detail page.

## Requirements

1. **Chapter Selector Line**: Render a second row of tabs/pills directly under the parent stage tabs if the parent piece has chapters (children).
2. **Contextual Display**:
   - The first tab is "Parent (Assembled)", which displays the overall combined/parent state of the stage.
   - The remaining tabs are the individual chapters (e.g. "Chapter 1", "Chapter 2", etc.).
3. **Visibility rules**:
   - The chapter selector line is visible only for chaptered stages (`draft`, `review`, `revise`, `humanize`, `validate`, `polish`, `state`).
   - For non-chaptered stages (e.g. `brief`, `structure`, `outline`, `research`), the selector line is hidden.
4. **Data Syncing**:
   - Clicking a chapter pill dynamically loads the prompt, content, metrics, and raw JSON response for that specific child piece.
   - Saving content in the editor for a chapter saves it to the child piece and automatically re-assembles the parent piece's stage file.

## Architecture & Interface Details

### Frontend UI

* **Template (`src/quill/templates/piece.html`)**:
  - Add the `#chapter-tabs` container block under `#stage-tabs` if `piece.children` is non-empty.
  
* **Styles (`src/quill/static/css/dashboard.css`)**:
  - Add classes `.chapter-tabs` and `.chapter-tab`. Use rounded pills with smaller text (12px) to distinguish them visually from the stage tabs.
  - Active tab receives a distinctive class `.active` with light purple background tint (`rgba(188, 140, 255, 0.1)`) and purple borders.

* **Behavior (`src/quill/static/js/piece.js`)**:
  - Define `SELECTED_PIECE_ID` globally, defaulting to `PIECE_ID`.
  - In `navigateToStage(stage)`, toggle `#chapter-tabs` visibility:
    - If the stage is one of `CHAPTERED_STAGES`, show the tabs. If `SELECTED_PIECE_ID` is not the parent or any child of the parent (e.g., reset case), default to parent.
    - If not a chaptered stage, reset `SELECTED_PIECE_ID` to `PIECE_ID` (the parent), make the "Parent (Assembled)" tab active, and hide the selector container.
  - Define `selectChapter(chapterId)`:
    - Update `SELECTED_PIECE_ID` (either `PIECE_ID` for parent or the child ID).
    - Update active tab classes.
    - Re-fetch prompt, content, metrics, and raw JSON using `SELECTED_PIECE_ID`.
  - Update `saveContent()` and `executeStage()` to fetch/post using `SELECTED_PIECE_ID`.

### Backend API

* **Routing (`src/quill/blueprints/pieces.py`)**:
  - In `pieces_stage_save` (the `PUT` endpoint), check if `piece.parent` is set.
  - If a parent exists, load the parent piece and its children.
  - Call `Orchestrator._assemble_outputs` to re-concatenate all chapter outputs into the parent's stage file, ensuring that editing child content updates the parent instantly.
  - Also update the parent's database record (`StageState.body`) with the new assembled content and commit the session.

## Verification Plan

### Automated Tests
- Verification tests will verify that:
  - Saving a child piece automatically calls `_assemble_outputs` on the parent.
  - Parents and children database stage states are in sync.

### Manual Verification
- Deploy/run the Flask server locally.
- Create a multi-chapter project.
- Navigate to the `draft` stage and select different chapters to confirm details (prompts, content, raw JSON, metrics) render correctly.
- Edit a chapter, save it, and verify that the parent's assembled content is correctly updated.
