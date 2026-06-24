"""Playwright E2E tests for Quill dashboard.

Covers: trigger save, brief editor, disabled buttons, agent dropdown.
"""
import pytest
from playwright.sync_api import expect, Page


QUILL = "http://localhost:8325"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "base_url": QUILL}


def _find_brief_piece(page: Page) -> str | None:
    """Find a piece currently at the brief stage via API."""
    import json, urllib.request
    try:
        with urllib.request.urlopen(f"{QUILL}/api/pieces", timeout=5) as resp:
            data = json.loads(resp.read())
            for p in data.get("pieces", []):
                if p.get("current_stage") == "brief":
                    return p["id"]
    except Exception:
        pass
    return None


class TestAgentsTab:
    """Trigger dropdown and save feedback."""

    def test_trigger_dropdown_has_three_options(self, page: Page):
        page.goto("/dashboard/agents")
        page.locator("#set-trigger").wait_for(state="visible", timeout=5000)
        options = page.locator("#set-trigger option")
        assert options.count() == 3
        values = [options.nth(i).get_attribute("value") for i in range(3)]
        assert "on_advance" in values
        assert "auto" in values
        assert "manual" in values

    def test_trigger_save_shows_feedback(self, page: Page):
        page.goto("/dashboard/agents")
        page.locator("#set-trigger").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(1000)  # Wait for flavor to load
        page.locator("#set-trigger").select_option("auto")
        page.evaluate("window.saveFlavorConfig()")
        # Status element shows "Saved" on success
        status = page.locator("#flavor-config-status")
        expect(status).to_contain_text("Saved", timeout=5000)

    def test_trigger_save_inline_feedback(self, page: Page):
        page.goto("/dashboard/agents")
        page.locator("#set-trigger").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(1000)  # Wait for flavor to load
        page.locator("#set-trigger").select_option("on_advance")
        page.evaluate("window.saveFlavorConfig()")
        status = page.locator("#flavor-config-status")
        expect(status).to_contain_text("Saved", timeout=5000)


class TestBriefEditor:
    """Brief stage textarea and content guard."""

    def test_brief_editor_visible_at_brief_stage(self, page: Page):
        piece_id = _find_brief_piece(page)
        if not piece_id:
            pytest.skip("No piece at brief stage")
        page.goto(f"/pieces/{piece_id}")
        editor = page.locator("#brief-editor")
        expect(editor).to_be_visible(timeout=5000)

    def test_brief_editor_has_save_button(self, page: Page):
        piece_id = _find_brief_piece(page)
        if not piece_id:
            pytest.skip("No piece at brief stage")
        page.goto(f"/pieces/{piece_id}")
        save_btn = page.locator("button", has_text="Save Brief")
        expect(save_btn).to_be_visible(timeout=5000)

    def test_brief_editor_shows_content(self, page: Page):
        piece_id = _find_brief_piece(page)
        if not piece_id:
            pytest.skip("No piece at brief stage")
        page.goto(f"/pieces/{piece_id}")
        editor = page.locator("#brief-editor")
        expect(editor).to_be_visible(timeout=5000)
        # Should have some content loaded
        value = editor.input_value()
        assert len(value) > 0, "Brief editor should have content"


class TestDisabledButtons:
    """Disabled button styling."""

    def test_disabled_run_agent_at_brief(self, page: Page):
        piece_id = _find_brief_piece(page)
        if not piece_id:
            pytest.skip("No piece at brief stage")
        page.goto(f"/pieces/{piece_id}")
        btn = page.locator("#run-agent-btn")
        expect(btn).to_be_visible(timeout=5000)
        assert btn.is_disabled(), "Run Agent should be disabled at brief stage"
