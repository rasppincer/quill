# Brief Input on New Piece Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Brief/Prompt optional textarea to the New Piece creation modal, pass the input to the backend during creation, and automatically clear the form on success.

**Architecture:** Extend the frontend dashboard template to include the textarea, modify the JavaScript creation function to retrieve the value and pass it as the `body` field of the creation payload, and reset the HTML form on success. Add backend and frontend unit tests to verify the integration.

**Tech Stack:** Flask, Jinja2, HTML5/CSS, Vanilla JS, Vitest, Pytest.

## Global Constraints
- Target workspace must be within `/home/bob/projects/quill`.
- Do not introduce unused imports or unnecessary code dependencies.
- Follow existing formatting and style guidelines.

---

### Task 1: Backend Integration Tests

**Files:**
- Modify: [test_app.py](file:///home/bob/projects/quill/tests/test_app.py)

**Interfaces:**
- Consumes: Backend API `POST /api/pieces` behavior
- Produces: Verified backend persistence of `body` parameter inside piece metadata and stage file on creation.

- [ ] **Step 1: Write the test case verifying piece creation with a brief**
  Add the following test case inside the `TestPiecesAPI` class in [test_app.py](file:///home/bob/projects/quill/tests/test_app.py):
  ```python
      def test_create_piece_with_brief(self, client, tmp_output):
          resp = client.post("/api/pieces", json={
              "title": "My Blog Post with Brief",
              "genre": "non-fiction",
              "type": "blog",
              "audience": "developers",
              "tone": "technical",
              "body": "This is my brief content.",
          })
          assert resp.status_code == 201
          data = resp.get_json()
          assert data["id"] == "my-blog-post-with-brief"
          
          # Verify the stage file was written with the brief content
          brief_file = tmp_output / "my-blog-post-with-brief" / "01_brief.md"
          assert brief_file.exists()
          assert "This is my brief content." in brief_file.read_text()
  ```

- [ ] **Step 2: Run backend tests to verify they pass**
  Run: `.venv/bin/pytest tests/test_app.py -k test_create_piece_with_brief`
  Expected: PASS

- [ ] **Step 3: Commit**
  Run:
  ```bash
  git add tests/test_app.py
  git commit -m "test: add backend integration test for creating piece with brief"
  ```

---

### Task 2: Frontend HTML Template Update

**Files:**
- Modify: [dashboard.html](file:///home/bob/projects/quill/src/quill/templates/dashboard.html)

- [ ] **Step 1: Add Brief/Prompt field to HTML modal form**
  Modify [dashboard.html](file:///home/bob/projects/quill/src/quill/templates/dashboard.html) around line 70, placing the Brief textarea before the Trigger Mode section:
  ```html
                  <label>Target Length</label>
                  <input type="text" id="f-length" placeholder="e.g. 5000-8000 words">
  
                  <label>Brief / Prompt</label>
                  <textarea id="f-body" placeholder="Outline the main goals, characters, plot points, or requirements..."></textarea>
  
                  <label>Trigger Mode</label>
  ```

- [ ] **Step 2: Commit template changes**
  Run:
  ```bash
  git add src/quill/templates/dashboard.html
  git commit -m "feat: add brief textarea to dashboard new piece modal"
  ```

---

### Task 3: Frontend JS Logic and Unit Tests

**Files:**
- Create: [dashboard_view.test.js](file:///home/bob/projects/quill/tests/frontend/dashboard_view.test.js)
- Modify: [dashboard_view.js](file:///home/bob/projects/quill/src/quill/static/js/dashboard_view.js)

**Interfaces:**
- Consumes: Modal DOM elements (`#f-body` textarea and `#create-form`)
- Produces: API request payload containing the `body` key, and reset form element state on successful creation.

- [ ] **Step 1: Create frontend unit test verifying the JS change**
  Create the file [dashboard_view.test.js](file:///home/bob/projects/quill/tests/frontend/dashboard_view.test.js):
  ```javascript
  import { describe, it, expect, beforeEach, vi } from 'vitest';
  import { JSDOM } from 'jsdom';
  import fs from 'fs';
  import path from 'path';
  
  const dashboardViewJsCode = fs.readFileSync(
    path.resolve(__dirname, '../../src/quill/static/js/dashboard_view.js'),
    'utf8'
  );
  
  describe('dashboard_view.js createPiece', () => {
    let dom;
  
    beforeEach(() => {
      dom = new JSDOM(`
        <!DOCTYPE html>
        <html>
        <body>
          <div id="create-modal">
            <form id="create-form">
              <input type="text" id="f-title" value="Test title">
              <select id="f-genre"><option value="fiction">Fiction</option></select>
              <select id="f-type"><option value="story">Story</option></select>
              <input type="text" id="f-audience" value="gamers">
              <input type="text" id="f-tone" value="casual">
              <select id="f-language"><option value="en">English</option></select>
              <input type="text" id="f-length" value="1000 words">
              <textarea id="f-body">This is the brief.</textarea>
              <input type="radio" name="trigger" value="on_advance" checked>
            </form>
          </div>
        </body>
        </html>
      `, { runScripts: "dangerously" });
  
      global.window = dom.window;
      global.document = dom.window.document;
      global.toast = vi.fn();
      global.api = vi.fn().mockResolvedValue({ id: 'test-id', title: 'Test title' });
      global.loadPieces = vi.fn();
      global.closeModal = vi.fn();
  
      // Bind to window to simulate scripts loading in same window context
      dom.window.toast = global.toast;
      dom.window.api = global.api;
      dom.window.loadPieces = global.loadPieces;
      dom.window.closeModal = global.closeModal;
  
      // Load dashboard_view.js
      const script = dom.window.document.createElement('script');
      script.textContent = dashboardViewJsCode;
      dom.window.document.body.appendChild(script);
    });
  
    it('collects f-body brief content and sends it to the API, then resets form', async () => {
      const event = { preventDefault: vi.fn() };
      
      // Spy on form reset
      const form = dom.window.document.getElementById('create-form');
      const resetSpy = vi.spyOn(form, 'reset');
      
      await dom.window.createPiece(event);
  
      expect(global.api).toHaveBeenCalledWith('/api/pieces', {
        method: 'POST',
        body: JSON.stringify({
          title: 'Test title',
          genre: 'fiction',
          type: 'story',
          audience: 'gamers',
          tone: 'casual',
          language: 'en',
          target_length: '1000 words',
          trigger: 'on_advance',
          body: 'This is the brief.',
        })
      });
      
      expect(resetSpy).toHaveBeenCalled();
    });
  });
  ```

- [ ] **Step 2: Run frontend tests to verify the test fails**
  Run: `npx vitest run tests/frontend/dashboard_view.test.js`
  Expected: FAIL (since the JS changes have not been implemented yet)

- [ ] **Step 3: Modify JS creation logic to pass f-body value and reset form**
  Modify the `createPiece(e)` function in [dashboard_view.js](file:///home/bob/projects/quill/src/quill/static/js/dashboard_view.js):
  ```javascript
  async function createPiece(e) {
      e.preventDefault();
      const body = {
          title: document.getElementById('f-title').value,
          genre: document.getElementById('f-genre').value,
          type: document.getElementById('f-type').value,
          audience: document.getElementById('f-audience').value,
          tone: document.getElementById('f-tone').value,
          language: document.getElementById('f-language').value,
          target_length: document.getElementById('f-length').value,
          body: document.getElementById('f-body').value,
          trigger: document.querySelector('input[name="trigger"]:checked').value,
      };
      const result = await api('/api/pieces', { method: 'POST', body: JSON.stringify(body) });
      if (result) {
          toast(`Created "${result.title}"`, 'success');
          document.getElementById('create-form').reset();
          closeModal();
          loadPieces();
      }
  }
  ```

- [ ] **Step 4: Run frontend tests to verify they pass**
  Run: `npx vitest run tests/frontend/dashboard_view.test.js`
  Expected: PASS

- [ ] **Step 5: Run all frontend tests to ensure no regressions**
  Run: `npx vitest run`
  Expected: PASS

- [ ] **Step 6: Commit**
  Run:
  ```bash
  git add src/quill/static/js/dashboard_view.js tests/frontend/dashboard_view.test.js
  git commit -m "feat: pass brief input from form and reset form on successful creation"
  ```
