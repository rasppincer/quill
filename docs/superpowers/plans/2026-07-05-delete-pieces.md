# Delete Pieces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a feature to permanently delete pieces/projects from both the SQLite database and the filesystem (`output/` directory) via the API and UI.

**Architecture:** Add a new `DELETE /api/pieces/<piece_id>` endpoint in the pieces blueprint. Cascade delete project and node database records, and remove the output directory/standalone file. Update Dashboard and Piece Detail HTML templates with confirming UI buttons.

**Tech Stack:** Python, Flask, SQLAlchemy, HTML, JavaScript.

## Global Constraints
- No placeholder or incomplete code blocks.
- Check for running processes via `RunManager` before deletion to prevent aborting active runs.
- Database deletion cascades to all child/relational tables.
- Filesystem cleanup removes the output directory or standalone legacy file if they exist.

---

### Task 1: Backend Delete Route
**Files:**
- Create: `tests/test_piece_delete.py`
- Modify: `src/quill/blueprints/pieces.py`

**Interfaces:**
- Consumes: Database session, `Project` and `DocumentNode` models, `RunManager.is_piece_running` check.
- Produces: `DELETE /api/pieces/<piece_id>` endpoint returning JSON `{"status": "deleted", "id": "<piece_id>"}` on success, `404` if not found, and `409` if running.

- [ ] **Step 1: Write the tests for delete endpoint**
Create the file `tests/test_piece_delete.py` with the following content:
```python
import pytest
from unittest.mock import patch
from quill.db import db_session
from quill.models import Project, DocumentNode

def test_delete_piece_success(client, tmp_output):
    session = db_session()
    
    # Setup database records
    project = Project(id="test-delete", title="Test Delete")
    node = DocumentNode(id="test-delete", project_id="test-delete", title="Test Delete", node_type="project")
    session.add(project)
    session.add(node)
    session.commit()
    
    # Setup filesystem directory
    path = tmp_output / "test-delete"
    path.mkdir(exist_ok=True)
    (path / "meta.yaml").write_text("id: test-delete\ntitle: Test Delete\n", encoding="utf-8")
    
    # Ensure setup was successful
    assert session.query(Project).filter_by(id="test-delete").first() is not None
    assert path.exists()
    
    # Action
    resp = client.delete("/api/pieces/test-delete")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "deleted", "id": "test-delete"}
    
    # Verify cleanup
    session = db_session() # refresh session
    assert session.query(Project).filter_by(id="test-delete").first() is None
    assert session.query(DocumentNode).filter_by(id="test-delete").first() is None
    assert not path.exists()

def test_delete_piece_not_found(client):
    resp = client.delete("/api/pieces/non-existent")
    assert resp.status_code == 404
    assert "not found" in resp.get_json()["error"]

def test_delete_piece_running(client, tmp_output):
    session = db_session()
    
    # Setup database records
    project = Project(id="test-delete-running", title="Test Delete Running")
    node = DocumentNode(id="test-delete-running", project_id="test-delete-running", title="Test Delete Running", node_type="project")
    session.add(project)
    session.add(node)
    session.commit()
    
    # Mock RunManager.is_piece_running to return True
    with patch("quill.run_manager.RunManager.is_piece_running", return_value=True):
        resp = client.delete("/api/pieces/test-delete-running")
        assert resp.status_code == 409
        assert "running" in resp.get_json()["error"]
        
    # Verify records were NOT deleted
    assert session.query(Project).filter_by(id="test-delete-running").first() is not None
    
    # Cleanup
    session.delete(project)
    session.delete(node)
    session.commit()
```

- [ ] **Step 2: Run tests to verify they fail**
Run: `pytest tests/test_piece_delete.py -v`
Expected: FAIL with `405 Method Not Allowed` or `404 Not Found` for the delete endpoint calls.

- [ ] **Step 3: Implement the DELETE endpoint**
Add the following endpoint definition to `src/quill/blueprints/pieces.py`:
```python
@bp.route("/api/pieces/<piece_id>", methods=["DELETE"])
def pieces_delete(piece_id: str):
    """Delete a piece/project from database and filesystem."""
    from ..models import Project, DocumentNode
    from ..db import db_session
    from ..piece import DEFAULT_OUTPUT_DIR
    from ..runner import RunManager
    import shutil
    import os

    session = db_session()
    
    project = session.query(Project).filter_by(id=piece_id).first()
    node = session.query(DocumentNode).filter_by(id=piece_id).first()
    
    if not project and not node:
        return jsonify({"error": f"Piece '{piece_id}' not found"}), 404

    if RunManager().is_piece_running(piece_id):
        return jsonify({"error": "Cannot delete piece while it has a running agent job"}), 409

    try:
        if project:
            session.delete(project)
        if node:
            session.delete(node)
        session.commit()
    except Exception as e:
        session.rollback()
        return jsonify({"error": f"Failed to delete database records: {str(e)}"}), 500

    try:
        path = DEFAULT_OUTPUT_DIR / piece_id
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
            
        legacy_path = DEFAULT_OUTPUT_DIR / f"{piece_id}.md"
        if legacy_path.exists() and legacy_path.is_file():
            os.remove(legacy_path)
    except Exception as e:
        logger.warning("Failed to delete filesystem directory for piece '%s': %s", piece_id, e)
        
    return jsonify({"status": "deleted", "id": piece_id})
```

- [ ] **Step 4: Run tests to verify they pass**
Run: `pytest tests/test_piece_delete.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
Run:
```bash
git add tests/test_piece_delete.py src/quill/blueprints/pieces.py
git commit -m "feat: add DELETE /api/pieces/<piece_id> API route and tests"
```

---

### Task 2: Dashboard UI integration
**Files:**
- Modify: `src/quill/templates/dashboard.html`

**Interfaces:**
- Consumes: `DELETE /api/pieces/<piece_id>` endpoint.

- [ ] **Step 1: Update pieces table row layout**
In `src/quill/templates/dashboard.html` modify the `tbody.innerHTML` mapping in the `loadPieces()` function (lines 130-132) to replace the single "View" button with a flex container holding both a "View" and a "Delete" button:
```javascript
            <td>
                <div style="display:flex;gap:8px">
                    <a href="${SCRIPT_ROOT}/pieces/${esc(p.id)}" class="btn sm">View</a>
                    <button class="btn sm danger" onclick="deletePiece(event, '${esc(p.id)}', '${esc(p.title)}')">Delete</button>
                </div>
            </td>
```

- [ ] **Step 2: Add deletePiece JavaScript handler**
In `src/quill/templates/dashboard.html` add the following function inside the script block before `loadPieces();` at the bottom:
```javascript
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
```

- [ ] **Step 3: Commit**
Run:
```bash
git add src/quill/templates/dashboard.html
git commit -m "fe: add delete button and handler to pieces list on Dashboard"
```

---

### Task 3: Piece Detail UI integration
**Files:**
- Modify: `src/quill/templates/piece.html`

**Interfaces:**
- Consumes: `DELETE /api/pieces/<piece_id>` endpoint.

- [ ] **Step 1: Add Delete button in the action bar**
In `src/quill/templates/piece.html` add the Delete button inside the action-bar header next to `#comic-btn` or the output controls (near lines 105-108):
```html
    <button class="btn danger" id="delete-piece-btn" onclick="deleteCurrentPiece()" style="margin-left:8px" title="Delete this piece permanently">
        🗑 Delete
    </button>
```

- [ ] **Step 2: Add deleteCurrentPiece JavaScript handler**
In `src/quill/templates/piece.html` add the `deleteCurrentPiece` function in the script block:
```javascript
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
```

- [ ] **Step 3: Commit**
Run:
```bash
git add src/quill/templates/piece.html
git commit -m "fe: add Delete button and handler in Piece Detail view"
```
