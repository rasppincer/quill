# Spec: Migrate Frontend-related Behave Tests to Frontend Unit Tests

## Goal
Establish isolated frontend unit tests for complex UI behaviors, specifically testing button state management, EventSource (SSE) stream handling, and dynamic agent loading. Remove slow, flaky Behave BDD scenarios that rely on backend orchestration and LLM executions to test frontend button states.

## Architectural Changes

### 1. Remove BDD Scenarios from `features/api/pipeline_navigation.feature`
Delete the two scenarios that assert backend errors to simulate UI disabling behavior:
- `Scenario: Auto trigger — cannot manually run agent while auto running`
- `Scenario: Auto trigger — cannot manually advance stage while auto running`

### 2. Implement Frontend Agent Loading Tests (`tests/frontend/piece_agents.test.js`)
Create a new frontend test file focusing on `loadAgentsForStage(stage)` logic in `src/quill/static/js/piece.js`:
- Mock JSDOM document structure (specifically `#agent-select`, `#run-agent-btn`).
- Stub the global `fetch` API.
- Test that:
  - If stage is `'research'`, option list is populated with `ResearchService` and `#run-agent-btn` is enabled and set to "🔍 Run Research" without triggering an API request.
  - If the fetch response is empty, it populates `#agent-select` with "No agents for this stage" and disables `#run-agent-btn`.
  - If the fetch response contains agent sets (e.g., `['default', 'fiction']`), it populates the select with these options and handles automatic selection of the resolved active agent set.

### 3. Implement Frontend SSE Stream Tests (`tests/frontend/piece_sse.test.js`)
Create a new frontend test file focusing on EventSource (SSE) event handlers and button resetting logic:
- Mock the global `EventSource` object in the JSDOM context.
- Test `connectAutoSSE(runId)`:
  - When the `'chain_stage_complete'` event is received, verify `refreshStageTabs()` is called.
  - When the `'chain_complete'` event is received, verify connection is closed, a success toast is shown, `resetAutoButtons()` is called, and `location.reload()` is triggered.
  - When the `'chain_interrupted'` event is received, verify connection is closed, an info toast is shown, `resetAutoButtons()` is called, and `location.reload()` is triggered.
  - When an `'error'` event is received and `readyState` is `CLOSED`, verify `resetAutoButtons()` is called.
- Test SSE flow in `executeStage()`:
  - When the `'stage_start'` event is received, verify log message is appended with stage start info.
  - When the `'stage_complete'` event is received, verify log message is appended with stage complete info.
  - When the `'run_complete'` event is received, verify connection is closed, run complete log is appended, status text/color is updated to green, execution complete toast is shown, lock state is set to `false`, page navigates to target stage, and `loadRunLog()` is called.

## Verification Plan

### Automated Tests
- Execute Vitest frontend unit tests:
  ```bash
  export PATH="/home/bob/.nvm/versions/node/v24.16.0/bin:$PATH" && npm test
  ```
- Run python pytest suite:
  ```bash
  .venv/bin/pytest
  ```
- Run behave tests to confirm BDD suite passes:
  ```bash
  .venv/bin/behave
  ```
