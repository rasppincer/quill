# Ticket 82: SQLite to Postgres Migration Script

## Description
Develop a Python migration script to move all existing piece data, metadata, and system configurations from the current SQLite database to a PostgreSQL instance.

## Background
The project currently relies on SQLite for local persistence. While sufficient for early development, migrating to PostgreSQL is necessary to support higher concurrency, improved reliability, and better scaling as the application grows. A structured migration path is needed to ensure that existing user data (pieces) can be transitioned without loss or corruption.

## Tasks
- [ ] Audit current SQLite schema to identify all tables, constraints, and relationships.
- [ ] Define the target PostgreSQL schema (ensuring compatibility with SQLAlchemy models).
- [x] Implement a migration script (using SQLAlchemy/psycopg2) that:
    - [ ] Connects to both source (SQLite) and destination (Postgres) databases.
    - [ ] Transfers data in correct dependency order (e.g., parent pieces before child pieces).
    - [ ] Handles type conversions if necessary (e.g., JSON fields in SQLite $\rightarrow$ JSONB in Postgres).
- [ ] Create a verification suite to validate the migration:
    - [ ] Compare row counts across all tables.
    - [ ] Perform checksums or sample checks on complex piece content.
- [ ] Update application configuration/environment variables to allow switching between DB backends (e.g., `DATABASE_URL`).

## Success Criteria
- [ ] The migration script completes successfully without data loss.
- [ ] Application boots and operates normally when connected to the PostgreSQL backend.
- [ ] All existing pieces are accessible and intact in the new database.

## Priority
Medium

---
**Next Expected Ticket Number**: 83
