# Frontend-related Behave Tests Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish isolated frontend unit tests for button state management, EventSource (SSE) stream handling, and dynamic agent loading. Remove slow, flaky Behave BDD scenarios that rely on backend orchestration and LLM executions to test frontend button states.

**Architecture:** Create two new test files under `tests/frontend/`: `piece_agents.test.js` to test `loadAgentsForStage()` agent list loading, and `piece_sse.test.js` to mock EventSource/SSE event handlers. Remove the UI-focused scenarios from `features/api/pipeline_navigation.feature`.

**Tech Stack:** Vitest, jsdom, Node.js (v24.16.0), Python (for Behave/Pytest).

## Global Constraints
- Node path: `/home/bob/.nvm/versions/node/v24.16.0/bin/node`
- NPM path: `/home/bob/.nvm/versions/node/v24.16.0/bin/npm`
- Prefix node path to `PATH` environment variable for all node/npm/npx command execution.
- Behave and Python test suites must continue to pass successfully.

---

### Task 1: Create Frontend Unit Tests for Agent Option Injection

**Files:**
- Create: `tests/frontend/piece_agents.test.js`

**Interfaces:**
- Consumes: `src/quill/static/js/piece.js`
- Produces: None (test only)

- [ ] **Step 1: Create piece_agents.test.js**
  Write tests that mock the dynamic agent options loading logic in JSDOM context.

  ```javascript
  import { describe, it, expect, beforeEach, vi } from 'vitest';
  import { JSDOM } from 'jsdom';
  import fs from 'fs';
  import path from 'path';

  const pieceJsCode = fs.readFileSync(
    path.resolve(__dirname, '../../src/quill/static/js/piece.js'),
    'utf8'
  );

  describe('piece.js loadAgentsForStage tests', () => {
    let dom;

    beforeEach(() => {
      dom = new JSDOM(`
        <!DOCTYPE html>
        <html>
        <body>
          <script id="piece-data" type="application/json">
          {
            "piece_id": "test-id",
            "current_stage": "outline",
            "piece_agent_set": "fiction",
            "pipeline_order": ["brief", "outline", "draft"]
          }
          </script>
          <select id="agent-select"></select>
          <button id="run-agent-btn"></button>
          <div id="viewing-stage-display"></div>
          <div id="content-heading"></div>
          <div id="chapter-breakdown"></div>
          <div id="stage-state-badge"></div>
          <div id="stage-metrics"></div>
          <div id="stage-metrics-grid"></div>
          <div id="audio-section"></div>
          <div id="audio-files"></div>
        </body>
        </html>
      `, { runScripts: "dangerously" });

      global.window = dom.window;
      global.document = dom.window.document;
      global.SCRIPT_ROOT = '';
      global.PIECE_AGENT_SET = 'fiction';
      global.toast = vi.fn();
      global.fetch = vi.fn();
      dom.window.SCRIPT_ROOT = '';
      dom.window.PIECE_AGENT_SET = 'fiction';
      dom.window.toast = global.toast;
      dom.window.fetch = global.fetch;

      const script = dom.window.document.createElement('script');
      script.textContent = pieceJsCode;
      dom.window.document.body.appendChild(script);
    });

    it('should populate agent selection for research stage without backend call', async () => {
      await dom.window.loadAgentsForStage('research');
      const select = dom.window.document.getElementById('agent-select');
      expect(select.innerHTML).toContain('ResearchService');
      const btn = dom.window.document.getElementById('run-agent-btn');
      expect(btn.disabled).toBe(false);
      expect(btn.textContent).toBe('🔍 Run Research');
    });

    it('should handle empty agent sets gracefully', async () => {
      global.fetch.mockResolvedValueOnce({
        json: async () => ({ agent_sets: [] })
      });
      await dom.window.loadAgentsForStage('outline');
      const select = dom.window.document.getElementById('agent-select');
      expect(select.innerHTML).toContain('No agents for this stage');
      const btn = dom.window.document.getElementById('run-agent-btn');
      expect(btn.disabled).toBe(true);
    });

    it('should populate options and auto-select active agent set', async () => {
      global.fetch.mockResolvedValueOnce({
        json: async () => ({ agent_sets: [{ name: 'default' }, { name: 'fiction' }] })
      });
      await dom.window.loadAgentsForStage('outline');
      const select = dom.window.document.getElementById('agent-select');
      expect(select.children.length).toBe(2);
      expect(select.children[0].value).toBe('default');
      expect(select.children[1].value).toBe('fiction');
      expect(select.value).toBe('fiction');
    });
  });
  ```

- [ ] **Step 2: Run Vitest to check new tests**
  Run: `export PATH="/home/bob/.nvm/versions/node/v24.16.0/bin:$PATH" && npm test tests/frontend/piece_agents.test.js`
  Expected output: 3 tests passed.

- [ ] **Step 3: Commit agent unit tests**
  Run:
  ```bash
  git add tests/frontend/piece_agents.test.js
  git commit -m "test: add frontend unit tests for loadAgentsForStage in piece_agents.test.js"
  ```

---

### Task 2: Create Frontend Unit Tests for EventSource (SSE) Handlers

**Files:**
- Create: `tests/frontend/piece_sse.test.js`

**Interfaces:**
- Consumes: `src/quill/static/js/piece.js`
- Produces: None (test only)

- [ ] **Step 1: Create piece_sse.test.js**
  Write tests that mock EventSource stream events and assert their updates on DOM elements.

  ```javascript
  import { describe, it, expect, beforeEach, vi } from 'vitest';
  import { JSDOM } from 'jsdom';
  import fs from 'fs';
  import path from 'path';

  const pieceJsCode = fs.readFileSync(
    path.resolve(__dirname, '../../src/quill/static/js/piece.js'),
    'utf8'
  );

  describe('piece.js EventSource / SSE handlers tests', () => {
    let dom;

    beforeEach(() => {
      dom = new JSDOM(`
        <!DOCTYPE html>
        <html>
        <body>
          <script id="piece-data" type="application/json">
          {
            "piece_id": "test-id",
            "current_stage": "outline",
            "piece_agent_set": "fiction",
            "pipeline_order": ["brief", "outline", "draft"]
          }
          </script>
          <select id="trigger-select">
            <option value="manual">Manual</option>
            <option value="on_advance">On Advance</option>
            <option value="auto">Auto</option>
          </select>
          <div id="trigger-display"></div>
          <button id="auto-btn"></button>
          <button id="interrupt-btn" style="display: none;"></button>
          <button id="execute-btn"></button>
          <button id="advance-btn"></button>
          <button id="save-content-btn"></button>
          <button id="delete-piece-btn"></button>
          <textarea id="prompt-editor"></textarea>
          <textarea id="content-editor"></textarea>
          <div id="execute-status"></div>
          <div id="run-log-panel"></div>
          <div id="run-log-entries"></div>
          <div id="run-log-toggle"></div>

          <!-- Mock initialization elements -->
          <div id="viewing-stage-display"></div>
          <div id="content-heading"></div>
          <div id="chapter-breakdown"></div>
          <div id="stage-state-badge"></div>
          <div id="stage-metrics"></div>
          <div id="stage-metrics-grid"></div>
          <div id="audio-section"></div>
          <div id="audio-files"></div>
        </body>
        </html>
      `, { runScripts: "dangerously" });

      global.window = dom.window;
      global.document = dom.window.document;
      global.SCRIPT_ROOT = '';
      global.toast = vi.fn();
      global.fetch = vi.fn();
      
      dom.window.SCRIPT_ROOT = '';
      dom.window.toast = global.toast;
      dom.window.fetch = global.fetch;

      // EventSource mock framework
      dom.window.eventSources = [];
      class MockEventSource {
        constructor(url) {
          this.url = url;
          this.listeners = {};
          this.readyState = 0; // CONNECTING
          dom.window.eventSources.push(this);
        }
        addEventListener(event, callback) {
          this.listeners[event] = this.listeners[event] || [];
          this.listeners[event].push(callback);
        }
        close() {
          this.readyState = 2; // CLOSED
        }
        emit(event, data) {
          if (this.listeners[event]) {
            this.listeners[event].forEach(cb => cb({ data: JSON.stringify(data) }));
          }
        }
      }
      dom.window.EventSource = MockEventSource;
      global.EventSource = MockEventSource;

      const script = dom.window.document.createElement('script');
      script.textContent = pieceJsCode;
      dom.window.document.body.appendChild(script);
    });

    it('connectAutoSSE chain_stage_complete event should refresh stage tabs', () => {
      dom.window.refreshStageTabs = vi.fn();
      dom.window.connectAutoSSE('run-123');
      const es = dom.window.eventSources[0];
      es.emit('chain_stage_complete', { stage: 'draft' });
      expect(dom.window.refreshStageTabs).toHaveBeenCalled();
    });

    it('connectAutoSSE chain_complete event should close, toast, reset, and reload', () => {
      const originalReload = dom.window.location.reload;
      dom.window.location.reload = vi.fn();

      dom.window.connectAutoSSE('run-123');
      const es = dom.window.eventSources[0];
      const closeSpy = vi.spyOn(es, 'close');

      es.emit('chain_complete', {});

      expect(closeSpy).toHaveBeenCalled();
      expect(global.toast).toHaveBeenCalledWith('Auto pipeline complete!', 'success');
      expect(dom.window.location.reload).toHaveBeenCalled();

      dom.window.location.reload = originalReload;
    });

    it('connectAutoSSE chain_interrupted event should close, toast, reset, and reload', () => {
      const originalReload = dom.window.location.reload;
      dom.window.location.reload = vi.fn();

      dom.window.connectAutoSSE('run-123');
      const es = dom.window.eventSources[0];
      const closeSpy = vi.spyOn(es, 'close');

      es.emit('chain_interrupted', {});

      expect(closeSpy).toHaveBeenCalled();
      expect(global.toast).toHaveBeenCalledWith('Pipeline interrupted', 'info');
      expect(dom.window.location.reload).toHaveBeenCalled();

      dom.window.location.reload = originalReload;
    });

    it('connectAutoSSE error event in CLOSED readyState resets buttons', () => {
      dom.window.connectAutoSSE('run-123');
      const es = dom.window.eventSources[0];
      es.readyState = 2; // CLOSED

      es.listeners['error'].forEach(cb => cb({}));
      
      expect(dom.window.document.getElementById('auto-btn').style.display).toBe('');
      expect(dom.window.document.getElementById('auto-btn').disabled).toBe(false);
    });

    it('executeStage SSE flow should append log and update status on completion', async () => {
      global.fetch.mockResolvedValueOnce({
        json: async () => ({ run_id: 'run-456' })
      });
      dom.window.navigateToStage = vi.fn();
      dom.window.loadRunLog = vi.fn();

      await dom.window.executeStage();

      const es = dom.window.eventSources[0];
      expect(es.url).toContain('/runs/run-456/events');

      es.emit('stage_start', { stage: 'draft' });
      expect(dom.window.document.getElementById('run-log-entries').innerHTML).toContain('Stage start:');

      es.emit('stage_complete', {});
      expect(dom.window.document.getElementById('run-log-entries').innerHTML).toContain('Stage complete');

      const closeSpy = vi.spyOn(es, 'close');
      es.emit('run_complete', {});

      expect(closeSpy).toHaveBeenCalled();
      expect(dom.window.document.getElementById('execute-status').textContent).toBe('Complete');
      expect(global.toast).toHaveBeenCalledWith('Execution complete', 'success');
      expect(dom.window.navigateToStage).toHaveBeenCalled();
      expect(dom.window.loadRunLog).toHaveBeenCalled();
    });
  });
  ```

- [ ] **Step 2: Run Vitest to check new tests**
  Run: `export PATH="/home/bob/.nvm/versions/node/v24.16.0/bin:$PATH" && npm test tests/frontend/piece_sse.test.js`
  Expected output: 5 tests passed.

- [ ] **Step 3: Commit sse unit tests**
  Run:
  ```bash
  git add tests/frontend/piece_sse.test.js
  git commit -m "test: add frontend unit tests for connectAutoSSE and executeStage SSE stream handling"
  ```

---

### Task 3: Remove BDD Scenarios and Run Full Verification

**Files:**
- Modify: `features/api/pipeline_navigation.feature:179-198`

**Interfaces:**
- Consumes: None
- Produces: None

- [ ] **Step 1: Modify pipeline_navigation.feature to remove UI-simulating BDD scenarios**
  Remove lines 179 to 198 of `features/api/pipeline_navigation.feature` containing the scenarios `Auto trigger — cannot manually run agent while auto running` and `Auto trigger — cannot manually advance stage while auto running`.

- [ ] **Step 2: Run all python unit tests and behave tests**
  Run:
  ```bash
  .venv/bin/pytest
  .venv/bin/behave
  ```
  Expected output: All backend tests pass successfully.

- [ ] **Step 3: Run all frontend tests**
  Run: `export PATH="/home/bob/.nvm/versions/node/v24.16.0/bin:$PATH" && npm test`
  Expected output: 12 tests passed (including the dashboard and piece tests).

- [ ] **Step 4: Commit behave changes**
  Run:
  ```bash
  git add features/api/pipeline_navigation.feature
  git commit -m "test: remove UI-simulating BDD scenarios migrated to frontend unit tests"
  ```

---

## Verification Plan

### Automated Tests
- JavaScript/Frontend unit tests:
  `export PATH="/home/bob/.nvm/versions/node/v24.16.0/bin:$PATH" && npm test`
- Python unit and integration tests:
  `.venv/bin/pytest`
- Behave BDD tests:
  `.venv/bin/behave`
