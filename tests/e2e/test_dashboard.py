"""E2E tests for the dashboard overview page."""
import pytest
from playwright.sync_api import expect


class TestDashboard:
    """Pieces overview page at /dashboard."""

    def test_dashboard_loads(self, page, base_url):
        """Dashboard page loads and shows pieces heading."""
        page.goto(f"{base_url}/dashboard")
        expect(page.locator("body")).to_contain_text("Pieces", timeout=5000)

    def test_pieces_list_visible(self, page, base_url):
        """At least one piece card visible in the overview."""
        page.goto(f"{base_url}/dashboard")
        # Piece cards or table rows should exist
        pieces = page.locator("[class*='piece'], [class*='card'], tr[data-id], .piece-card")
        expect(pieces.first).to_be_visible(timeout=5000)

    def test_stats_cards_visible(self, page, base_url):
        """Stats cards (total pieces, stages, etc.) are visible."""
        page.goto(f"{base_url}/dashboard")
        # Should have some stats/metrics display
        stats = page.locator("[class*='stat'], [class*='metric'], [class*='card']")
        expect(stats.first).to_be_visible(timeout=5000)

    def test_nav_links_present(self, page, base_url):
        """Navigation links to Pipeline and Agents pages exist."""
        page.goto(f"{base_url}/dashboard")
        pipeline_link = page.locator("a[href*='pipeline']")
        agents_link = page.locator("a[href*='agents']")
        expect(pipeline_link).to_be_attached()
        expect(agents_link).to_be_attached()

    def test_create_piece_button(self, page, base_url):
        """Create piece button or modal trigger exists."""
        page.goto(f"{base_url}/dashboard")
        create_btn = page.locator("button:has-text('Create'), button:has-text('New'), a:has-text('Create')")
        expect(create_btn.first).to_be_attached()


class TestPipelinePage:
    """Pipeline info page at /dashboard/pipeline."""

    def test_pipeline_page_loads(self, page, base_url):
        """Pipeline page loads and shows stages."""
        page.goto(f"{base_url}/dashboard/pipeline")
        expect(page.locator("body")).to_contain_text("brief")

    def test_all_stages_listed(self, page, base_url):
        """All 9 pipeline stages are listed."""
        page.goto(f"{base_url}/dashboard/pipeline")
        for stage in ["brief", "outline", "draft", "review", "revise", "humanize", "validate", "polish", "done"]:
            expect(page.locator("body")).to_contain_text(stage, timeout=3000)


class TestAgentsPage:
    """Agents/flavors page at /dashboard/agents."""

    def test_agents_page_loads(self, page, base_url):
        """Agents page loads."""
        page.goto(f"{base_url}/dashboard/agents")
        expect(page.locator("body")).to_contain_text("agent", timeout=5000)

    def test_flavors_listed(self, page, base_url):
        """At least the default flavor is listed."""
        page.goto(f"{base_url}/dashboard/agents")
        expect(page.locator("body")).to_contain_text("default", timeout=5000)

    def test_model_config_visible(self, page, base_url):
        """Model configuration section is visible."""
        page.goto(f"{base_url}/dashboard/agents")
        page.wait_for_load_state("networkidle")
        body = page.locator("body").inner_text().lower()
        assert any(word in body for word in ["model", "api", "temperature", "agent"]), (
            f"Expected model/agent config text, got: {body[:200]}"
        )
