import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from quill.models import Base, Project, DocumentNode, StageState
from quill.engine import WorkflowEngine, workflow_engine

@pytest.fixture
def db_session():
    """Create an in-memory SQLite database and session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def setup_project_with_chapters(db_session):
    """Set up a test project with 3 chapters in the database."""
    project = Project(
        id="proj-123",
        title="Test Project",
        genre="fiction",
        current_stage="draft",
        trigger="auto"
    )
    node_p = DocumentNode(id="proj-123", project_id="proj-123", node_type="project", title="Test Project")
    
    node_c1 = DocumentNode(id="proj-123-chapter-1", project_id="proj-123", parent_id="proj-123", node_type="chapter", title="Chapter 1")
    node_c2 = DocumentNode(id="proj-123-chapter-2", project_id="proj-123", parent_id="proj-123", node_type="chapter", title="Chapter 2")
    node_c3 = DocumentNode(id="proj-123-chapter-3", project_id="proj-123", parent_id="proj-123", node_type="chapter", title="Chapter 3")
    
    db_session.add_all([project, node_p, node_c1, node_c2, node_c3])
    db_session.commit()
    return project

def test_engine_sequential_progression(db_session, setup_project_with_chapters):
    """Test that engine progresses sequentially from Chapter 1 to Chapter 2."""
    # Chapter 1 completes draft
    c1_state = StageState(
        document_node_id="proj-123-chapter-1",
        stage="draft",
        status="completed",
        output_text="Chapter 1 content"
    )
    db_session.add(c1_state)
    db_session.commit()

    with patch("quill.engine.WorkflowEngine._dispatch_task") as mock_dispatch:
        workflow_engine.evaluate_and_dispatch(db_session, "proj-123-chapter-1", "draft")
        # Should dispatch draft on Chapter 2
        mock_dispatch.assert_called_once_with("proj-123-chapter-2", "draft", db_session)

def test_engine_cascade_revision_strategy(db_session, setup_project_with_chapters):
    """Test that cascade strategy re-runs flagged chapter and all downstream chapters."""
    # Setup completed draft for all chapters
    for i in range(1, 4):
        db_session.add(StageState(
            document_node_id=f"proj-123-chapter-{i}",
            stage="draft",
            status="completed",
            output_text=f"Chapter {i} draft content"
        ))
    db_session.commit()

    # Completed review stage for all chapters
    for i in range(1, 4):
        db_session.add(StageState(
            document_node_id=f"proj-123-chapter-{i}",
            stage="review",
            status="completed",
            output_text=f"Chapter {i} review content"
        ))
    db_session.commit()

    # Parent completes review_decision with reject and critique targeting Chapter 2
    proj_decision = StageState(
        document_node_id="proj-123",
        stage="review_decision",
        status="completed",
        output_text='{"decision": "reject", "critique": "Please fix Chapter 2 pacing."}'
    )
    db_session.add(proj_decision)
    db_session.commit()

    # Mock project config for strategy
    setup_project_with_chapters.revision_strategy = "cascade"
    db_session.commit()

    with patch("quill.engine.WorkflowEngine._dispatch_task") as mock_dispatch:
        workflow_engine.evaluate_and_dispatch(db_session, "proj-123", "review_decision")
        
        # Verify revise states
        c1_revise = db_session.query(StageState).filter_by(document_node_id="proj-123-chapter-1", stage="revise").first()
        c2_revise = db_session.query(StageState).filter_by(document_node_id="proj-123-chapter-2", stage="revise").first()
        c3_revise = db_session.query(StageState).filter_by(document_node_id="proj-123-chapter-3", stage="revise").first()

        # Chapter 1 should be skipped (status completed, output copied from draft)
        assert c1_revise is not None
        assert c1_revise.status == "completed"
        assert c1_revise.output_text == "Chapter 1 draft content"

        # Chapters 2 and 3 should be marked new (to run)
        assert c2_revise is not None
        assert c2_revise.status == "new"
        
        assert c3_revise is not None
        assert c3_revise.status == "new"

        # Should dispatch revise on Chapter 2 (the earliest new/non-completed chapter)
        mock_dispatch.assert_called_once_with("proj-123-chapter-2", "revise", db_session)

def test_engine_surgical_revision_strategy(db_session, setup_project_with_chapters):
    """Test that surgical strategy re-runs ONLY flagged chapter."""
    for i in range(1, 4):
        db_session.add(StageState(
            document_node_id=f"proj-123-chapter-{i}",
            stage="draft",
            status="completed",
            output_text=f"Chapter {i} draft content"
        ))
    db_session.commit()

    proj_decision = StageState(
        document_node_id="proj-123",
        stage="review_decision",
        status="completed",
        output_text='{"decision": "reject", "critique": "Please fix Chapter 2 pacing."}'
    )
    db_session.add(proj_decision)
    db_session.commit()

    setup_project_with_chapters.revision_strategy = "surgical"
    db_session.commit()

    with patch("quill.engine.WorkflowEngine._dispatch_task") as mock_dispatch:
        workflow_engine.evaluate_and_dispatch(db_session, "proj-123", "review_decision")
        
        c1_revise = db_session.query(StageState).filter_by(document_node_id="proj-123-chapter-1", stage="revise").first()
        c2_revise = db_session.query(StageState).filter_by(document_node_id="proj-123-chapter-2", stage="revise").first()
        c3_revise = db_session.query(StageState).filter_by(document_node_id="proj-123-chapter-3", stage="revise").first()

        assert c1_revise.status == "completed"
        assert c2_revise.status == "new"
        assert c3_revise.status == "completed"

        mock_dispatch.assert_called_once_with("proj-123-chapter-2", "revise", db_session)

def test_engine_global_critique_fallback(db_session, setup_project_with_chapters):
    """Test that global critique defaults to Chapter 1 cascade (re-run all)."""
    for i in range(1, 4):
        db_session.add(StageState(
            document_node_id=f"proj-123-chapter-{i}",
            stage="draft",
            status="completed",
            output_text=f"Chapter {i} draft content"
        ))
    db_session.commit()

    proj_decision = StageState(
        document_node_id="proj-123",
        stage="review_decision",
        status="completed",
        output_text='{"decision": "reject", "critique": "General pacing issues across the entire book."}'
    )
    db_session.add(proj_decision)
    db_session.commit()

    setup_project_with_chapters.revision_strategy = "cascade"
    db_session.commit()

    with patch("quill.engine.WorkflowEngine._dispatch_task") as mock_dispatch:
        workflow_engine.evaluate_and_dispatch(db_session, "proj-123", "review_decision")
        
        c1_revise = db_session.query(StageState).filter_by(document_node_id="proj-123-chapter-1", stage="revise").first()
        c2_revise = db_session.query(StageState).filter_by(document_node_id="proj-123-chapter-2", stage="revise").first()
        c3_revise = db_session.query(StageState).filter_by(document_node_id="proj-123-chapter-3", stage="revise").first()

        # All chapters should be re-run
        assert c1_revise.status == "new"
        assert c2_revise.status == "new"
        assert c3_revise.status == "new"

        mock_dispatch.assert_called_once_with("proj-123-chapter-1", "revise", db_session)
