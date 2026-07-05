# Ticket 70: Implement Directory Sync Script for Legacy Support

## Description
Build a utility command/script to import existing pieces under the `output/` directory into the SQL database.

## Background
Users already have existing pieces stored as directories with YAML files and markdown stages. A sync utility is needed to populate the database on migrate.

## Tasks
- [x] Create `scripts/db_sync.py` or a Flask CLI command (`flask sync-legacy`).
- [x] Implement parser to scan the `output/` folder, parse each piece directory (`meta.yaml` and stage files), and insert records into database tables.
- [x] Handle deduplication (skip already imported pieces or update them).

## Success Criteria
- [x] Running `flask sync-legacy` successfully imports all existing pieces from `output/` into SQL tables.
- [x] Database contains correct stages, states, metrics, and loop histories from files.

## Priority
Medium

---
**Next Expected Ticket Number**: 71
