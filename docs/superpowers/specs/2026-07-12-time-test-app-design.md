# Design Spec: Measure tests/test_app.py Execution Times

Determine which test methods in `tests/test_app.py` run slowly by instrumenting them with the `@timeit` decorator.

## Proposed Changes

### [tests/test_app.py](file:///home/bob/projects/quill/tests/test_app.py)

At the bottom of `tests/test_app.py`, we will dynamically decorate all methods in test classes starting with `Test` using a dynamic module-level setup:

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

## Verification Plan

### Manual Verification
Run the tests using the following command to display `INFO` level timeit logs in real-time:
```bash
.venv/bin/pytest -o log_cli=true --log-cli-level=INFO tests/test_app.py
```
Observe which tests take longer than 0.1s.
