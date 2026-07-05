# Ticket 68: SQLite Integration & Migration Engine

## Description
Configure database connections, session management, and database initialization logic. Set up Alembic for handling future database migrations.

## Background
The initial backend will use SQLite for simplicity and local execution, with the option to swap to PostgreSQL. Alembic will manage schema versioning.

## Tasks
- [ ] Set up database configuration using environment variables (`DATABASE_URL`).
- [ ] Create `src/quill/db.py` to initialize SQL engine and sessionmaker.
- [ ] Initialize Alembic migration scripts and create initial migration.
- [ ] Add db initialization hooks to Flask application startup.

## Success Criteria
- [ ] Running Flask server automatically creates the SQLite database if it doesn't exist.
- [ ] Database migrations can be run successfully via CLI commands (`flask db upgrade`).

## Priority
High

---
**Next Expected Ticket Number**: 69
