# Resolve Datetime Deprecation Warnings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve datetime.utcnow() deprecation warnings by replacing them with a timezone-naive UTC helper function.

**Architecture:** Define helper `utc_now()` in models.py and import/use it across the codebase.

**Tech Stack:** Python 3.13, SQLAlchemy, pytest

## Global Constraints

- Python >=3.10
- Maintain timezone-naive datetimes for SQLite/SQLAlchemy compatibility.

---

### Task 1: Define `utc_now` helper and update defaults in models.py

**Files:**
- Modify: `src/quill/models.py:9-40`
- Modify: `src/quill/models.py:60-70`
- Modify: `src/quill/models.py:100-110`
- Modify: `src/quill/models.py:130-140`
- Modify: `src/quill/models.py:150-155`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: None
- Produces: `utc_now() -> datetime` timezone-naive UTC datetime helper

- [ ] **Step 1: Write a unit test for utc_now helper**

  Add the following test to `tests/test_models.py`:
  ```python
  def test_utc_now():
      from quill.models import utc_now
      from datetime import datetime, timezone
      now = utc_now()
      assert now.tzinfo is None
      # Make sure it matches UTC time closely
      utc_now_val = datetime.now(timezone.utc).replace(tzinfo=None)
      diff = abs((now - utc_now_val).total_seconds())
      assert diff < 5
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run: `.venv/bin/pytest tests/test_models.py::test_utc_now -v`
  Expected: FAIL with ImportError or AttributeError (utc_now not defined)

- [ ] **Step 3: Implement `utc_now` helper in models.py**

  Add `utc_now` to `src/quill/models.py`:
  ```python
  from datetime import timezone

  def utc_now() -> datetime:
      """Return timezone-naive UTC datetime."""
      return datetime.now(timezone.utc).replace(tzinfo=None)
  ```

- [ ] **Step 4: Update models schema column defaults to use `utc_now`**

  In `src/quill/models.py`, replace all references of `default=datetime.utcnow` with `default=utc_now`, and `onupdate=datetime.utcnow` with `onupdate=utc_now`.
  
  Specifically:
  - `Project.created_at`: default=utc_now
  - `Project.updated_at`: default=utc_now, onupdate=utc_now
  - `DocumentNode.created_at`: default=utc_now
  - `DocumentNode.updated_at`: default=utc_now, onupdate=utc_now
  - `StageState.updated_at`: default=utc_now, onupdate=utc_now
  - `Metrics.updated_at`: default=utc_now, onupdate=utc_now
  - `AgentLog.timestamp`: default=utc_now

- [ ] **Step 5: Run tests to verify it passes**

  Run: `.venv/bin/pytest tests/test_models.py -v`
  Expected: PASS

- [ ] **Step 6: Commit**

  ```bash
  git add src/quill/models.py tests/test_models.py
  git commit -m "refactor: define utc_now helper and update SQLAlchemy models defaults"
  ```

---

### Task 2: Replace `datetime.utcnow()` in `piece.py`

**Files:**
- Modify: `src/quill/piece.py`
- Test: `tests/test_piece.py`

- [ ] **Step 1: Update imports in piece.py**

  Import `utc_now` in `src/quill/piece.py`:
  ```python
  from .models import Project, DocumentNode, StageState, utc_now
  ```

- [ ] **Step 2: Replace all `datetime.utcnow()` calls with `utc_now()`**

  In `src/quill/piece.py`, replace all occurrences of `datetime.utcnow()` with `utc_now()`.

- [ ] **Step 3: Run piece tests**

  Run: `.venv/bin/pytest tests/test_piece.py -v`
  Expected: PASS

- [ ] **Step 4: Commit**

  ```bash
  git add src/quill/piece.py
  git commit -m "refactor: replace datetime.utcnow with utc_now in piece.py"
  ```

---

### Task 3: Replace `datetime.utcnow()` in `cli.py`

**Files:**
- Modify: `src/quill/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Update imports in cli.py**

  Import `utc_now` in `src/quill/cli.py`:
  ```python
  from .models import Project, DocumentNode, StageState, Metrics, utc_now
  ```

- [ ] **Step 2: Replace all `datetime.utcnow()` calls with `utc_now()`**

  In `src/quill/cli.py`, replace all occurrences of `datetime.utcnow()` with `utc_now()`.

- [ ] **Step 3: Run cli tests**

  Run: `.venv/bin/pytest tests/test_cli.py -v`
  Expected: PASS

- [ ] **Step 4: Commit**

  ```bash
  git add src/quill/cli.py
  git commit -m "refactor: replace datetime.utcnow with utc_now in cli.py"
  ```
