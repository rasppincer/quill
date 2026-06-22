"""Shared utilities for blueprints."""

from functools import lru_cache
from ..pipeline import Pipeline, load_pipeline


@lru_cache(maxsize=1)
def _cached_pipeline() -> Pipeline:
    """Load and cache the default pipeline."""
    return load_pipeline("default")


def get_pipeline() -> Pipeline:
    """Get the default pipeline (cached)."""
    return _cached_pipeline()


def reload_pipeline() -> Pipeline:
    """Force reload the pipeline (e.g. after YAML edit)."""
    _cached_pipeline.cache_clear()
    return _cached_pipeline()
