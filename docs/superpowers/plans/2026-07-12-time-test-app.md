# Timing tests/test_app.py Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument `tests/test_app.py` with `@timeit` to output execution times of all tests in that module.

**Architecture:** Append a module-level dynamic wrapper block at the bottom of `tests/test_app.py` that loops through all subclasses starting with `Test` and decorates their `test_*` methods with `@timeit`.

**Tech Stack:** Python, pytest

## Global Constraints
None

---

### Task 1: Add Dynamic Decoration Block to `tests/test_app.py`

**Files:**
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `quill.timeit.timeit`
- Produces: Dynamically decorated test methods inside `tests/test_app.py`

- [ ] **Step 1: Append timing instrumentation block to `tests/test_app.py`**

Modify: [tests/test_app.py](file:///home/bob/projects/quill/tests/test_app.py) by appending this code at the bottom of the file (lines 736+):

```python
# ---------------------------------------------------------------------------
# Timing Instrumentation
# ---------------------------------------------------------------------------

from quill.timeit import timeit

for name, obj in list(globals().items()):
    if isinstance(obj, type) and name.startswith("Test"):
        for attr_name, attr_val in list(obj.__dict__.items()):
            if attr_name.startswith("test_") and callable(attr_val):
                setattr(obj, attr_name, timeit(f"{name}.{attr_name}")(attr_val))
```

- [ ] **Step 2: Run pytest to verify log output**

Run the following command:
```bash
.venv/bin/pytest -o log_cli=true --log-cli-level=INFO tests/test_app.py
```
Expected: The tests run, and you see `[timeit] TestClassName.test_method: X.XXs` logs for each test.

- [ ] **Step 3: Commit the changes**

Run:
```bash
git add tests/test_app.py
git commit -m "test: dynamically decorate test_app.py tests with @timeit"
```
