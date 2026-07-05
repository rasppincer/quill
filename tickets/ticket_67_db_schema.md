# Ticket 67: Design Database Schema & Models

## Description
Design the relational database schema to replace `meta.yaml` and filesystem-based frontmatter tracking. Define SQL tables for Projects, Documents (Nodes), StageStates, AgentLogs, and Metrics.

## Background
Currently, piece metadata is loaded by parsing frontmatter from all markdown files in a piece directory and loading `meta.yaml`. In a redesign, a SQL database ensures consistency, transactions, and indexable queries.

## Tasks
- [x] Define SQLAlchemy/SQLModel models for `Project` (top-level piece metadata).
- [x] Define models for `DocumentNode` (representing files/chapters in a tree structure).
- [x] Define models for `StageState` (stages, states like generating/ready, loops, and timestamps).
- [x] Define models for `Metrics` (readability scores, word count, type-token ratio).
- [x] Define models for `AgentLog` (append-only record of LLM calls, costs, and decisions).

## Success Criteria
- [x] Schema models cover all existing fields in `meta.yaml`, frontmatter, metrics, and `run-log.jsonl`.
- [x] Models support self-referential parent-child relationships for hierarchical nodes.

## Priority
High

---
**Next Expected Ticket Number**: 68
