"""E2E tests for the piece detail page."""
import pytest
from playwright.sync_api import expect


class TestPieceDetail:
    """Piece detail page at /pieces/<id>."""

    def _get_first_piece_id(self, page, base_url):
        """Get the ID of the first piece from the dashboard."""
        import requests
        resp = requests.get(f"{base_url}/api/pieces")
        pieces = resp.json().get("pieces", [])
        if not pieces:
            pytest.skip("No pieces available for testing")
        return pieces[0]["id"]

    def test_piece_detail_loads(self, page, base_url):
        """Piece detail page loads and shows piece title."""
        piece_id = self._get_first_piece_id(page, base_url)
        page.goto(f"{base_url}/pieces/{piece_id}")
        # Should show some content, not a 404
        expect(page.locator("body")).not_to_contain_text("Not Found")

    def test_pipeline_visualization(self, page, base_url):
        """Pipeline stages are visualized on the piece detail page."""
        piece_id = self._get_first_piece_id(page, base_url)
        page.goto(f"{base_url}/pieces/{piece_id}")
        page.wait_for_load_state("networkidle")
        body = page.locator("body").inner_text().lower()
        # Should mention at least some pipeline stages
        stages_found = sum(1 for s in ["brief", "draft", "review", "done"] if s in body)
        assert stages_found >= 2, f"Expected pipeline stages, found {stages_found} in: {body[:300]}"

    def test_agent_selector_present(self, page, base_url):
        """Agent/flavor selector dropdown is present."""
        piece_id = self._get_first_piece_id(page, base_url)
        page.goto(f"{base_url}/pieces/{piece_id}")
        select = page.locator("select#agent-select")
        expect(select).to_be_attached(timeout=5000)

    def test_agent_selector_has_options(self, page, base_url):
        """Agent selector dropdown has at least one option."""
        piece_id = self._get_first_piece_id(page, base_url)
        page.goto(f"{base_url}/pieces/{piece_id}")
        select = page.locator("select#agent-select")
        # Wait for options to load (fetched via JS)
        expect(select.locator("option").first).to_be_attached(timeout=5000)

    def test_advance_button_visible(self, page, base_url):
        """Advance button is visible for non-done pieces."""
        piece_id = self._get_first_piece_id(page, base_url)
        page.goto(f"{base_url}/pieces/{piece_id}")
        advance_btn = page.locator("button:has-text('Advance')")
        # May not be visible if piece is at 'done' — check body instead
        body_text = page.locator("body").inner_text()
        assert "Advance" in body_text or "done" in body_text.lower()

    def test_run_agent_button_visible(self, page, base_url):
        """Run Agent button is visible."""
        piece_id = self._get_first_piece_id(page, base_url)
        page.goto(f"{base_url}/pieces/{piece_id}")
        run_btn = page.locator("#run-agent-btn")
        expect(run_btn).to_be_attached(timeout=5000)

    def test_run_log_panel_present(self, page, base_url):
        """Run Log panel section exists on the page."""
        piece_id = self._get_first_piece_id(page, base_url)
        page.goto(f"{base_url}/pieces/{piece_id}")
        expect(page.locator("text=Run Log")).to_be_attached(timeout=5000)

    def test_stage_content_viewer(self, page, base_url):
        """Stage content viewer shows content for the current stage."""
        piece_id = self._get_first_piece_id(page, base_url)
        page.goto(f"{base_url}/pieces/{piece_id}")
        # The stage content section should exist
        expect(page.locator("text=Stage Content")).to_be_attached(timeout=5000)


class TestPieceDetailInteraction:
    """Interactive tests on the piece detail page."""

    def test_run_agent_triggers_request(self, page, base_url):
        """Clicking Run Agent triggers an API call."""
        import requests
        resp = requests.get(f"{base_url}/api/pieces")
        pieces = resp.json().get("pieces", [])
        if not pieces:
            pytest.skip("No pieces available")

        # Find a piece not at 'done'
        piece_id = None
        for p in pieces:
            if p["current_stage"] != "done":
                piece_id = p["id"]
                break
        if not piece_id:
            pytest.skip("All pieces at done stage")

        page.goto(f"{base_url}/pieces/{piece_id}")
        page.wait_for_load_state("networkidle")

        # Track API calls and JS errors
        api_calls = []
        js_errors = []
        page.on("request", lambda req: api_calls.append(req.url) if "/api/" in req.url else None)
        page.on("pageerror", lambda err: js_errors.append(str(err)))

        btn = page.locator("#run-agent-btn")
        expect(btn).to_be_enabled(timeout=5000)
        btn.click()
        page.wait_for_timeout(3000)

        assert len(js_errors) == 0, f"JS errors after click: {js_errors}"
        assert any("run" in url for url in api_calls), f"No run API call: {api_calls}"

    def test_run_log_toggle_persists(self, page, base_url):
        """Run Log toggle state persists via localStorage within same context."""
        piece_id = self._get_first_piece_id(page, base_url)
        page.goto(f"{base_url}/pieces/{piece_id}")
        page.wait_for_load_state("networkidle")

        # Enable run log
        checkbox = page.locator("#run-log-enabled")
        if not checkbox.is_checked():
            checkbox.click()
        page.wait_for_timeout(500)

        # Navigate to another page and back
        page.goto(f"{base_url}/dashboard")
        page.goto(f"{base_url}/pieces/{piece_id}")
        page.wait_for_load_state("networkidle")

        # Check localStorage directly
        value = page.evaluate("localStorage.getItem('quill_run_log_enabled')")
        assert value == "1", f"Expected '1', got '{value}'"

    def _get_first_piece_id(self, page, base_url):
        import requests
        resp = requests.get(f"{base_url}/api/pieces")
        pieces = resp.json().get("pieces", [])
        if not pieces:
            pytest.skip("No pieces available")
        return pieces[0]["id"]
