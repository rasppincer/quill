"""E2E tests that catch JavaScript errors and broken fetch calls."""
import pytest
from playwright.sync_api import expect


class TestNoConsoleErrors:
    """Verify no JS errors on key pages."""

    def _get_first_piece_id(self, base_url):
        import requests
        resp = requests.get(f"{base_url}/api/pieces")
        pieces = resp.json().get("pieces", [])
        return pieces[0]["id"] if pieces else None

    def test_dashboard_no_js_errors(self, page, base_url):
        """Dashboard loads without JavaScript errors."""
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(f"{base_url}/dashboard")
        page.wait_for_load_state("networkidle")
        assert len(errors) == 0, f"JS errors: {errors}"

    def test_piece_detail_no_js_errors(self, page, base_url):
        """Piece detail loads without JavaScript errors."""
        piece_id = self._get_first_piece_id(base_url)
        if not piece_id:
            pytest.skip("No pieces")

        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(f"{base_url}/pieces/{piece_id}")
        page.wait_for_load_state("networkidle")
        assert len(errors) == 0, f"JS errors: {errors}"

    def test_agents_page_no_js_errors(self, page, base_url):
        """Agents page loads without JavaScript errors."""
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(f"{base_url}/dashboard/agents")
        page.wait_for_load_state("networkidle")
        assert len(errors) == 0, f"JS errors: {errors}"

    def test_no_failed_api_calls_on_dashboard(self, page, base_url):
        """No API calls return 4xx/5xx on the dashboard page."""
        failed = []
        page.on("response", lambda resp: failed.append(f"{resp.status} {resp.url}")
                if resp.status >= 400 else None)
        page.goto(f"{base_url}/dashboard")
        page.wait_for_load_state("networkidle")
        assert len(failed) == 0, f"Failed API calls: {failed}"

    def test_no_failed_api_calls_on_piece_detail(self, page, base_url):
        """No API calls return 4xx/5xx on the piece detail page."""
        piece_id = self._get_first_piece_id(base_url)
        if not piece_id:
            pytest.skip("No pieces")

        failed = []
        page.on("response", lambda resp: failed.append(f"{resp.status} {resp.url}")
                if resp.status >= 400 else None)
        page.goto(f"{base_url}/pieces/{piece_id}")
        page.wait_for_load_state("networkidle")
        assert len(failed) == 0, f"Failed API calls: {failed}"


class TestFetchPaths:
    """Verify the frontend fetch calls hit the correct API paths."""

    def test_pieces_api_called(self, page, base_url):
        """Dashboard fetches /api/pieces."""
        api_calls = []
        page.on("request", lambda req: api_calls.append(req.url)
                if "/api/" in req.url else None)
        page.goto(f"{base_url}/dashboard")
        page.wait_for_load_state("networkidle")
        assert any("/api/pieces" in url for url in api_calls), f"No /api/pieces call: {api_calls}"

    def test_agents_api_called_on_agents_page(self, page, base_url):
        """Agents page fetches /api/agents."""
        api_calls = []
        page.on("request", lambda req: api_calls.append(req.url)
                if "/api/" in req.url else None)
        page.goto(f"{base_url}/dashboard/agents")
        page.wait_for_load_state("networkidle")
        assert any("/api/agents" in url for url in api_calls), f"No /api/agents call: {api_calls}"

    def test_piece_detail_fetches_piece_data(self, page, base_url):
        """Piece detail fetches /api/pieces/<id>."""
        import requests
        resp = requests.get(f"{base_url}/api/pieces")
        pieces = resp.json().get("pieces", [])
        if not pieces:
            pytest.skip("No pieces")
        piece_id = pieces[0]["id"]

        api_calls = []
        page.on("request", lambda req: api_calls.append(req.url)
                if "/api/" in req.url else None)
        page.goto(f"{base_url}/pieces/{piece_id}")
        page.wait_for_load_state("networkidle")
        assert any(f"/api/pieces/{piece_id}" in url for url in api_calls), (
            f"No /api/pieces/{piece_id} call: {api_calls}"
        )
