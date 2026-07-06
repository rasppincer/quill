# Spec: Frontend Layout, Editor Locking & Raw JSON Inspector

## Goal
Restructure the piece detail page to present the prompt text editor and the content editor side-by-side. Update the navigation logic to dynamically fetch prompts and save stage content. Implement UI locking during execution/auto runs, support a front-end Interrupt button, and add a collapsible raw JSON response viewer.

## Architectural Changes

### 1. New Backend Save Endpoint (`src/quill/blueprints/pieces.py`)
Add a PUT route `/api/pieces/<piece_id>/stages/<stage>` to allow saving stage content directly from the editor textarea:
- If the stage is `fresh` (state is `fresh`), the pasted/edited content is saved to the *preceding* stage's markdown file to establish input context.
- Otherwise, it is saved directly to the target stage's markdown file.
- Automatically updates the target stage state to `completed` and computes metrics if it is a content stage.

### 2. Frontend Layout Overhaul (`src/quill/templates/piece.html`)
- Remove the top-level `▶ Run Agent` button.
- Remove the separate brief editor section.
- Replace the single-pane `#stage-content` section with a responsive side-by-side layout:
  - **Left Pane (40% width)**: Editable prompt panel. Contains `<textarea id="prompt-editor">`, `<button class="btn primary" id="execute-btn">Execute</button>`, and a loading spinner.
  - **Right Pane (60% width)**: Content editor panel. Contains `<textarea id="content-editor">`, `<button class="btn success" id="save-content-btn">Save</button>`, and status indicators.
- Add a collapsible `<details>` element at the bottom of the page containing a `<pre id="raw-json-content">` to serve as the raw response JSON inspector.

### 3. Stage Navigation & Prompt Fetching (`src/quill/static/js/piece.js`)
- Always enable stage tabs (allow clicking any stage tab regardless of current progress).
- On tab navigation (`navigateToStage`), concurrently:
  - Fetch stage content and metrics from `/api/pieces/<piece_id>/stages/<stage>`. Load the content into the Content Editor.
  - Fetch the Jinja-rendered prompt from `/api/pieces/<piece_id>/prompt/<stage>`. Load the prompt text into the Prompt Editor.
  - Load the pretty-printed raw JSON from `<stage>.json` (if exists) into the Raw JSON Inspector.

### 4. UI Locking & Interrupt Toggles
- When a run is initiated (clicking Execute or Auto Pipeline):
  - Disable textareas (`#prompt-editor`, `#content-editor`).
  - Disable buttons (`#execute-btn`, `#save-content-btn`, `#advance-btn`, `#auto-btn`, `#trigger-select`, `#delete-piece-btn`).
  - Keep ONLY the `#interrupt-btn` active.
- Wire `#interrupt-btn` to:
  - POST to `/api/pieces/<piece_id>/interrupt`.
  - Discard current unsaved edits in both editors, reloading their states from the server.
  - Unlock the inputs once backend SSE event indicates run termination.

## Verification Plan

### Automated Tests
- Run tests in `tests/test_piece_state.py` to ensure database states and navigability pass correctly.
- Update `test_empty_stage_is_not_navigable` to match the always-enabled tab behavior (if `can_navigate` is modified to always return `True`).

### Manual Verification
- Access the Quill UI via browser.
- Navigate between completed and fresh stage tabs. Verify prompts and contents load dynamically.
- Try editing a prompt and clicking "Execute". Ensure editors lock, status updates, and raw response JSON is loaded at the bottom upon completion.
- Click "Interrupt" during execution and ensure state reverts and unlocks properly.
