"""Unit tests for database initialization and config."""

import os
from unittest.mock import patch
from quill.db import db, engine, SessionLocal
from quill.models import Base, Project


def test_db_setup():
    """Test that SQLAlchemy db and engine are setup correctly."""
    assert db is not None
    assert engine is not None
    assert SessionLocal is not None


def test_db_session_standalone():
    """Test that standalone session can write and read from database."""
    # Ensure tables are created on the engine
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        # Clean up any existing test project
        session.query(Project).filter_by(id="standalone-test").delete()
        session.commit()

        project = Project(id="standalone-test", title="Standalone Test")
        session.add(project)
        session.commit()

        retrieved = session.query(Project).filter_by(id="standalone-test").first()
        assert retrieved is not None
        assert retrieved.title == "Standalone Test"

        session.delete(retrieved)
        session.commit()
    finally:
        session.close()


def test_flask_app_db_uri():
    """Test that Flask app gets the correct SQLALCHEMY_DATABASE_URI config."""
    from quill.app import create_app

    # We patch os.environ to check factory setup
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}):
        app = create_app()
        assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"
