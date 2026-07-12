# Design Spec: Mock LLM Client in tests/test_app.py

Mock the `LLMClient` globally for all tests in `tests/test_app.py` (except `TestRunAgent`) to prevent them from attempting real network calls to the offline port 9999, speeding up the test run.

## Proposed Changes

### [tests/test_app.py](file:///home/bob/projects/quill/tests/test_app.py)

Add an autouse fixture `mock_llm_client` at the top of the file (under the fixtures section) that mocks `LLMClient` for all classes except `TestRunAgent`:

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

## Verification Plan

### Manual Verification
Run the tests:
```bash
.venv/bin/pytest tests/test_app.py
```
Observe that the tests run successfully and complete in < 2 seconds.
