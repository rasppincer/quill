"""Tests for search_client.py — SearXNG wrapper."""

import json
import pytest
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from quill.search_client import SearchClient, SearchResult


class TestSearchResult:
    def test_to_markdown(self):
        r = SearchResult(title="Test", url="https://example.com", snippet="A snippet.", engine="google")
        md = r.to_markdown()
        assert "[Test](https://example.com)" in md
        assert "A snippet." in md
        assert "google" in md

    def test_to_markdown_no_engine(self):
        r = SearchResult(title="T", url="https://x.com", snippet="s")
        md = r.to_markdown()
        assert "Source:" not in md

    def test_to_markdown_no_snippet(self):
        r = SearchResult(title="T", url="https://x.com", snippet="")
        md = r.to_markdown()
        assert "### [T](https://x.com)" in md


class TestSearchClient:
    def test_search_returns_results(self):
        mock_data = {
            "results": [
                {"title": "A", "url": "https://a.com", "content": "snippet a", "engine": "google"},
                {"title": "B", "url": "https://b.com", "content": "snippet b", "engine": "bing"},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            client = SearchClient()
            results = client.search("test query")

        assert len(results) == 2
        assert results[0].title == "A"
        assert results[1].engine == "bing"

    def test_search_respects_limit(self):
        mock_data = {"results": [{"title": f"R{i}", "url": f"https://{i}.com", "content": ""} for i in range(10)]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            results = SearchClient().search("q", limit=3)
        assert len(results) == 3

    def test_search_returns_empty_on_error(self):
        with patch("urllib.request.urlopen", side_effect=URLError("fail")):
            results = SearchClient().search("q")
        assert results == []

    def test_search_many_deduplicates(self):
        mock_data_1 = {"results": [{"title": "A", "url": "https://a.com", "content": ""}]}
        mock_data_2 = {"results": [{"title": "A2", "url": "https://a.com", "content": ""},  # dup
                                    {"title": "B", "url": "https://b.com", "content": ""}]}

        call_count = 0
        def mock_urlopen(req, timeout=None):
            nonlocal call_count
            resp = MagicMock()
            data = mock_data_1 if call_count == 0 else mock_data_2
            resp.read.return_value = json.dumps(data).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            call_count += 1
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            results = SearchClient().search_many(["q1", "q2"])

        urls = [r.url for r in results]
        assert len(urls) == 2  # a.com deduplicated
        assert "https://a.com" in urls
        assert "https://b.com" in urls
