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
    // Will be overridden by template if ProxyFix sends X-Forwarded-Prefix
    if (window._SCRIPT_ROOT) return window._SCRIPT_ROOT;
    // Auto-detect from location
    var p = location.pathname;
    var parts = p.split('/').filter(Boolean);
    // If we're at /quill/dashboard, base is /quill
    if (parts.length > 1) return '/' + parts[0];
    return '';
})();
