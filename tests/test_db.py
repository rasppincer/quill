"""Unit tests for database initialization and config."""

import os
import importlib
import pytest
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


def test_flask_app_requires_postgres_url():
    """Test that db.py raises if DATABASE_URL is a SQLite URL (without QUILL_TESTING)."""
    import subprocess
    import sys
    env = dict(os.environ)
    env["DATABASE_URL"] = "sqlite:///should-fail.db"
    if "QUILL_TESTING" in env:
        del env["QUILL_TESTING"]
    
    res = subprocess.run(
        [sys.executable, "-c", "import quill.db"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "Quill requires PostgreSQL" in res.stderr or "Quill requires PostgreSQL" in res.stdout


def test_flask_app_raises_on_missing_url():
    """Test that db.py raises if DATABASE_URL is completely absent."""
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "QUILL_TESTING")}
    
    res = subprocess.run(
        [sys.executable, "-c", "import quill.db"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "DATABASE_URL environment variable is not set" in res.stderr or "DATABASE_URL environment variable is not set" in res.stdout

