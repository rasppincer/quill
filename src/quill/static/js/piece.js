const pieceData = JSON.parse(document.getElementById('piece-data').textContent);
const PIECE_ID = pieceData.piece_id;
const CURRENT_STAGE = pieceData.current_stage;
const PIECE_AGENT_SET = pieceData.piece_agent_set;
const PIPELINE_ORDER = pieceData.pipeline_order;
let VIEWING_STAGE = CURRENT_STAGE;

// ── Stage navigation ──────────────────────────────────────────────

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
            ORIGINAL_CONTENT_VAL = '';
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

            // Load raw JSON if it was returned by navigate endpoint
            if (data.raw_json) {
                jsonContent.textContent = JSON.stringify(data.raw_json, null, 4);
            } else {
                jsonContent.textContent = '(No JSON response payload generated for this stage)';
            }
        }

        // Chapter breakdown for draft stage
        const chapterDiv = document.getElementById('chapter-breakdown');
        if (stage === 'draft' && data.content && data.content.trim()) {
            loadChapterBreakdown(chapterDiv);
        } else if (chapterDiv) {
            chapterDiv.style.display = 'none';
        }

    } catch (e) {
        contentTextarea.value = `Error loading content: ${e.message}`;
        ORIGINAL_CONTENT_VAL = '';
        jsonContent.textContent = '(Error loading response JSON)';
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
            if (data.prompt) {
                promptText = data.prompt.user || '';
            } else if (data.generate) {
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
}

// ── Chapter breakdown ────────────────────────────────────────────

async function loadChapterBreakdown(container) {
    if (!container) return;
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/chapters`);
        const data = await resp.json();

        if (!data.chapters || data.chapters.length === 0) {
            container.style.display = 'none';
            return;
        }

        container.style.display = 'block';
        document.getElementById('chapter-summary').textContent =
            `${data.chapter_count} chapters · ${data.total_words.toLocaleString()} words`;

        const list = document.getElementById('chapter-list');
        list.innerHTML = data.chapters.map(ch => {
            const pct = data.total_words > 0 ? Math.round(ch.words / data.total_words * 100) : 0;
            const barColor = pct >= 20 ? 'var(--accent-green)' : pct >= 10 ? 'var(--accent-blue)' : 'var(--accent-orange)';
            return `
                <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px 16px;cursor:pointer"
                     onclick="scrollToChapter(${ch.number})"
                     title="${ch.preview.replace(/"/g, '&quot;')}">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                        <div style="display:flex;align-items:center;gap:8px">
                            <span style="color:var(--accent-purple);font-weight:600;font-size:13px">Ch ${ch.number}</span>
                            <span style="font-size:14px;font-weight:500">${ch.title}</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:8px">
                            <span style="font-size:13px;color:var(--text-muted)">${ch.words.toLocaleString()} words</span>
                            <span style="font-size:12px;color:${barColor}">${pct}%</span>
                        </div>
                    </div>
                    <div style="background:var(--bg-primary);border-radius:4px;height:6px;overflow:hidden">
                        <div style="background:${barColor};height:100%;width:${pct}%;transition:width 0.3s ease"></div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        container.style.display = 'none';
    }
}

function scrollToChapter(chapterNum) {
    const contentDiv = document.getElementById('stage-content');
    if (!contentDiv) return;
    // Find the chapter heading in the rendered markdown
    const headings = contentDiv.querySelectorAll('h2');
    for (const h of headings) {
        if (h.textContent.match(new RegExp(`Part ${chapterNum}|Chapter ${chapterNum}`))) {
            h.scrollIntoView({ behavior: 'smooth', block: 'start' });
            // Flash highlight
            h.style.background = 'rgba(188,140,255,0.15)';
            setTimeout(() => { h.style.background = ''; }, 2000);
            return;
        }
    }
}

async function loadChapterBadge() {
    const badge = document.getElementById('draft-chapter-badge');
    if (!badge) return;
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/chapters`);
        const data = await resp.json();
        if (data.chapter_count && data.chapter_count > 1) {
            badge.textContent = `${data.chapter_count}ch`;
            badge.title = `${data.chapter_count} chapters · ${data.total_words.toLocaleString()} words`;
            badge.style.display = 'inline';
        }
    } catch (e) { /* no chapters */ }
}

// ── Trigger ───────────────────────────────────────────────────────

async function setTrigger(trigger) {
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/trigger`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ trigger }),
        });
        const data = await resp.json();
        if (data.error) {
            toast(data.error, 'error');
            return;
        }
        document.getElementById('trigger-display').textContent = trigger;
        toast(`Trigger set to ${trigger}`, 'success');
        updateButtonStates();
    } catch (e) {
        toast(`Failed to set trigger: ${e.message}`, 'error');
    }
}

// ── Auto pipeline ─────────────────────────────────────────────────

async function toggleAuto() {
    const btn = document.getElementById('auto-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Starting...';

    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/auto`, { method: 'POST' });
        const data = await resp.json();

        if (data.error) {
            toast(data.error, 'error');
            btn.disabled = false;
            btn.textContent = '▶ Auto Pipeline';
            return;
        }

        toast('Auto pipeline started', 'success');
        document.getElementById('auto-btn').style.display = 'none';
        document.getElementById('interrupt-btn').style.display = '';
        document.getElementById('trigger-select').value = 'auto';
        document.getElementById('trigger-display').textContent = 'auto';
        updateButtonStates();

        // Connect to SSE for progress
        connectAutoSSE(data.run_id);

    } catch (e) {
        toast(`Failed to start auto: ${e.message}`, 'error');
        btn.disabled = false;
        btn.textContent = '▶ Auto Pipeline';
    }
}

function connectAutoSSE(runId) {
    const eventSource = new EventSource(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/runs/${runId}/events`);

    // Refresh tabs when a new stage begins (shows "generating" badge)
    eventSource.addEventListener('stage_start', function(e) {
        refreshStageTabs();
    });

    eventSource.addEventListener('chain_stage_complete', function(e) {
        const d = JSON.parse(e.data);
        // Update stage tab states
        refreshStageTabs();
    });

    eventSource.addEventListener('chain_complete', function(e) {
        eventSource.close();
        toast('Auto pipeline complete!', 'success');
        resetAutoButtons();
        location.reload();
    });

    eventSource.addEventListener('chain_interrupted', function(e) {
        eventSource.close();
        toast('Pipeline interrupted', 'info');
        resetAutoButtons();
        location.reload();
    });

    eventSource.addEventListener('error', function(e) {
        if (eventSource.readyState === EventSource.CLOSED) {
            resetAutoButtons();
        }
    });
}

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


function resetAutoButtons() {
    document.getElementById('auto-btn').style.display = '';
    document.getElementById('auto-btn').disabled = false;
    document.getElementById('auto-btn').textContent = '▶ Auto Pipeline';
    document.getElementById('interrupt-btn').style.display = 'none';
    document.getElementById('interrupt-btn').disabled = false;
    document.getElementById('interrupt-btn').textContent = '⏹ Interrupt';
    updateButtonStates();
}

// ── Button state management ───────────────────────────────────────

function updateButtonStates() {
    const trigger = document.getElementById('trigger-select').value;
    const isAuto = trigger === 'auto';
    const executeBtn = document.getElementById('execute-btn');
    const advanceBtn = document.getElementById('advance-btn');

    // During auto mode, disable execute and advance
    if (isAuto && document.getElementById('interrupt-btn').style.display !== 'none') {
        if (executeBtn) { executeBtn.disabled = true; executeBtn.title = 'Auto mode — cannot run manually'; }
        if (advanceBtn) { advanceBtn.disabled = true; advanceBtn.title = 'Auto mode — cannot advance manually'; }
    } else {
        if (executeBtn) { executeBtn.disabled = false; executeBtn.title = ''; }
        if (advanceBtn) { advanceBtn.disabled = false; advanceBtn.title = ''; }
    }
}

// ── Refresh stage tabs ────────────────────────────────────────────

async function refreshStageTabs() {
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}`);
        const data = await resp.json();
        const states = data.stage_states || {};

        document.querySelectorAll('.stage-tab').forEach(tab => {
            const stage = tab.dataset.stage;
            const state = states[stage] || 'empty';
            tab.dataset.state = state;
            tab.className = `stage-tab ${state} ${stage === data.current_stage ? 'active' : ''}`;
            const dot = tab.querySelector('.stage-dot');
            if (dot) dot.className = `stage-dot ${state}`;
        });
    } catch (e) { /* ignore */ }
}

// ── Load agents for a specific stage ──────────────────────────────

async function loadAgentsForStage(stage) {
    const select = document.getElementById('agent-select');
    if (!select) return;

    if (stage === 'research') {
        select.innerHTML = '<option value="non-fiction">ResearchService</option>';
        const btn = document.getElementById('run-agent-btn');
        if (btn) { btn.disabled = false; btn.textContent = '🔍 Run Research'; btn.title = 'Search SearXNG for reference material'; }
        return;
    }

    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/agents/for-stage/${stage}`);
        const data = await resp.json();
        const sets = data.agent_sets || [];

        if (sets.length === 0) {
            select.innerHTML = '<option value="">No agents for this stage</option>';
            const btn = document.getElementById('run-agent-btn');
            if (btn) { btn.disabled = true; btn.title = 'No agent prompts configured for this stage'; }
            return;
        }

        select.innerHTML = '';
        sets.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.name;
            opt.textContent = s.name;
            if (s.name === PIECE_AGENT_SET || (!PIECE_AGENT_SET && s.name === 'default')) {
                opt.selected = true;
            }
            select.appendChild(opt);
        });

        const btn = document.getElementById('run-agent-btn');
        if (btn) { btn.disabled = false; btn.textContent = '▶ Run Agent'; btn.title = ''; }
    } catch (e) {
        select.innerHTML = '<option value="default">default</option>';
    }
}

// ── Brief editor ──────────────────────────────────────────────────

if (CURRENT_STAGE === 'brief') {
    document.addEventListener('DOMContentLoaded', async function() {
        const textarea = document.getElementById('brief-editor');
        const statusEl = document.getElementById('brief-status');
        if (!textarea) return;

        try {
            const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/brief`);
            const data = await resp.json();
            textarea.value = data.content || '';
            if (data.has_content) {
                statusEl.textContent = '✓ Brief has content';
                statusEl.style.color = 'var(--accent-green)';
            } else {
                statusEl.textContent = '⚠ No content yet — write your brief below';
                statusEl.style.color = 'var(--accent-yellow)';
            }
        } catch (e) {
            statusEl.textContent = 'Failed to load brief';
            statusEl.style.color = 'var(--accent-red)';
        }
    });
}

async function saveBrief() {
    const textarea = document.getElementById('brief-editor');
    const saveStatus = document.getElementById('brief-save-status');
    const statusEl = document.getElementById('brief-status');
    if (!textarea) return;

    saveStatus.textContent = 'Saving...';
    saveStatus.style.color = 'var(--text-muted)';

    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/brief`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content: textarea.value}),
        });
        const data = await resp.json();
        if (data.status === 'saved') {
            saveStatus.textContent = '✓ Saved';
            saveStatus.style.color = 'var(--accent-green)';
            if (data.has_content) {
                statusEl.textContent = '✓ Brief has content';
                statusEl.style.color = 'var(--accent-green)';
            } else {
                statusEl.textContent = '⚠ No content yet';
                statusEl.style.color = 'var(--accent-yellow)';
            }
            setTimeout(() => { saveStatus.textContent = ''; }, 2000);
        }
    } catch (e) {
        saveStatus.textContent = 'Failed to save';
        saveStatus.style.color = 'var(--accent-red)';
    }
}

// ── Init ──────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async function() {
    // Load initial stage content
    navigateToStage(CURRENT_STAGE);

    // Load chapter badge for draft stage
    loadChapterBadge();

    // Check if auto pipeline is running
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}`);
        const data = await resp.json();
        if (data.running) {
            document.getElementById('auto-btn').style.display = 'none';
            document.getElementById('interrupt-btn').style.display = '';
            document.getElementById('trigger-select').value = data.trigger || 'auto';
            updateButtonStates();
        }
    } catch (e) { /* ignore */ }

    // Load audio files
    loadAudioFiles();
});

// ── Rename ────────────────────────────────────────────────────────

function startRename() {
    document.getElementById('piece-title').style.display = 'none';
    document.getElementById('rename-bar').style.display = 'flex';
    const input = document.getElementById('rename-input');
    input.focus();
    input.select();
}

function cancelRename() {
    document.getElementById('rename-bar').style.display = 'none';
    document.getElementById('piece-title').style.display = '';
}

async function saveRename() {
    const newTitle = document.getElementById('rename-input').value.trim();
    if (!newTitle) return;

    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/rename`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: newTitle})
        });
        const data = await resp.json();
        if (data.error) {
            toast(data.error, 'error');
        } else {
            document.getElementById('piece-title').textContent = newTitle;
            cancelRename();
            toast('Renamed to: ' + newTitle, 'success');
        }
    } catch (e) {
        toast('Rename failed', 'error');
    }
}

// ── Advance ───────────────────────────────────────────────────────

async function advance() {
    const btn = document.getElementById('advance-btn');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Advancing...'; }

    const result = await api(`/api/pieces/${PIECE_ID}/advance`, { method: 'POST' });
    if (result) {
        if (result.run_id) {
            // Auto mode: chain started — show interrupt button and stream progress
            toast('Advanced — auto pipeline running…', 'success');
            document.getElementById('auto-btn').style.display = 'none';
            document.getElementById('interrupt-btn').style.display = '';
            updateButtonStates();
            connectAutoSSE(result.run_id);
        } else {
            toast(`Advanced to ${result.current_stage}`, 'success');
            setTimeout(() => location.reload(), 500);
        }
    } else {
        if (btn) { btn.disabled = false; btn.textContent = `Advance →`; }
    }
}

async function deleteCurrentPiece() {
    if (!confirm(`Are you sure you want to permanently delete this piece? This cannot be undone.`)) {
        return;
    }
    const btn = document.getElementById('delete-piece-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Deleting...';
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}`, { method: 'DELETE' });
        const data = await resp.json();
        if (resp.ok && data.status === 'deleted') {
            toast('Piece deleted successfully', 'success');
            setTimeout(() => {
                window.location.href = `${SCRIPT_ROOT}/`;
            }, 1000);
        } else {
            toast(data.error || 'Failed to delete piece', 'error');
            btn.disabled = false;
            btn.textContent = '🗑 Delete';
        }
    } catch (e) {
        toast(`Error: ${e.message}`, 'error');
        btn.disabled = false;
        btn.textContent = '🗑 Delete';
    }
}

// ── Execute and Save ──────────────────────────────────────────────

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
            loadRunLog();
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

// ── Run Log ───────────────────────────────────────────────────────

function toggleRunLog() {
    const panel = document.getElementById('run-log-panel');
    const toggle = document.getElementById('run-log-toggle');
    if (panel.style.display === 'none') {
        panel.style.display = 'block';
        toggle.textContent = '▼';
        loadRunLog();
    } else {
        panel.style.display = 'none';
        toggle.textContent = '▶';
    }
}

function toggleRunLogEnabled() { /* deprecated */ }

async function loadRunLog() {
    const entriesDiv = document.getElementById('run-log-entries');
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/run-log?limit=30`);
        const data = await resp.json();
        if (!data.entries || data.entries.length === 0) {
            entriesDiv.innerHTML = '<div style="color:var(--text-muted)">No run log entries yet.</div>';
            return;
        }
        entriesDiv.innerHTML = data.entries.map(e => {
            const ts = e.ts ? new Date(e.ts).toLocaleTimeString() : '?';
            const stage = e.stage || '?';
            const call = e.call || '?';
            const decision = e.decision ? `<span style="color:${e.decision === 'advance' ? 'var(--accent-green)' : 'var(--accent-red)'}">${e.decision}</span>` : '';
            const critique = e.critique ? `<div style="color:var(--text-muted);margin-left:16px;white-space:pre-wrap">${e.critique.substring(0, 200)}</div>` : '';
            const chars = e.user_chars ? `${e.user_chars} chars` : '';
            return `<div style="border-bottom:1px solid var(--border);padding:4px 0">${ts} <b>${stage}</b> [${call}] ${decision} <span style="color:var(--text-muted)">${chars}</span>${critique}</div>`;
        }).join('');
    } catch (err) {
        entriesDiv.innerHTML = `<div style="color:var(--accent-red)">Error loading run log: ${err.message}</div>`;
    }
}

// ── Export / Audio / Comic ─────────────────────────────────────────

async function exportGDocs() {
    const btn = document.getElementById('export-gdocs-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Exporting...';
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/export/google-docs`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ stage: VIEWING_STAGE })
        });
        const data = await resp.json();
        if (data.error) { toast(`Export failed: ${data.error}`, 'error'); }
        else { toast('Exported to Google Docs!', 'success'); window.open(data.url, '_blank'); }
    } catch (e) { toast(`Export error: ${e.message}`, 'error'); }
    btn.disabled = false;
    btn.textContent = '📄 Export';
}

async function generateComic() {
    const btn = document.getElementById('comic-btn');
    const styleSelect = document.getElementById('comic-style');
    const style = styleSelect ? styleSelect.value : 'manga';
    btn.disabled = true;
    btn.textContent = '⏳ Generating...';
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/comic`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ stage: VIEWING_STAGE, style: style })
        });
        const data = await resp.json();
        if (data.error) { toast(`Comic failed: ${data.error}`, 'error'); }
        else { toast(`Comic generated (${style} style)!`, 'success'); window.open(`${SCRIPT_ROOT}${data.viewer_url}`, '_blank'); }
    } catch (e) { toast(`Comic error: ${e.message}`, 'error'); }
    btn.disabled = false;
    btn.textContent = '🎨 Comic';
}

document.addEventListener('DOMContentLoaded', loadAudioFiles);

async function loadAudioFiles() {
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/audio`);
        const data = await resp.json();
        const section = document.getElementById('audio-section');
        const container = document.getElementById('audio-files');
        if (data.files && data.files.length > 0) {
            section.style.display = 'block';
            container.innerHTML = data.files.map(f => `
                <div style="display:flex;align-items:center;gap:12px;padding:10px 12px;margin-bottom:6px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px">
                    <span style="font-size:16px">🎵</span>
                    <div style="flex:1">
                        <div style="font-size:13px;font-weight:500">${f.filename}</div>
                        <div style="font-size:11px;color:var(--text-muted)">${(f.size_bytes / 1024).toFixed(0)} KB · ${f.created}</div>
                    </div>
                    <a href="${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/audio/${f.filename}" download class="btn" style="font-size:12px;padding:4px 10px">⬇ Download</a>
                </div>
            `).join('');
        } else {
            section.style.display = 'none';
        }
    } catch (e) { /* silently ignore */ }
}

async function generateAudio() {
    const btn = document.getElementById('generate-audio-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Generating...';
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/audio`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ stage: VIEWING_STAGE })
        });
        const data = await resp.json();
        if (data.error) { toast(`Audio failed: ${data.error}`, 'error'); }
        else { const sizeKB = (data.size_bytes / 1024).toFixed(0); toast(`Audio generated! ${data.filename} (${sizeKB} KB, ${data.voice})`, 'success'); loadAudioFiles(); }
    } catch (e) { toast(`Audio error: ${e.message}`, 'error'); }
    btn.disabled = false;
    btn.textContent = '🔊 Audio';
}

// ── Active-run reconnect on page load ─────────────────────────────
// One-shot check (no polling): if a chain is running when this page opens,
// reconnect to its SSE stream so the UI stays live.
(async function checkActiveRun() {
    try {
        const resp = await fetch(`${SCRIPT_ROOT}/api/pieces/${PIECE_ID}/active-run`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.run_id) {
            // A chain is actively running — hook up the progress stream
            const autoBtn = document.getElementById('auto-btn');
            const interruptBtn = document.getElementById('interrupt-btn');
            if (autoBtn) autoBtn.style.display = 'none';
            if (interruptBtn) interruptBtn.style.display = '';
            updateButtonStates();
            connectAutoSSE(data.run_id);
        }
    } catch (e) {
        // Non-critical — ignore network errors on startup
    }
})();
