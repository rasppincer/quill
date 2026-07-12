async function loadPieces() {
    const data = await api('/api/pieces');
    if (!data) return;

    // Stats cards
    const stats = document.getElementById('stats');
    const total = data.count;
    const active = data.pieces.filter(p => p.current_stage !== 'done').length;
    const done = data.pieces.filter(p => p.current_stage === 'done').length;
    const avgProgress = total > 0
        ? Math.round(data.pieces.reduce((s, p) => s + (p.progress?.percent || 0), 0) / total)
        : 0;

    stats.innerHTML = `
        <div class="card"><div class="label">Total Pieces</div><div class="value blue">${total}</div></div>
        <div class="card"><div class="label">In Progress</div><div class="value orange">${active}</div></div>
        <div class="card"><div class="label">Completed</div><div class="value green">${done}</div></div>
        <div class="card"><div class="label">Avg Progress</div><div class="value purple">${avgProgress}%</div></div>
    `;

    // Table
    const tbody = document.getElementById('pieces-table');
    if (total === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty"><p>No pieces yet.</p><p>Create your first piece to get started.</p></td></tr>';
        return;
    }

    tbody.innerHTML = data.pieces.map(p => {
        let titleHtml = `<a href="${SCRIPT_ROOT}/pieces/${esc(p.id)}" style="color:var(--accent-blue);text-decoration:none;font-weight:600">${esc(p.title)}</a>`;
        if (p.parent) {
            titleHtml += ` <span style="font-size:10px;color:var(--text-muted)" title="Chapter of ${esc(p.parent)}">📖</span>`;
        }
        if (p.children && p.children.length > 0) {
            titleHtml += ` <span style="font-size:10px;color:var(--accent-purple)" title="${p.children.length} chapters">📚${p.children.length}</span>`;
        }
        return `
        <tr>
            <td>${titleHtml}</td>
            <td style="color:var(--text-secondary)">${esc(p.genre)}</td>
            <td><span class="badge ${p.current_stage}">${esc(p.current_stage)}</span></td>
            <td style="min-width:120px">
                <div style="display:flex;align-items:center;gap:8px">
                    <div class="progress-bar" style="flex:1"><div class="fill ${p.progress?.percent >= 100 ? 'green' : 'blue'}" style="width:${p.progress?.percent || 0}%"></div></div>
                    <span style="font-size:12px;color:var(--text-muted)">${p.progress?.percent || 0}%</span>
                </div>
            </td>
            <td style="color:var(--text-muted);font-size:12px">${esc(p.updated || '')}</td>
            <td>
                <div style="display:flex;gap:8px">
                    <a href="${SCRIPT_ROOT}/pieces/${esc(p.id)}" class="btn sm">View</a>
                    <button class="btn sm danger" onclick="deletePiece(event, '${esc(p.id)}', '${esc(p.title)}')">Delete</button>
                </div>
            </td>
        </tr>
    `;}).join('');
}

function showCreateModal() {
    document.getElementById('create-modal').style.display = 'block';
}

function closeModal() {
    document.getElementById('create-modal').style.display = 'none';
}

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

async function deletePiece(event, id, title) {
    event.preventDefault();
    event.stopPropagation();
    if (!confirm(`Are you sure you want to permanently delete "${title}"? This cannot be undone.`)) {
        return;
    }
    try {
        const response = await fetch(`${SCRIPT_ROOT}/api/pieces/${id}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        if (response.ok && data.status === 'deleted') {
            toast(`Deleted "${title}"`, 'success');
            loadPieces();
        } else {
            toast(data.error || 'Failed to delete piece', 'error');
        }
    } catch (e) {
        toast(`Error: ${e.message}`, 'error');
    }
}

loadPieces();
