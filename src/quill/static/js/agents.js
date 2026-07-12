(function() {
    var BASE = (window._SCRIPT_ROOT || '') + '/api/agents';
    var currentSet = '';
    var currentStage = '';

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function fetchJson(url, opts) {
        return fetch(url, opts).then(function(r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    window.loadSets = function() {
        fetchJson(BASE).then(function(data) {
            var container = document.getElementById('agent-sets');
            var selector = document.getElementById('flavor-selector');
            if (!data.sets || data.sets.length === 0) {
                container.innerHTML = '<div class="meta-item"><div class="value" style="color:var(--text-muted)">No agent sets found. Create one in agents/</div></div>';
                return;
            }
            // Populate the dropdown selector
            selector.innerHTML = '';
            data.sets.forEach(function(s) {
                var opt = document.createElement('option');
                opt.value = s.name;
                opt.textContent = s.name + ' — ' + (s.description || s.stages.length + ' stages');
                selector.appendChild(opt);
            });
            // Populate the card grid
            var html = '';
            data.sets.forEach(function(s) {
                html += '<div class="meta-item" style="cursor:pointer;transition:border-color 0.15s" onmouseenter="this.style.borderColor=\'var(--accent-blue)\'" onmouseleave="this.style.borderColor=\'var(--border)\'" onclick="window.showSet(\'' + s.name + '\')">';
                html += '<div class="label">' + esc(s.name) + '</div>';
                html += '<div class="value">' + s.stages.length + ' stages <span style="color:var(--text-muted);font-size:11px">→</span></div>';
                html += '</div>';
            });
            container.innerHTML = html;
            if (data.sets.length > 0) {
                window.showSet(data.sets[0].name);
            }
        });
    };

    window.showSet = function(name) {
        currentSet = name;
        // Sync the dropdown selector
        var selector = document.getElementById('flavor-selector');
        if (selector) selector.value = name;

        fetchJson(BASE + '/' + name).then(function(data) {
            document.getElementById('agent-detail').style.display = 'block';
            document.getElementById('prompt-editor').style.display = 'none';
            document.getElementById('set-desc').textContent = (data.config && data.config.description) || '';

            // Hide delete button for default flavor
            var deleteBtn = document.getElementById('delete-flavor-btn');
            if (deleteBtn) deleteBtn.style.display = (name === 'default') ? 'none' : '';
            document.getElementById('delete-flavor-status').textContent = '';
            document.getElementById('set-max-loops').value = (data.config && data.config.max_loops != null) ? data.config.max_loops : 3;
            document.getElementById('flavor-config-status').textContent = '';

            var list = document.getElementById('prompt-list');
            if (!data.prompts || data.prompts.length === 0) {
                list.innerHTML = '<div style="color:var(--text-muted);margin-top:12px">No prompt templates found.</div>';
                return;
            }
            var html = '';
            data.prompts.forEach(function(p, i) {
                html += '<div class="section" style="margin-top:12px;cursor:pointer" onclick="window.editPrompt(\'' + p.stage + '\')">';
                html += '<div style="display:flex;justify-content:space-between;align-items:center">';
                html += '<div><span style="color:var(--text-muted);font-size:12px;margin-right:8px">' + (i+1) + '.</span><strong>' + esc(p.title) + '</strong>';
                html += '<span style="color:var(--text-muted);font-size:12px;margin-left:8px">' + p.stage + '.prompt.md · ' + p.length + ' chars</span></div>';
                html += '<span style="color:var(--accent-blue);font-size:13px">Edit →</span>';
                html += '</div></div>';
            });
            list.innerHTML = html;
        });
    };

    window.editPrompt = function(stage) {
        currentStage = stage;
        fetchJson(BASE + '/' + currentSet + '/' + stage + '/prompt').then(function(data) {
            document.getElementById('agent-detail').style.display = 'none';
            document.getElementById('prompt-editor').style.display = 'block';
            document.getElementById('editor-title').textContent = currentSet + ' / ' + stage + '.prompt.md';
            document.getElementById('prompt-content').value = data.content || '';
            document.getElementById('save-status').textContent = '';
        });
    };

    window.closeEditor = function() {
        document.getElementById('agent-detail').style.display = 'block';
        document.getElementById('prompt-editor').style.display = 'none';
    };

    window.savePrompt = function() {
        var content = document.getElementById('prompt-content').value;
        fetchJson(BASE + '/' + currentSet + '/' + currentStage + '/prompt', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content: content})
        }).then(function(data) {
            var status = document.getElementById('save-status');
            if (data.status === 'updated') {
                status.textContent = 'Saved (' + data.length + ' chars)';
                status.style.color = 'var(--accent-green)';
            } else {
                status.textContent = 'Error: ' + (data.error || 'unknown');
                status.style.color = 'var(--accent-red)';
            }
        });
    };

    // Create flavor
    window.showCreateFlavor = function() {
        document.getElementById('create-flavor').style.display = 'block';
        document.getElementById('flavor-name').value = '';
        document.getElementById('flavor-desc').value = '';
        document.getElementById('create-flavor-status').textContent = '';
        // Populate source dropdown with existing flavors
        var select = document.getElementById('flavor-source');
        select.innerHTML = '';
        fetchJson(BASE).then(function(data) {
            (data.sets || []).forEach(function(s) {
                var opt = document.createElement('option');
                opt.value = s.name;
                opt.textContent = s.name;
                if (s.name === 'default') opt.selected = true;
                select.appendChild(opt);
            });
        });
    };

    window.hideCreateFlavor = function() {
        document.getElementById('create-flavor').style.display = 'none';
    };

    window.createFlavor = function() {
        var name = document.getElementById('flavor-name').value.trim();
        var desc = document.getElementById('flavor-desc').value.trim();
        var source = document.getElementById('flavor-source').value;
        var status = document.getElementById('create-flavor-status');

        if (!name) {
            status.textContent = 'Name required';
            status.style.color = 'var(--accent-red)';
            return;
        }

        fetchJson(BASE, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name, description: desc, clone_from: source})
        }).then(function(data) {
            if (data.error) {
                status.textContent = data.error;
                status.style.color = 'var(--accent-red)';
            } else {
                status.textContent = 'Created: ' + data.name;
                status.style.color = 'var(--accent-green)';
                window.loadSets(); // Refresh the list
                setTimeout(hideCreateFlavor, 1500);
            }
        });
    };

    window.saveFlavorConfig = function() {
        if (!currentSet) return;
        var maxLoops = parseInt(document.getElementById('set-max-loops').value) || 3;
        var status = document.getElementById('flavor-config-status');

        fetchJson(BASE + '/' + currentSet, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({max_loops: maxLoops})
        }).then(function(data) {
            if (data.error) {
                status.textContent = data.error;
                status.style.color = 'var(--accent-red)';
                toast(data.error, 'error');
            } else {
                status.textContent = '✓ Saved';
                status.style.color = 'var(--accent-green)';
                toast('Saved configuration', 'success');
                setTimeout(function() { status.textContent = ''; }, 2000);
            }
        }).catch(function(err) {
            status.textContent = 'Save failed';
            status.style.color = 'var(--accent-red)';
            toast('Save failed: ' + err.message, 'error');
        });
    };

    window.deleteFlavor = function() {
        if (!currentSet || currentSet === 'default') return;
        if (!confirm('Delete flavor "' + currentSet + '"? This cannot be undone.')) return;

        var status = document.getElementById('delete-flavor-status');
        status.textContent = 'Deleting...';
        status.style.color = 'var(--text-muted)';

        fetch(BASE + '/' + currentSet, {method: 'DELETE'})
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) {
                    status.textContent = data.error;
                    status.style.color = 'var(--accent-red)';
                } else {
                    status.textContent = 'Deleted: ' + data.name;
                    status.style.color = 'var(--accent-green)';
                    window.loadSets(); // Refresh
                    // Switch to default
                    setTimeout(function() { window.showSet('default'); }, 500);
                }
            });
    };


    window.loadSets();
})();
