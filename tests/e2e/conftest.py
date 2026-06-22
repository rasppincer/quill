"""Playwright E2E tests for Quill dashboard."""
import pytest

BASE_URL = "http://localhost:8325"


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture
def page(context):
    """Page with generous timeout for LLM calls."""
    page = context.new_page()
    page.set_default_timeout(15000)
    yield page
