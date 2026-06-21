"""Behave environment hooks for API tests."""
import os
import shutil
import tempfile
from pathlib import Path

import yaml

API_BASE = "http://127.0.0.1:8325"
OUTPUT_DIR = Path.home() / "projects" / "quill" / "output"


def before_all(context):
    """Set up shared state."""
    context.api_base = API_BASE
    context.temp_dir = tempfile.mkdtemp(prefix="quill-behave-")
    context.created_pieces = []


def after_all(context):
    """Clean up temp files."""
    if hasattr(context, "temp_dir") and os.path.exists(context.temp_dir):
        shutil.rmtree(context.temp_dir, ignore_errors=True)


def before_scenario(context, scenario):
    """Reset scenario-level state and clean up leftover test pieces."""
    context.response = None
    context.piece_id = None
    context.error = None
    # Clean up any leftover test pieces from previous runs
    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and d.name.startswith(("test-", "my-", "chain-", "no-agent",
                                                   "single-", "format-", "runner-",
                                                   "reject-", "body-", "done-", "dupe-",
                                                   "chain-skip", "the-cognitive-",
                                                   "renamed-", "frontmatter-")):
                shutil.rmtree(d, ignore_errors=True)
