# Frontend Unit Testing and Script Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a JavaScript unit testing environment using Vitest/jsdom and extract template scripts into separate static files to allow testing frontend logic in isolation.

**Architecture:** 
1. Extract inline JavaScript blocks from templates (`piece.html`, `dashboard.html`, `agents.html`) into modular JS files under `src/quill/static/js/`.
2. Configure a JS testing environment at the project root using `package.json` and `vitest` with `jsdom`.
3. Write unit tests loading extracted scripts in a JSDOM document context to verify UI logic (button states, dynamic option injection, and modal dismissals).
4. Update `pipeline_navigation.feature` scenario names to reflect backend/API constraints rather than UI button states.

**Tech Stack:** Vitest, jsdom, npm, Node.js (v24.16.0).

## Global Constraints
- Node path: `/home/bob/.nvm/versions/node/v24.16.0/bin/node`
- NPM path: `/home/bob/.nvm/versions/node/v24.16.0/bin/npm`
- Prefix node path to `PATH` environment variable for all node/npm/npx command execution.
- Behave and python test suites must continue to pass successfully.

---

### Task 1: Package Initialization and Vitest Configuration

**Files:**
- Create: `package.json`
- Create: `vitest.config.js`

- [ ] **Step 1: Create package.json**
  Write the package configuration with vitest and jsdom dependencies to `package.json` at the project root.
  ```json
  {
    "name": "quill-frontend-tests",
    "version": "1.0.0",
    "description": "Frontend unit tests for Quill",
    "scripts": {
      "test": "vitest run"
    },
    "devDependencies": {
      "vitest": "^2.1.0",
      "jsdom": "^25.0.0"
    }
  }
  ```

- [ ] **Step 2: Create vitest.config.js**
  Write the Vitest configuration file at the project root.
  ```javascript
  import { defineConfig } from 'vitest/config';

  export default defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
    },
  });
  ```

- [ ] **Step 3: Install JS Dependencies**
  Run: `export PATH="/home/bob/.nvm/versions/node/v24.16.0/bin:$PATH" && npm install`
  Expected output: Dependency installation completes successfully (creating `package-lock.json` and `node_modules`).

- [ ] **Step 4: Commit dependencies setup**
  Run:
  ```bash
  git add package.json vitest.config.js
  git commit -m "chore: initialize package.json and vitest config"
  ```

---

### Task 2: Extract JavaScript from agents.html

**Files:**
- Modify: `src/quill/templates/agents.html:109-409`
- Create: `src/quill/static/js/agents.js`

- [ ] **Step 1: Create agents.js and populate with extracted script**
  Move the complete content from within the `<script>` tag of `src/quill/templates/agents.html` (lines 110-408) to `src/quill/static/js/agents.js`.
  Remove `window.loadSets` wrapper IIFE or preserve it to ensure global bindings. Let's keep it exactly as it was:
  ```javascript
  (function() {
      var BASE = (window._SCRIPT_ROOT || '') + '/api/agents';
      var currentSet = '';
      var currentStage = '';
      // ... all functions and loadModelConfig(), window.loadSets() invocation
  })();
  ```

- [ ] **Step 2: Modify agents.html to load agents.js**
  Replace lines 109 to 409 in `src/quill/templates/agents.html` with:
  ```html
  <script src="{{ base }}/static/js/agents.js"></script>
  ```

- [ ] **Step 3: Run Python tests to verify page rendering**
  Run: `.venv/bin/pytest tests/test_app.py`
  Expected output: PASS

- [ ] **Step 4: Commit agents javascript extraction**
  Run:
  ```bash
  git add src/quill/templates/agents.html src/quill/static/js/agents.js
  git commit -m "refactor: extract agents.js static script from agents.html"
  ```

---

### Task 3: Extract JavaScript from dashboard.html

**Files:**
- Modify: `src/quill/templates/dashboard.html:81-190`
- Create: `src/quill/static/js/dashboard_view.js`

- [ ] **Step 1: Create dashboard_view.js and populate with extracted script**
  Move the code from inside `<script>` tag in `src/quill/templates/dashboard.html` (lines 83-189) into `src/quill/static/js/dashboard_view.js`.
  ```javascript
  async function loadPieces() { ... }
  function showCreateModal() { ... }
  function closeModal() { ... }
  async function createPiece(e) { ... }
  async function deletePiece(event, id, title) { ... }
  loadPieces();
  ```

- [ ] **Step 2: Modify dashboard.html to load dashboard_view.js**
  Replace lines 81 to 191 in `src/quill/templates/dashboard.html` with:
  ```html
  <script src="{{ base }}/static/js/dashboard_view.js"></script>
  ```

- [ ] **Step 3: Run Python tests to verify app tests still pass**
  Run: `.venv/bin/pytest tests/test_app.py`
  Expected: PASS

- [ ] **Step 4: Commit dashboard javascript extraction**
  Run:
  ```bash
  git add src/quill/templates/dashboard.html src/quill/static/js/dashboard_view.js
  git commit -m "refactor: extract dashboard_view.js static script from dashboard.html"
  ```

---

### Task 4: Extract JavaScript from piece.html

**Files:**
- Modify: `src/quill/templates/piece.html`
- Create: `src/quill/static/js/piece.js`

- [ ] **Step 1: Create piece.js and populate with script code**
  Move the JavaScript logic from within the `<script>` tag of `src/quill/templates/piece.html` to `src/quill/static/js/piece.js`.
  The script content should start with loading the constants from `piece-data`:
  ```javascript
  const pieceData = JSON.parse(document.getElementById('piece-data').textContent);
  const PIECE_ID = pieceData.piece_id;
  const CURRENT_STAGE = pieceData.current_stage;
  const PIECE_AGENT_SET = pieceData.piece_agent_set;
  const PIPELINE_ORDER = pieceData.pipeline_order;
  let VIEWING_STAGE = CURRENT_STAGE;

  // ── Stage navigation ──────────────────────────────────────────────
  async function navigateToStage(stage) { ... }
  // ... all functions and event listeners
  ```

- [ ] **Step 2: Modify piece.html to load piece.js**
  Update `src/quill/templates/piece.html` block scripts:
  ```html
  {% block scripts %}
  <script id="piece-data" type="application/json">
  {
      "piece_id": {{ piece.id|tojson }},
      "current_stage": {{ piece.current_stage|tojson }},
      "piece_agent_set": {{ (piece.agent_set or '')|tojson }},
      "pipeline_order": {{ pipeline_order|tojson }}
  }
  </script>
  <script src="{{ base }}/static/js/piece.js"></script>
  {% endblock %}
  ```

- [ ] **Step 3: Run python tests to confirm piece functionality**
  Run: `.venv/bin/pytest tests/test_piece.py` and `.venv/bin/pytest tests/test_app.py`
  Expected: PASS

- [ ] **Step 4: Commit piece.js extraction**
  Run:
  ```bash
  git add src/quill/templates/piece.html src/quill/static/js/piece.js
  git commit -m "refactor: extract piece.js static script from piece.html"
  ```

---

### Task 5: Implement Frontend Unit Tests for piece.js

**Files:**
- Create: `tests/frontend/piece.test.js`

- [ ] **Step 1: Create tests/frontend/piece.test.js**
  Write tests that mock DOM elements and the fetch API, then load `piece.js` and verify functions like `updateButtonStates` and `loadAgentsForStage`.
  ```javascript
  import { describe, it, expect, beforeEach, vi } from 'vitest';
  import fs from 'fs';
  import path from 'path';

  const pieceJsCode = fs.readFileSync(
    path.resolve(__dirname, '../../src/quill/static/js/piece.js'),
    'utf8'
  );

  describe('piece.js tests', () => {
    beforeEach(() => {
      document.body.innerHTML = `
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
        <button id="run-agent-btn"></button>
        <button id="advance-btn"></button>
        <button id="interrupt-btn" style="display: none;"></button>
        <select id="agent-select"></select>
      `;
      global.SCRIPT_ROOT = '';
      global.toast = vi.fn();
      global.fetch = vi.fn();
      
      // Load piece.js code in DOM context
      const script = document.createElement('script');
      script.textContent = pieceJsCode;
      document.body.appendChild(script);
    });

    it('should disable run and advance buttons when auto trigger and interrupt is visible', () => {
      document.getElementById('trigger-select').value = 'auto';
      document.getElementById('interrupt-btn').style.display = 'block';
      
      window.updateButtonStates();

      expect(document.getElementById('run-agent-btn').disabled).toBe(true);
      expect(document.getElementById('advance-btn').disabled).toBe(true);
    });

    it('should enable run and advance buttons when trigger is manual', () => {
      document.getElementById('trigger-select').value = 'manual';
      window.updateButtonStates();

      expect(document.getElementById('run-agent-btn').disabled).toBe(false);
      expect(document.getElementById('advance-btn').disabled).toBe(false);
    });

    it('should populate agent selection for research stage without backend call', async () => {
      await window.loadAgentsForStage('research');
      const select = document.getElementById('agent-select');
      expect(select.innerHTML).toContain('ResearchService');
    });
  });
  ```

- [ ] **Step 2: Run frontend unit tests to verify they pass**
  Run: `export PATH="/home/bob/.nvm/versions/node/v24.16.0/bin:$PATH" && npm test`
  Expected: PASS

- [ ] **Step 3: Commit frontend piece.js unit tests**
  Run:
  ```bash
  git add tests/frontend/piece.test.js
  git commit -m "test: add unit tests for piece.js"
  ```

---

### Task 6: Implement Frontend Unit Tests for Dashboard Modal and Escape Key

**Files:**
- Create: `tests/frontend/dashboard.test.js`

- [ ] **Step 1: Create tests/frontend/dashboard.test.js**
  Write tests evaluating `dashboard.js` to assert that:
  - Pressing the Escape key removes `.modal-overlay`.
  - Clicking on `.modal-overlay` removes it.
  ```javascript
  import { describe, it, expect, beforeEach, vi } from 'vitest';
  import fs from 'fs';
  import path from 'path';

  const dashboardJsCode = fs.readFileSync(
    path.resolve(__dirname, '../../src/quill/static/js/dashboard.js'),
    'utf8'
  );

  describe('dashboard.js modal interactions', () => {
    beforeEach(() => {
      document.body.innerHTML = `
        <div class="modal-overlay">
          <div class="modal-content">Create Piece Form</div>
        </div>
      `;
      // Load dashboard.js
      const script = document.createElement('script');
      script.textContent = dashboardJsCode;
      document.body.appendChild(script);
    });

    it('closes modal on Escape key down', () => {
      const event = new KeyboardEvent('keydown', { key: 'Escape' });
      document.dispatchEvent(event);
      expect(document.querySelector('.modal-overlay')).toBeNull();
    });

    it('closes modal on click-outside (overlay click)', () => {
      const overlay = document.querySelector('.modal-overlay');
      overlay.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      expect(document.querySelector('.modal-overlay')).toBeNull();
    });
  });
  ```

- [ ] **Step 2: Run all frontend unit tests**
  Run: `export PATH="/home/bob/.nvm/versions/node/v24.16.0/bin:$PATH" && npm test`
  Expected: PASS

- [ ] **Step 3: Commit dashboard unit tests**
  Run:
  ```bash
  git add tests/frontend/dashboard.test.js
  git commit -m "test: add unit tests for dashboard modal dismissals"
  ```

---

### Task 7: Update BDD Behave Scenarios

**Files:**
- Modify: `features/api/pipeline_navigation.feature`

- [ ] **Step 1: Rename scenarios in pipeline_navigation.feature**
  Replace occurrences of scenario titles mentioning UI elements with API-centric terms.
  Modify `pipeline_navigation.feature`:
  - `Scenario: Auto trigger — run agent button is disabled while running`
    Change to:
    `Scenario: Auto trigger — cannot manually run agent while auto running`
  - `Scenario: Auto trigger — advance button is disabled while running`
    Change to:
    `Scenario: Auto trigger — cannot manually advance stage while auto running`

- [ ] **Step 2: Run all Python and behave tests to verify completeness**
  Run Python tests: `.venv/bin/pytest`
  Run Behave tests: `.venv/bin/behave` (or through pytest runner if integrated)
  Wait, let's run `.venv/bin/behave` or python tests to check.
  Let's verify what command runs the behave suite.
  Run: `poetry run behave` (or `.venv/bin/behave` or similar python trigger).

- [ ] **Step 3: Commit BDD scenario cleanup**
  Run:
  ```bash
  git add features/api/pipeline_navigation.feature
  git commit -m "test: rename BDD scenarios to focus on API constraints rather than UI button states"
  ```

---

## Verification Plan

### Automated Tests
- JavaScript/Frontend unit tests:
  `export PATH="/home/bob/.nvm/versions/node/v24.16.0/bin:$PATH" && npm test`
- Python unit and integration tests:
  `.venv/bin/pytest tests/test_piece.py tests/test_app.py`
- Behave BDD tests:
  `.venv/bin/pytest` or running behave command directly.
