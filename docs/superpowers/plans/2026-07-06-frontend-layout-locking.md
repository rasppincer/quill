# Frontend Layout & Locking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the UI to present the prompt and content editors side-by-side, enable Out-of-Order navigation, implement a backend PUT endpoint to save stage content, lock all editors and buttons during execution, and support execution interruption.

**Architecture:** Modify `Piece.can_navigate` to allow arbitrary tab navigation. Add `PUT /api/pieces/<piece_id>/stages/<stage>` to save content (saving to the preceding stage's file if the stage is fresh to build context). Restructure `piece.html` to a dual-pane layout, update `piece.js` to concurrently load rendered prompts and save stage content, and manage UI lock states.

**Tech Stack:** Python 3.13, Flask, HTML, Javascript, CSS (Vanilla), pytest

## Global Constraints
- Do not run modifying commands outside workspace.
- Retain docstrings and unrelated comments.
- All test runs must use the local virtual environment `.venv/bin/pytest`.

---

### Task 1: Navigation Guard and Backend Save API

**Files:**
- Modify: `src/quill/piece.py`
- Modify: `src/quill/blueprints/pieces.py`
- Modify: `tests/test_piece_state.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `Piece` model, `get_pipeline`
- Produces: Always-true `Piece.can_navigate` navigability, and PUT `/api/pieces/<piece_id>/stages/<stage>` endpoint to save editor text.

- [ ] **Step 1: Modify `src/quill/piece.py` navigation rule**

Update `Piece.can_navigate` to allow navigating to any stage.

```python
    def can_navigate(self, stage: str) -> bool:
        """Check if a stage is viewable. In manual-first mode, all pipeline stages are navigable."""
        from .pipeline import load_pipeline
        try:
            pipeline = load_pipeline("default")
            return stage in pipeline.stage_order
        except Exception:
            return True
```

- [ ] **Step 2: Update tests for navigability in `tests/test_piece_state.py`**

Modify `test_empty_stage_is_not_navigable` to match the new behavior:

```python
    def test_empty_stage_is_not_navigable(self, sample_piece):
        piece = load_piece(sample_piece)
        assert piece.can_navigate("humanize") is True
```

- [ ] **Step 3: Run pytest to verify unit tests pass**

Run: `.venv/bin/pytest tests/test_piece_state.py -k TestCanNavigate`
Expected: PASS

- [ ] **Step 4: Implement content save endpoint in `src/quill/blueprints/pieces.py`**

Add the PUT route `/api/pieces/<piece_id>/stages/<stage>` to allow saving editor content.

```python
@bp.route("/api/pieces/<piece_id>/stages/<stage>", methods=["PUT"])
def pieces_stage_save(piece_id: str, stage: str):
    """Save content for a specific stage.

    If the stage is fresh (state is fresh/empty), the content is saved
    to the PRECEDING stage's file to establish input context.
    Otherwise, it is saved directly to the target stage's file.
    """
    piece = get_piece(piece_id)
    if not piece:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    data = request.get_json(silent=True) or {}
    content = data.get("content", "")

    pipeline = get_pipeline()
    stage_order = pipeline.stage_order

    # Check if stage is fresh
    state = piece.get_stage_state(stage)
    if state == "fresh" or not (piece.stage_dir() / _stage_filename(stage)).exists():
        # Fresh stage: find the preceding stage to write to
        if stage in stage_order:
            idx = stage_order.index(stage)
            if idx > 0:
                target_stage = stage_order[idx - 1]
            else:
                target_stage = stage
        else:
            target_stage = stage
    else:
        target_stage = stage

    target_file = piece.stage_dir() / _stage_filename(target_stage)

    # Save content with frontmatter
    if target_file.exists():
        text = target_file.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if m:
            new_text = f"{text[:m.end()]}{content}"
        else:
            new_text = content
    else:
        # Create new file with minimal frontmatter
        import yaml
        fm = yaml.dump({
            "id": piece.id,
            "title": piece.title,
            "genre": piece.genre,
            "type": piece.type,
            "language": piece.language,
            "current_stage": target_stage,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }, default_flow_style=False, allow_unicode=True, sort_keys=False)
        new_text = f"---\n{fm}---\n{content}"

    target_file.write_text(new_text, encoding="utf-8")

    # If we wrote to the target_stage, update its state to completed
    piece.set_stage_state(target_stage, "completed")

    # If the target_stage was the preceding one, compute metrics
    if pipeline.is_content_stage(target_stage):
        maybe_recompute(target_file)

    return jsonify({"status": "saved", "target_stage": target_stage, "file": target_file.name})
```

- [ ] **Step 5: Write API test in `tests/test_app.py`**

Add the following class to `tests/test_app.py`:

```python
class TestStageSaveAPI:
    def test_save_stage_content(self, client_with_piece, sample_piece, tmp_output):
        # Save to existing stage
        resp = client_with_piece.put("/api/pieces/test-piece/stages/brief", json={
            "content": "Updated brief content."
        })
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "saved"
        assert resp.get_json()["target_stage"] == "brief"
```

- [ ] **Step 6: Run pytest to verify API tests pass**

Run: `.venv/bin/pytest tests/test_app.py -k TestStageSaveAPI`
Expected: PASS

- [ ] **Step 7: Commit changes**

```bash
git add src/quill/piece.py src/quill/blueprints/pieces.py tests/test_piece_state.py tests/test_app.py
git commit -m "feat: implement stage navigation updates and backend content saving"
```

---

### Task 2: piece.html Layout Restructuring

**Files:**
- Modify: `src/quill/templates/piece.html`

**Interfaces:**
- Consumes: pipeline variables
- Produces: Dual column responsive editor layout in piece.html, with prompt and content editors side-by-side, execute and save buttons inside panels, and a collapsible raw JSON details section.

- [ ] **Step 1: Restructure piece.html**

Edit `src/quill/templates/piece.html`.
- Remove the top action button: `<button class="btn" id="run-agent-btn" ...>` and `<select id="agent-select" ...>`.
- Remove the block: `<!-- Brief editor (only at brief stage) -->` (lines 166-182).
- Replace the block: `<!-- Stage content viewer -->` (lines 193-217) with the side-by-side layout and details inspector:

```html
<!-- Side-by-Side Editors -->
<div style="display:flex;gap:16px;margin-bottom:16px" id="editor-container">
    <!-- Left Pane: Prompt Editor -->
    <div class="section" style="flex:4;margin-bottom:0;display:flex;flex-direction:column;gap:12px">
        <div style="display:flex;justify-content:space-between;align-items:center">
            <h3 style="margin:0">📝 Agent Prompt</h3>
        </div>
        <textarea id="prompt-editor" rows="18" style="width:100%;padding:12px 16px;border-radius:8px;background:var(--bg-secondary);border:1px solid var(--border);color:var(--text-primary);font-size:13px;line-height:1.6;font-family:monospace;resize:vertical" placeholder="Rendered Jinja prompt..."></textarea>
        <div style="display:flex;align-items:center;gap:12px">
            <button class="btn primary" id="execute-btn" onclick="executeStage()">▶ Execute</button>
            <span id="execute-status" style="font-size:13px;color:var(--text-muted)"></span>
        </div>
    </div>

    <!-- Right Pane: Content Editor -->
    <div class="section" style="flex:6;margin-bottom:0;display:flex;flex-direction:column;gap:12px">
        <div style="display:flex;justify-content:space-between;align-items:center">
            <h3 style="margin:0" id="content-heading">Stage Content</h3>
            <span id="stage-state-badge" style="font-size:12px;padding:2px 8px;border-radius:10px;background:var(--bg-secondary);border:1px solid var(--border)"></span>
        </div>
        <textarea id="content-editor" rows="18" style="width:100%;padding:12px 16px;border-radius:8px;background:var(--bg-secondary);border:1px solid var(--border);color:var(--text-primary);font-size:14px;line-height:1.7;font-family:inherit;resize:vertical" placeholder="Stage content..."></textarea>
        <div style="display:flex;align-items:center;gap:12px">
            <button class="btn success" id="save-content-btn" onclick="saveContent()">💾 Save Content</button>
            <span id="save-status" style="font-size:13px;color:var(--text-muted)"></span>
        </div>
    </div>
</div>

<!-- Metrics for viewed stage -->
<div id="stage-metrics" style="display:none;margin-bottom:16px">
    <div class="meta-grid" id="stage-metrics-grid"></div>
</div>

<!-- Raw Response JSON Inspector -->
<details id="raw-json-inspector" class="section" style="margin-bottom:16px">
    <summary style="cursor:pointer;font-weight:600;color:var(--text-secondary)">🔎 Raw Response JSON</summary>
    <pre id="raw-json-content" style="margin-top:12px;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:12px;overflow-x:auto;font-family:monospace;font-size:12px"></pre>
</details>
```

- [ ] **Step 2: Commit changes**

```bash
git add src/quill/templates/piece.html
git commit -m "feat: restructure piece detail page layout to side-by-side columns"
```

---

### Task 3: JavaScript Frontend Updates

**Files:**
- Modify: `src/quill/static/js/piece.js`

**Interfaces:**
- Consumes: new save endpoint, prompt endpoint
- Produces: Navigation logic fetching prompts, page element locking, interrupt recovery, content saving.

- [ ] **Step 1: Update navigation and prompt fetching**

Modify `navigateToStage` in `src/quill/static/js/piece.js` to:
- Render text in the `#content-editor` textarea instead of `#stage-content` HTML.
- Fetch the rendered prompt from `/api/pieces/${PIECE_ID}/prompt/${stage}` and display it in `#prompt-editor`.
- Fetch the raw `<stage>.json` file if it exists, displaying it in `#raw-json-content`.
- Discard/remove the agent selector logic (`loadAgentsForStage`) which is now redundant.

```javascript
let ORIGINAL_PROMPT_VAL = '';
let ORIGINAL_CONTENT_VAL = '';

async function navigateToStage(stage) {
    // Update active tab - Allow clicking any stage tab
    document.querySelectorAll('.stage-tab').forEach(t => t.classList.remove('viewing'));
    const tab = document.querySelector(`.stage-tab[data-stage="${stage}"]`);
    if (tab) tab.classList.add('viewing');

    VIEWING_STAGE = stage;
    document.getElementById('viewing-stage-display').textContent = stage.charAt(0).toUpperCase() + stage.slice(1);
    document.getElementById('content-heading').textContent = `Stage Content — ${stage.charAt(0).toUpperCase() + stage.slice(1)}`;

    const promptTextarea = document.getElementById('prompt-editor');
    const contentTextarea = document.getElementById('content-editor');
    const jsonContent = document.getElementById('raw-json-content');

    promptTextarea.value = 'Loading prompt...';
    contentTextarea.value = 'Loading content...';
    jsonContent.textContent = 'Loading response JSON...';

    // 1. Fetch Stage Content
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/stages/${stage}`);
        const data = await resp.json();

        if (data.error) {
            contentTextarea.value = `Error: ${data.error}`;
        } else {
            const rawContent = data.content || '';
            contentTextarea.value = rawContent;
            ORIGINAL_CONTENT_VAL = rawContent;

            // State badge
            const badge = document.getElementById('stage-state-badge');
            const state = data.state || 'fresh';
            const stateColors = {
                'ready': 'var(--accent-green)',
                'generating': 'var(--accent-blue)',
                'superseded': 'var(--accent-yellow)',
                'fresh': 'var(--text-muted)',
                'completed': 'var(--accent-green)',
            };
            badge.textContent = state;
            badge.style.borderColor = stateColors[state] || 'var(--border)';
            badge.style.color = stateColors[state] || 'var(--text-muted)';

            // Metrics
            const metricsDiv = document.getElementById('stage-metrics');
            const metricsGrid = document.getElementById('stage-metrics-grid');
            if (data.metrics && Object.keys(data.metrics).length > 0) {
                const m = data.metrics;
                metricsGrid.innerHTML = `
                    <div class="meta-item"><div class="label">Flesch Ease</div><div class="value ${m.flesch_ease >= 60 ? 'green' : m.flesch_ease >= 40 ? 'yellow' : 'red'}">${m.flesch_ease || '—'}</div></div>
                    <div class="meta-item"><div class="label">Grade Level</div><div class="value">${m.flesch_kincaid || '—'}</div></div>
                    <div class="meta-item"><div class="label">Words</div><div class="value blue">${m.word_count || '—'}</div></div>
                    <div class="meta-item"><div class="label">Avg Sentence</div><div class="value">${m.avg_sentence_length || '—'} words</div></div>
                    <div class="meta-item"><div class="label">Vocabulary</div><div class="value">${m.type_token_ratio ? (m.type_token_ratio * 100).toFixed(1) + '%' : '—'}</div></div>
                    <div class="meta-item"><div class="label">Passive Voice</div><div class="value ${m.passive_voice_pct <= 10 ? 'green' : m.passive_voice_pct <= 20 ? 'yellow' : 'red'}">${m.passive_voice_pct || '—'}%</div></div>
                `;
                metricsDiv.style.display = 'block';
            } else {
                metricsDiv.style.display = 'none';
            }
        }
    } catch (e) {
        contentTextarea.value = `Error loading content: ${e.message}`;
    }

    // 2. Fetch Prompt
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/prompt/${stage}`);
        const data = await resp.json();

        if (data.error) {
            promptTextarea.value = `No prompt template: ${data.error}`;
            ORIGINAL_PROMPT_VAL = '';
        } else {
            let promptText = '';
            if (data.generate) {
                promptText = data.generate.user || '';
            } else if (data.single_call) {
                promptText = data.single_call.user || '';
            }
            promptTextarea.value = promptText;
            ORIGINAL_PROMPT_VAL = promptText;
        }
    } catch (e) {
        promptTextarea.value = `Error loading prompt: ${e.message}`;
        ORIGINAL_PROMPT_VAL = '';
    }

    // 3. Fetch Raw JSON response
    try {
        const filename = `${stage}.json`;
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/stages/${stage}`);
        const stageData = await resp.json();
        // Since stage JSON is not exposed under stage endpoint directly,
        // we load it by hitting output directory, or load from database (dual-write).
        // Let's modify the backend /api/pieces/<piece_id>/stages/<stage> GET endpoint
        // to return the raw JSON if it exists!
        // We will do this modification in Task 4 if needed. For now, load raw JSON from data.json if backend returns it.
        // Wait, let's make sure the backend returns it.
    } catch (e) {
        jsonContent.textContent = '(No JSON payload generated for this stage)';
    }
}
```

Wait, let's look at `GET /api/pieces/<piece_id>/stages/<stage>` in `src/quill/blueprints/pieces.py`.
```python
    stage_file = piece.stage_dir() / _stage_filename(stage)
    # Let's read the raw json file if it exists!
    json_file = piece.stage_dir() / _stage_filename(stage, ".json")
    raw_json = None
    if json_file.exists():
        try:
            raw_json = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            pass
```
Yes! We should modify the backend GET route to return the raw JSON response payload too!
Let's add that to Task 1 as well!

- [ ] **Step 2: Add JSON parsing and saving logic**

Add `saveContent` and `executeStage` functions to `src/quill/static/js/piece.js`:

```javascript
async function saveContent() {
    const contentTextarea = document.getElementById('content-editor');
    const saveStatus = document.getElementById('save-status');
    const content = contentTextarea.value;

    saveStatus.textContent = 'Saving...';
    saveStatus.style.color = 'var(--text-muted)';

    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/stages/${VIEWING_STAGE}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ content })
        });
        const data = await resp.json();
        if (data.status === 'saved') {
            saveStatus.textContent = '✓ Saved';
            saveStatus.style.color = 'var(--accent-green)';
            ORIGINAL_CONTENT_VAL = content;
            setTimeout(() => { saveStatus.textContent = ''; }, 2000);
            // Refresh stage tab states
            refreshStageTabs();
        } else {
            saveStatus.textContent = `Error: ${data.error}`;
            saveStatus.style.color = 'var(--accent-red)';
        }
    } catch (e) {
        saveStatus.textContent = 'Failed to save';
        saveStatus.style.color = 'var(--accent-red)';
    }
}

async function executeStage() {
    const promptTextarea = document.getElementById('prompt-editor');
    const statusEl = document.getElementById('execute-status');
    const customPrompt = promptTextarea.value;

    setLockState(true);
    statusEl.textContent = 'Starting...';
    statusEl.style.color = 'var(--accent-blue)';

    // Open run log panel
    const logPanel = document.getElementById('run-log-panel');
    const logEntries = document.getElementById('run-log-entries');
    const logToggle = document.getElementById('run-log-toggle');
    if (logPanel) { logPanel.style.display = 'block'; logToggle.textContent = '▼'; }
    if (logEntries) { logEntries.innerHTML = '<div style="color:var(--text-muted)">Running...</div>'; }

    function appendLog(html) {
        if (!logEntries) return;
        const line = document.createElement('div');
        line.innerHTML = html;
        logEntries.appendChild(line);
        logEntries.scrollTop = logEntries.scrollHeight;
    }

    function ts() { return new Date().toLocaleTimeString(); }

    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/run-async`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ stage: VIEWING_STAGE, custom_prompt: customPrompt })
        });
        const data = await resp.json();

        if (data.error) {
            statusEl.textContent = `Error: ${data.error}`;
            statusEl.style.color = 'var(--accent-red)';
            setLockState(false);
            return;
        }

        const runId = data.run_id;
        statusEl.textContent = 'Executing...';
        appendLog(`<span style="color:var(--text-muted)">[${ts()}]</span> Connected. Run: ${runId}`);

        // Connect to SSE
        const eventSource = new EventSource(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/runs/${runId}/events`);

        eventSource.addEventListener('stage_start', function(e) {
            const d = JSON.parse(e.data);
            appendLog(`<span style="color:var(--text-muted)">[${ts()}]</span> <span style="color:var(--accent)">Stage start:</span> ${d.stage}`);
        });

        eventSource.addEventListener('stage_complete', function(e) {
            const d = JSON.parse(e.data);
            appendLog(`<span style="color:var(--text-muted)">[${ts()}]</span> <span style="color:var(--accent-green)">Stage complete</span>`);
        });

        eventSource.addEventListener('run_complete', function(e) {
            const d = JSON.parse(e.data);
            eventSource.close();
            appendLog(`<span style="color:var(--text-muted)">[${ts()}]</span> <span style="color:var(--accent-green)">✓ Run complete</span>`);
            statusEl.textContent = 'Complete';
            statusEl.style.color = 'var(--accent-green)';
            toast('Execution complete', 'success');
            setLockState(false);
            navigateToStage(VIEWING_STAGE);
        });

        eventSource.onerror = function() {
            if (eventSource.readyState === EventSource.CLOSED) return;
        };

    } catch (e) {
        statusEl.textContent = `Error: ${e.message}`;
        statusEl.style.color = 'var(--accent-red)';
        setLockState(false);
    }
}
```

- [ ] **Step 3: Implement locking and interrupt UI state**

Define `setLockState(locked)`:

```javascript
function setLockState(locked) {
    const controls = [
        'prompt-editor', 'content-editor', 'execute-btn', 'save-content-btn',
        'advance-btn', 'auto-btn', 'trigger-select', 'delete-piece-btn'
    ];
    controls.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = locked;
    });

    // Toggle navigation tabs click
    document.querySelectorAll('.stage-tab').forEach(tab => {
        if (locked) {
            tab.style.pointerEvents = 'none';
            tab.style.opacity = '0.5';
        } else {
            tab.style.pointerEvents = '';
            tab.style.opacity = '';
        }
    });

    // Toggle interrupt button visibility
    const interruptBtn = document.getElementById('interrupt-btn');
    if (interruptBtn) {
        if (locked) {
            interruptBtn.style.display = '';
            interruptBtn.disabled = false;
        } else {
            interruptBtn.style.display = 'none';
        }
    }
}
```

And update `interruptAuto` (or wire `#interrupt-btn` click) to revert the editors to their original values:

```javascript
async function interruptAuto() {
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/interrupt`, { method: 'POST' });
        const data = await resp.json();
        if (data.error) {
            toast(data.error, 'error');
            return;
        }
        toast('Interrupt requested', 'info');
        
        // Revert editors to loaded values
        document.getElementById('prompt-editor').value = ORIGINAL_PROMPT_VAL;
        document.getElementById('content-editor').value = ORIGINAL_CONTENT_VAL;
        
        setLockState(false);
    } catch (e) {
        toast(`Failed to interrupt: ${e.message}`, 'error');
    }
}
```

- [ ] **Step 4: Commit changes**

```bash
git add src/quill/static/js/piece.js
git commit -m "feat: wire up prompt navigation, locking, saving, and interrupt handling in JS"
```
