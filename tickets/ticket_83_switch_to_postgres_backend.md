# Ticket 83: Switch Application Backend to PostgreSQL

## Description
Update the Quill application codebase to use PostgreSQL as the primary database backend and remove the hard dependency on SQLite.

## Background
Following the creation of the migration script (Ticket 82), the application needs to be formally transitioned to utilize PostgreSQL in production and development environments. This ensures that the system benefits from Postgres's robustness, concurrency, and scaling capabilities while eliminating reliance on local file-based databases for primary state.

## Tasks
- [ ] **Dependency Update**:
    - [ ] Add `psycopg2-binary` (or `pg8000`) to project requirements.
    - [ ] Remove any SQLite-specific dependencies if they are no longer needed for optional local testing.
- [ ] **Database Configuration Refactor**:
    - [ ] Update the database engine initialization logic to use a configurable `DATABASE_URL`.
    - [ ] Implement environment variable loading (e.g., via `.env`) to handle DB credentials securely.
    - [ ] Ensure SQLAlchemy is configured for the PostgreSQL dialect.
- [ ] **Code Cleanup**:
    - [ ] Audit the codebase for any SQLite-specific SQL or PRAGMA statements and replace them with standard SQL or Postgres-compatible equivalents.
    - [ ] Remove hardcoded paths to `.db` files in the initialization sequence.
- [ ] **Documentation Update**:
    - [ ] Update `README.md` and setup guides to include instructions for spinning up a PostgreSQL instance (e.g., via Docker Compose).
    - [ ] Document the required environment variables for DB connectivity.
- [ ] **Validation**:
    - [ ] Verify that the application starts and executes all core pipeline flows using the Postgres backend.
    - [ ] Ensure the migration script from Ticket 82 successfully populates this new environment.

## Success Criteria
- [ ] The application no longer requires a local SQLite file to function.
- [ ] All database operations are performed against a PostgreSQL instance.
- [ ] Development and production environments use `DATABASE_URL` for connectivity.
- [ ] Application boot time and core feature performance remain stable or improve.

## Priority
High (Blocks final deployment stability)

---
**Next Expected Ticket Number**: 84
