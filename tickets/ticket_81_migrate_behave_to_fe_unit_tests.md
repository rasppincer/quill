# Ticket 81: Migrate Frontend-related Behave Tests to Frontend Unit Tests

## Description
Establish a frontend unit testing environment (e.g., Vitest/Jest with JSDOM) and migrate behave scenarios that check user interface behaviors (such as button states) into true frontend unit tests.

## Background
Currently, several BDD scenarios in `features/api/pipeline_navigation.feature` verify user-facing interface behaviors, specifically:
- `Scenario: Auto trigger — run agent button is disabled while running`
- `Scenario: Auto trigger — advance button is disabled while running`

Since Behave tests run strictly against the backend HTTP API, they do not verify actual DOM states (e.g., `#run-agent-btn` or `#advance-btn` disabled attribute). Instead, they simulate this by invoking the backend `/api/pieces/<id>/run` and `/api/pieces/<id>/advance` endpoints and asserting that an HTTP error is returned. 

These tests are slow (requiring `@slow` background pipeline execution and polling) and do not actually test the frontend JavaScript logic in `src/quill/templates/piece.html` (such as `updateButtonStates()` or `navigateToStage()`). Introducing a modular JS test suite would allow testing UI logic in isolation without a running Flask server or heavy E2E Playwright infrastructure.

## Tasks
- [ ] Initialize and configure a JavaScript testing framework (e.g., Jest or Vitest with `jsdom`) in the project root.
- [ ] Refactor and extract the inline `<script>` contents from `src/quill/templates/piece.html`, `src/quill/templates/agents.html`, and `src/quill/templates/dashboard.html` into testable JS files under `src/quill/static/js/` (e.g., `piece.js`, `agents.js`).
- [ ] Write unit tests for frontend utilities:
  - [ ] Validate button enabling/disabling in `updateButtonStates()` under different trigger configurations (e.g., `auto`).
  - [ ] Validate modal interactions (Escape key and click-outside closures).
  - [ ] Validate `loadAgentsForStage(stage)` dynamic options injection.
  - [ ] Validate SSE stream handlers updating DOM classes on completion or interruption.
- [ ] Clean up/simplify `features/api/pipeline_navigation.feature` by removing the UI-focused scenarios (or updating them to test purely API/backend constraints rather than referencing UI button states).

## Success Criteria
- [ ] A JS test command (e.g., `npm test` or `vitest run`) runs successfully and executing unit tests passes.
- [ ] Frontend button state logic is verified directly in isolated unit/DOM tests.
- [ ] The behave test suite passes successfully.

## Priority
Medium

---
**Next Expected Ticket Number**: None
