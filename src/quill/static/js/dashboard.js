/* Quill dashboard utilities */


function esc(str) {
    const el = document.createElement('span');
    el.textContent = str || '';
    return el.innerHTML;
}

function toast(msg, type = 'info') {
    const container = document.querySelector('.toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
}

async function api(path, opts = {}) {
    try {
        const resp = await fetch(SCRIPT_ROOT + path, {
            headers: { 'Content-Type': 'application/json', ...opts.headers },
            ...opts,
        });
        const data = await resp.json();
        if (!resp.ok) {
            toast(data.error || `HTTP ${resp.status}`, 'error');
            return null;
        }
        return data;
    } catch (e) {
        toast('Network error', 'error');
        return null;
    }
}

// Escape key closes modals
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        const modal = document.querySelector('.modal-overlay');
        if (modal) modal.remove();
    }
});

// Click outside closes modal
document.addEventListener('click', e => {
    if (e.target.classList.contains('modal-overlay')) {
        e.target.remove();
    }
});
// Auto-detect base path: if at /quill/dashboard, base is /quill
var SCRIPT_ROOT = (function() {
    // Will be set by template via ProxyFix X-Forwarded-Prefix (empty string for direct access)
    if (window._SCRIPT_ROOT !== undefined && window._SCRIPT_ROOT !== null) return window._SCRIPT_ROOT;
    // Auto-detect from location (fallback if template didn't set it)
    var p = location.pathname;
    var parts = p.split('/').filter(Boolean);
    // If we're at /quill/dashboard, base is /quill
    if (parts.length > 1) return '/' + parts[0];
    return '';
})();
