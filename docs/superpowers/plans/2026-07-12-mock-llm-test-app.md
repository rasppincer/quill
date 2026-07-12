# Mock LLM in tests/test_app.py Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up `tests/test_app.py` by mocking the `LLMClient` class globally for all tests except `TestRunAgent`.

**Architecture:** Add a new autouse fixture `mock_llm_client` in `tests/test_app.py` that intercepts calls to `LLMClient` and returns a mock client that responds with a dummy JSON string satisfying all response schemas.

**Tech Stack:** Python, pytest, unittest.mock

## Global Constraints
None

---

### Task 1: Add Mocking Fixture to `tests/test_app.py`

**Files:**
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `unittest.mock.patch`, `unittest.mock.MagicMock`
- Produces: Autouse fixture `mock_llm_client` mocking `quill.runner.LLMClient`

- [ ] **Step 1: Insert `mock_llm_client` fixture in `tests/test_app.py`**

Modify: [tests/test_app.py](file:///home/bob/projects/quill/tests/test_app.py) around line 37 by adding the new fixture under the existing fixtures block:

```python
@pytest.fixture(autouse=True)
def mock_llm_client(request):
    """Mock LLMClient globally for all app tests except TestRunAgent."""
    if "TestRunAgent" in request.node.nodeid:
        yield
        return

    with patch("quill.runner.LLMClient") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.chat.return_value = (
            '{"decision": "advance", "reason": "Mocked reason", '
            '"critique": "Mocked critique", "content": "Mocked content"}'
        )
        mock_cls.return_value = mock_instance
        yield
```

- [ ] **Step 2: Run pytest to verify speedup**

Run:
```bash
.venv/bin/pytest tests/test_app.py
```
Expected: The test run completes successfully in under 2 seconds.

- [ ] **Step 3: Commit the changes**

Run:
```bash
git add tests/test_app.py
git commit -m "test: mock LLMClient globally in test_app.py to speed up tests"
```
