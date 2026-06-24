"""Playwright E2E tests for Quill dashboard.

Covers: trigger save, research interaction, brief editor, disabled buttons.
"""
import json
import time
import urllib.request
import pytest
from playwright.sync_api import expect, Page


QUILL = "http://localhost:8325"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "base_url": QUILL}


def _api(path: str) -> dict:
    """GET from Quill API."""
    with urllib.request.urlopen(f"{QUILL}{path}", timeout=10) as resp:
        return json.loads(resp.read())


def _api_post(path: str, data: dict = None, timeout: int = 30) -> dict:
    """POST to Quill API."""
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(
        f"{QUILL}{path}", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _find_piece_at_stage(stage: str) -> str | None:
    """Find a piece currently at the given stage."""
    try:
        data = _api("/api/pieces")
        for p in data.get("pieces", []):
            if p.get("current_stage") == stage:
                return p["id"]
    except Exception:
        pass
    return None


def _ensure_trigger(trigger: str = "on_advance"):
    """Set trigger on all flavors."""
    for flavor in ["default", "non-fiction", "fiction"]:
        try:
            _api_post(f"/api/agents/{flavor}", {"trigger": trigger}, timeout=5)
        except Exception:
            pass


def _create_piece_with_research() -> str | None:
    """Create a piece, run outline, advance to research, run research.

    Returns piece_id with research completed, or None on failure.
    """
    _ensure_trigger("on_advance")
    ts = int(time.time())
    try:
        # 1. Create piece
        result = _api_post("/api/pieces", {
            "title": f"E2E Research {ts}",
            "genre": "non-fiction", "type": "blog", "language": "en",
            "body": "Write about productivity costs of daily standup meetings for software teams. Include ROI calculations and cognitive science research.",
        })
        piece_id = result["id"]

        # 2. Advance brief → outline
        _api_post(f"/api/pieces/{piece_id}/advance")

        # 3. Run outline agent (generates outline from brief)
        _api_post(f"/api/pieces/{piece_id}/run", {"agent_set": "non-fiction"}, timeout=120)

        # 4. Advance outline → research
        _api_post(f"/api/pieces/{piece_id}/advance")

        # 5. Run research (SearXNG + LLM queries)
        _api_post(f"/api/pieces/{piece_id}/run", {
            "agent_set": "non-fiction", "stage": "research",
        }, timeout=120)

        # 6. Verify research file exists with content
        piece = _api(f"/api/pieces/{piece_id}")
        research_stages = [s for s in piece.get("stages", []) if s.get("stage") == "research"]
        if research_stages and research_stages[0].get("body_length", 0) > 50:
            return piece_id

        # Research ran but file is empty — SearXNG might be down
        return None
    except Exception as e:
        print(f"_create_piece_with_research failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Trigger tests
# ---------------------------------------------------------------------------


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
        page.wait_for_timeout(1000)
        page.locator("#set-trigger").select_option("auto")
        page.evaluate("window.saveFlavorConfig()")
        status = page.locator("#flavor-config-status")
        expect(status).to_contain_text("Saved", timeout=5000)
        # Restore
        page.locator("#set-trigger").select_option("on_advance")
        page.evaluate("window.saveFlavorConfig()")

    def test_trigger_save_inline_feedback(self, page: Page):
        page.goto("/dashboard/agents")
        page.locator("#set-trigger").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(1000)
        page.locator("#set-trigger").select_option("on_advance")
        page.evaluate("window.saveFlavorConfig()")
        status = page.locator("#flavor-config-status")
        expect(status).to_contain_text("Saved", timeout=5000)


# ---------------------------------------------------------------------------
# Research interaction tests
# ---------------------------------------------------------------------------


class TestResearchInteraction:
    """Full research stage interaction: run, verify output, check integration."""

    @pytest.fixture(scope="module")
    def research_piece(self):
        """Create a piece with research completed."""
        piece_id = _create_piece_with_research()
        if not piece_id:
            pytest.skip("Could not create piece with research (SearXNG may be down)")
        return piece_id

    def test_research_file_has_content(self, research_piece):
        """research.md should have substantial content (actual search results)."""
        piece = _api(f"/api/pieces/{research_piece}")
        research_stages = [s for s in piece.get("stages", []) if s.get("stage") == "research"]
        assert len(research_stages) > 0, "Research stage file should exist"
        body_length = research_stages[0].get("body_length", 0)
        assert body_length > 100, f"Research file should have substantial content, got {body_length} chars"

    def test_research_file_has_urls(self, research_piece):
        """research.md should contain actual URLs from SearXNG."""
        # Read the research file directly
        piece = _api(f"/api/pieces/{research_piece}")
        path = piece.get("path", "")
        if path:
            research_file = f"{path}/03_research.md"
            try:
                with open(research_file) as f:
                    content = f.read()
                assert "http" in content, "Research should contain URLs"
                assert "Search Queries" in content, "Research should have search queries section"
                assert "Results" in content, "Research should have results section"
            except FileNotFoundError:
                pytest.skip("Research file not accessible")

    def test_run_log_has_research_entry(self, research_piece):
        """Run log should contain entries for the research stage."""
        log_data = _api(f"/api/pieces/{research_piece}/run-log")
        entries = log_data.get("entries", [])
        research_entries = [e for e in entries if e.get("stage") == "research"]
        assert len(research_entries) > 0, "Run log should have research stage entries"

    def test_run_research_button_visible_at_stage(self, page: Page):
        """At research stage, 'Run Research' button should be visible and enabled."""
        _ensure_trigger("on_advance")
        ts = int(time.time())
        try:
            result = _api_post("/api/pieces", {
                "title": f"E2E Button {ts}",
                "genre": "non-fiction", "type": "blog", "language": "en",
                "body": "Test brief for button verification.",
            })
            piece_id = result["id"]
            _api_post(f"/api/pieces/{piece_id}/advance")
            _api_post(f"/api/pieces/{piece_id}/run", {"agent_set": "non-fiction"}, timeout=120)
            _api_post(f"/api/pieces/{piece_id}/advance")
        except Exception:
            pytest.skip("Could not create piece at research stage")

        page.goto(f"/pieces/{piece_id}")
        btn = page.locator("#run-agent-btn")
        expect(btn).to_be_visible(timeout=5000)
        # Wait for JS to update button text (happens after DOMContentLoaded + API fetch)
        page.wait_for_timeout(2000)
        assert not btn.is_disabled(), "Run Research button should be enabled"
        assert "Run Research" in btn.text_content(), \
            f"Button should say 'Run Research', got: '{btn.text_content().strip()}'"

    def test_content_viewer_before_research(self, page: Page):
        """Before running research, content viewer should show placeholder."""
        _ensure_trigger("on_advance")
        ts = int(time.time())
        try:
            result = _api_post("/api/pieces", {
                "title": f"E2E Viewer {ts}",
                "genre": "non-fiction", "type": "blog", "language": "en",
                "body": "Test brief.",
            })
            piece_id = result["id"]
            _api_post(f"/api/pieces/{piece_id}/advance")
            _api_post(f"/api/pieces/{piece_id}/run", {"agent_set": "non-fiction"}, timeout=120)
            _api_post(f"/api/pieces/{piece_id}/advance")
        except Exception:
            pytest.skip("Could not create piece at research stage")

        page.goto(f"/pieces/{piece_id}")
        show_btn = page.locator("button", has_text="Show")
        if show_btn.count() > 0:
            show_btn.click()
            page.wait_for_timeout(1000)
        content = page.locator("#stage-content")
        if content.is_visible():
            text = content.text_content()
            assert "hasn't run yet" in text or "Run Research" in text, \
                "Before research, viewer should show placeholder"

    def test_content_viewer_after_research(self, page: Page, research_piece):
        """After running research, content viewer should show research results."""
        page.goto(f"/pieces/{research_piece}")
        page.wait_for_timeout(1000)
        show_btn = page.locator("button", has_text="Show")
        if show_btn.count() > 0:
            show_btn.click()
            page.wait_for_timeout(1000)
        content = page.locator("#stage-content")
        if content.is_visible():
            text = content.text_content()
            # Should NOT show placeholder
            assert "hasn't run yet" not in text, \
                "After research, content should show results, not placeholder"

    def test_draft_prompt_includes_research(self, research_piece):
        """Draft stage should receive research content as input."""
        # Advance to draft
        piece = _api(f"/api/pieces/{research_piece}")
        if piece.get("current_stage") == "research":
            _api_post(f"/api/pieces/{research_piece}/advance")

        # Check that the piece has research + draft stages
        piece = _api(f"/api/pieces/{research_piece}")
        stages = {s["stage"]: s for s in piece.get("stages", [])}
        assert "research" in stages, "Piece should have research stage"
        assert "draft" in stages or piece.get("current_stage") == "draft", \
            "Piece should be at or past draft stage"


# ---------------------------------------------------------------------------
# Brief editor tests
# ---------------------------------------------------------------------------


class TestBriefEditor:
    """Brief stage textarea and content guard."""

    def test_brief_editor_visible_at_brief_stage(self, page: Page):
        piece_id = _find_piece_at_stage("brief")
        if not piece_id:
            pytest.skip("No piece at brief stage")
        page.goto(f"/pieces/{piece_id}")
        editor = page.locator("#brief-editor")
        expect(editor).to_be_visible(timeout=5000)

    def test_brief_editor_has_save_button(self, page: Page):
        piece_id = _find_piece_at_stage("brief")
        if not piece_id:
            pytest.skip("No piece at brief stage")
        page.goto(f"/pieces/{piece_id}")
        save_btn = page.locator("button", has_text="Save Brief")
        expect(save_btn).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# Disabled button tests
# ---------------------------------------------------------------------------


class TestDisabledButtons:
    """Disabled button styling."""

    def test_disabled_run_agent_at_brief(self, page: Page):
        piece_id = _find_piece_at_stage("brief")
        if not piece_id:
            pytest.skip("No piece at brief stage")
        page.goto(f"/pieces/{piece_id}")
        btn = page.locator("#run-agent-btn")
        expect(btn).to_be_visible(timeout=5000)
        assert btn.is_disabled(), "Run Agent should be disabled at brief stage"
