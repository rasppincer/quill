# Ticket 69: Refactor Piece Model for Database Storage

## Description
Refactor the `Piece` class in `src/quill/piece.py` to read and write metadata/stages to and from the database, while maintaining compatibility with legacy files.

## Background
`Piece` currently loads states from the filesystem. Refactoring it to interact with the DB requires shifting its persistence methods (`save`, `load`, `advance_to`, `supersede_from`) to SQL queries while keeping its public API intact.

## Tasks
- [ ] Modify `Piece.save()` to write to the SQL database tables (Project, DocumentNode, StageState).
- [ ] Implement `load_piece()` to fetch data from database tables instead of scanning `meta.yaml` and files.
- [ ] Add dual-write / compatibility flags to write markdown files to the `output/` directory for legacy visual support (user inspects markdown on disk).
- [ ] Ensure existing unit tests for `Piece` pass with database persistence.

## Success Criteria
- [ ] Writing/loading pieces persists to database.
- [ ] Legacy API routes return matching schema properties from SQL database.
- [ ] All `pytest tests/test_piece.py` pass.

## Priority
High

---
**Next Expected Ticket Number**: 70
