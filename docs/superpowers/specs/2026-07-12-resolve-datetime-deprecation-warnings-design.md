# Spec: Resolve Datetime Deprecation Warnings

We will replace the deprecated `datetime.utcnow()` with a timezone-naive UTC datetime helper function `utc_now()`. This resolves the 850+ deprecation warnings generated during testing, while maintaining backward compatibility and preventing type comparison errors between timezone-aware and timezone-naive datetime objects.

## Proposed Changes

### Centralized Utility Function

We will define `utc_now` in `src/quill/models.py`:
```python
from datetime import timezone

def utc_now() -> datetime:
    """Return timezone-naive UTC datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
```

### Models Column Defaults

In `src/quill/models.py`, replace SQLAlchemy column defaults that use `datetime.utcnow`:
- Change `default=datetime.utcnow` to `default=utc_now`
- Change `onupdate=datetime.utcnow` to `onupdate=utc_now`

### Core Code Call Sites

Import `utc_now` from `quill.models` and replace `datetime.utcnow()` calls with `utc_now()` in:
- `src/quill/piece.py`
- `src/quill/cli.py`

## Verification Plan

### Automated Tests
- Run `pytest` and verify that all tests pass and the 850+ `DeprecationWarning`s are resolved.
