"""Shared utilities for blueprints."""

from ..pipeline import Pipeline, load_pipeline


def get_pipeline() -> Pipeline:
    """Get the default pipeline (cached by mtime in load_pipeline)."""
    return load_pipeline("default")


def reload_pipeline() -> Pipeline:
    """Force reload the pipeline (touch the YAML file, then call this)."""
    from ..pipeline import _pipeline_cache
    _pipeline_cache.clear()
    return load_pipeline("default")
