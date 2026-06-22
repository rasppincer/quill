"""SearchClient — SearXNG HTTP wrapper for web search.

Provides a clean interface for querying a local SearXNG instance.
No Quill knowledge — pure HTTP client that returns structured results.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_SEARXNG_URL = "http://localhost:8888"
DEFAULT_TIMEOUT = 10
DEFAULT_LIMIT = 5


@dataclass
class SearchResult:
    """A single search result from SearXNG."""

    title: str
    url: str
    snippet: str
    engine: str = ""

    def to_markdown(self) -> str:
        """Format as a markdown link with snippet."""
        parts = [f"### [{self.title}]({self.url})"]
        if self.engine:
            parts.append(f"*Source: {self.engine}*")
        if self.snippet:
            parts.append(self.snippet)
        return "\n".join(parts)


class SearchClient:
    """SearXNG HTTP client.

    Args:
        base_url: SearXNG instance URL (default: http://localhost:8888).
        timeout: HTTP request timeout in seconds.
    """

    def __init__(self, base_url: str = DEFAULT_SEARXNG_URL,
                 timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def search(self, query: str, limit: int = DEFAULT_LIMIT) -> list[SearchResult]:
        """Execute a search query against SearXNG.

        Args:
            query: Search query string.
            limit: Maximum number of results to return.

        Returns:
            List of SearchResult objects. Empty list on error.
        """
        params = urllib.parse.urlencode({
            "q": query,
            "format": "json",
            "pageno": 1,
        })
        url = f"{self.base_url}/search?{params}"

        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "Quill/1.0",
            })
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
            logger.warning("SearXNG search failed for '%s': %s", query, e)
            return []

        results = []
        for item in data.get("results", [])[:limit]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                engine=item.get("engine", ""),
            ))

        logger.info("SearXNG: '%s' returned %d results", query, len(results))
        return results

    def search_many(self, queries: list[str],
                    limit_per_query: int = DEFAULT_LIMIT) -> list[SearchResult]:
        """Execute multiple queries and merge results.

        Deduplicates by URL. Preserves order (first query's results first).

        Args:
            queries: List of search query strings.
            limit_per_query: Max results per query.

        Returns:
            Deduplicated list of SearchResult objects.
        """
        seen_urls: set[str] = set()
        all_results: list[SearchResult] = []

        for query in queries:
            for result in self.search(query, limit=limit_per_query):
                if result.url not in seen_urls:
                    seen_urls.add(result.url)
                    all_results.append(result)

        return all_results
