"""Unit tests for database models."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from quill.models import Base, Project, DocumentNode, StageState, Metrics, AgentLog


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


def test_project_creation(db_session):
    """Test creating a project with optional metadata."""
    project = Project(
        id="test-project",
        title="Test Project",
        genre="fiction",
        type="story",
        audience="general",
        tone="neutral",
        language="en",
        target_length="1000 words",
        constraints=["no passive voice", "short sentences"],
        agent_set="default",
        trigger="on_advance",
    )
    db_session.add(project)
    db_session.commit()

    retrieved = db_session.query(Project).filter_by(id="test-project").first()
    assert retrieved is not None
    assert retrieved.title == "Test Project"
    assert retrieved.genre == "fiction"
    assert retrieved.constraints == ["no passive voice", "short sentences"]
    assert retrieved.current_stage == "brief"
    assert isinstance(retrieved.created_at, datetime)
    assert isinstance(retrieved.updated_at, datetime)


def test_document_node_hierarchy(db_session):
    """Test document nodes and self-referential relationships."""
    project = Project(id="test-proj", title="Project Title")
    db_session.add(project)

    # Create root node
    root = DocumentNode(
        id="test-proj-root",
        project_id="test-proj",
        title="Root Node",
        node_type="project",
    )
    db_session.add(root)

    # Create child nodes
    ch1 = DocumentNode(
        id="test-proj-ch1",
        project_id="test-proj",
        parent_id="test-proj-root",
        title="Chapter 1",
        node_type="chapter",
        order_index=1,
    )
    ch2 = DocumentNode(
        id="test-proj-ch2",
        project_id="test-proj",
        parent_id="test-proj-root",
        title="Chapter 2",
        node_type="chapter",
        order_index=2,
    )
    db_session.add_all([ch1, ch2])
    db_session.commit()

    # Query root node and check children
    retrieved_root = db_session.query(DocumentNode).filter_by(id="test-proj-root").first()
    assert retrieved_root is not None
    assert len(retrieved_root.children) == 2
    assert retrieved_root.children[0].title == "Chapter 1"
    assert retrieved_root.children[1].title == "Chapter 2"
    assert retrieved_root.children[0].parent == retrieved_root


def test_stage_state_relationships(db_session):
    """Test stage states linked to document nodes."""
    project = Project(id="test-proj", title="Project Title")
    node = DocumentNode(id="test-node", project_id="test-proj", title="Node Title")
    db_session.add_all([project, node])

    stage_state = StageState(
        document_node_id="test-node",
        stage="draft",
        state="generating",
        loop_count=2,
        body="This is draft content.",
        decision="loop_back",
        critique="Needs more depth.",
    )
    db_session.add(stage_state)
    db_session.commit()

    retrieved_node = db_session.query(DocumentNode).filter_by(id="test-node").first()
    assert len(retrieved_node.stage_states) == 1
    state = retrieved_node.stage_states[0]
    assert state.stage == "draft"
    assert state.state == "generating"
    assert state.loop_count == 2
    assert state.body == "This is draft content."
    assert state.decision == "loop_back"
    assert state.critique == "Needs more depth."


def test_metrics_retrieval(db_session):
    """Test metrics calculation storage and labeling."""
    project = Project(id="test-proj", title="Project Title")
    node = DocumentNode(id="test-node", project_id="test-proj", title="Node Title")
    db_session.add_all([project, node])

    metric = Metrics(
        document_node_id="test-node",
        stage="draft",
        label="baseline",
        flesch_ease=75.5,
        flesch_kincaid=6.2,
        word_count=450,
        sentence_count=20,
        avg_sentence_length=22.5,
        type_token_ratio=0.62,
        passive_voice_pct=8.5,
    )
    db_session.add(metric)
    db_session.commit()

    retrieved = db_session.query(Metrics).filter_by(document_node_id="test-node").first()
    assert retrieved is not None
    assert retrieved.stage == "draft"
    assert retrieved.label == "baseline"
    assert retrieved.flesch_ease == 75.5
    assert retrieved.word_count == 450
    assert retrieved.type_token_ratio == 0.62


def test_agent_log_creation(db_session):
    """Test append-only AgentLog logging records."""
    project = Project(id="test-proj", title="Project Title")
    node = DocumentNode(id="test-node", project_id="test-proj", title="Node Title")
    db_session.add_all([project, node])

    log = AgentLog(
        project_id="test-proj",
        document_node_id="test-node",
        stage="draft",
        call_type="evaluate",
        model="gpt-4o",
        system_prompt="You are an evaluator.",
        user_prompt="Evaluate this.",
        system_chars=22,
        user_chars=14,
        trace_id="trace-123",
        decision="advance",
        critique="Good work.",
        prompt_tokens=150,
        completion_tokens=50,
        cost=0.003,
        output="Resulting evaluation JSON",
    )
    db_session.add(log)
    db_session.commit()

    retrieved = db_session.query(AgentLog).filter_by(trace_id="trace-123").first()
    assert retrieved is not None
    assert retrieved.model == "gpt-4o"
    assert retrieved.decision == "advance"
    assert retrieved.cost == 0.003
    assert retrieved.system_chars == 22
    assert retrieved.project == project
    assert retrieved.document_node == node


def test_cascade_delete(db_session):
    """Test cascade deletes from project level down to child entities."""
    project = Project(id="test-proj", title="Project Title")
    node = DocumentNode(id="test-node", project_id="test-proj", title="Node Title")
    db_session.add_all([project, node])
    db_session.commit()

    stage_state = StageState(document_node_id="test-node", stage="outline", state="ready")
    metric = Metrics(document_node_id="test-node", stage="outline")
    log = AgentLog(project_id="test-proj", document_node_id="test-node", stage="outline", call_type="generate")
    db_session.add_all([stage_state, metric, log])
    db_session.commit()

    # Verify everything exists
    assert db_session.query(Project).count() == 1
    assert db_session.query(DocumentNode).count() == 1
    assert db_session.query(StageState).count() == 1
    assert db_session.query(Metrics).count() == 1
    assert db_session.query(AgentLog).count() == 1

    # Delete project
    db_session.delete(project)
    db_session.commit()

    # All related models should be deleted via cascade
    assert db_session.query(Project).count() == 0
    assert db_session.query(DocumentNode).count() == 0
    assert db_session.query(StageState).count() == 0
    assert db_session.query(Metrics).count() == 0
    assert db_session.query(AgentLog).count() == 0


def test_utc_now():
    """Test the timezone-naive UTC datetime helper function."""
    from quill.models import utc_now
    from datetime import datetime, timezone
    now = utc_now()
    assert now.tzinfo is None
    # Make sure it matches UTC time closely
    utc_now_val = datetime.now(timezone.utc).replace(tzinfo=None)
    diff = abs((now - utc_now_val).total_seconds())
    assert diff < 5

