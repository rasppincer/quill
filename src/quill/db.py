"""Database session and engine management.

Provides standard SQLAlchemy engine, SessionLocal, and db_session for standalone
scripts, as well as the Flask-SQLAlchemy db object for web request contexts.
"""

from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from flask_sqlalchemy import SQLAlchemy

from .models import Base

# Database URI from environment
DATABASE_URL = os.environ.get("DATABASE_URL") or "sqlite:///quill.db"

# Connection arguments (e.g., disable check_same_thread for SQLite)
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# Standalone SQLAlchemy configuration (for workers and tasks)
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = scoped_session(SessionLocal)

# Flask-SQLAlchemy instance configured with the same Base metadata
db = SQLAlchemy(model_class=Base)
