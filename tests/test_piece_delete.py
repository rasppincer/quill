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
