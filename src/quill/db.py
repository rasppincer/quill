"""Database session and engine management.

Provides standard SQLAlchemy engine, SessionLocal, and db_session for standalone
scripts, as well as the Flask-SQLAlchemy db object for web request contexts.

Requires DATABASE_URL to be set in the environment pointing at a PostgreSQL
instance (e.g. postgresql://user:pass@host:5432/dbname).
"""

from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from flask_sqlalchemy import SQLAlchemy

from .models import Base

# Database URI — required; no fallback intentional.
# Set QUILL_TESTING=1 to allow SQLite in-memory URLs (test suite only).
DATABASE_URL = os.environ.get("DATABASE_URL")
_is_testing = os.environ.get("QUILL_TESTING") == "1"
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Set it to a PostgreSQL connection string, e.g.: "
        "postgresql://user:pass@host:5432/dbname"
    )
if DATABASE_URL.startswith("sqlite") and not _is_testing:
    raise RuntimeError(
        "DATABASE_URL is set to a SQLite URL. "
        "Quill requires PostgreSQL. "
        "Update DATABASE_URL to a postgresql:// connection string."
    )

# Standalone SQLAlchemy configuration (for workers and tasks)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = scoped_session(SessionLocal)

# Flask-SQLAlchemy instance configured with the same Base metadata
db = SQLAlchemy(model_class=Base)

