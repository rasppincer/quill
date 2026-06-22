"""Tests for research_service.py — query generation, orchestration."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from quill.research_service import ResearchService
from quill.search_client import SearchResult


class TestQueryParsing:
    def test_parse_json_array(self):
        svc = ResearchService()
        assert svc._parse_queries('["q1", "q2", "q3"]') == ["q1", "q2", "q3"]

    def test_parse_wrapped_dict(self):
        svc = ResearchService()
        assert svc._parse_queries('{"queries": ["a", "b"]}') == ["a", "b"]

    def test_parse_embedded_array(self):
        svc = ResearchService()
        assert svc._parse_queries('Here are the queries: ["x", "y"] done.') == ["x", "y"]

    def test_parse_empty(self):
        svc = ResearchService()
        assert svc._parse_queries("no json here") == []

    def test_parse_empty_list(self):
        svc = ResearchService()
        assert svc._parse_queries("[]") == []


class TestFallbackQueries:
    def test_extracts_first_line_and_heading(self):
        svc = ResearchService()
        queries = svc._fallback_queries(
            "The history of Rome\nMore details",
            "# Chapter 1\nContent here\n# Chapter 2\nMore",
        )
        assert len(queries) >= 1
        assert "The history of Rome" in queries[0]

    def test_fallback_minimal(self):
        svc = ResearchService()
        queries = svc._fallback_queries("", "")
        assert queries == ["research"]


class TestFormatMarkdown:
    def test_with_results(self):
        results = [
            SearchResult(title="A", url="https://a.com", snippet="snippet a"),
            SearchResult(title="B", url="https://b.com", snippet="snippet b"),
        ]
        md = ResearchService.format_markdown(["query1"], results)
        assert "# Research" in md
        assert "query1" in md
        assert "[A](https://a.com)" in md
        assert "2 sources" in md

    def test_no_results(self):
        md = ResearchService.format_markdown(["q1"], [])
        assert "No results" in md


class TestExecute:
    def test_from_cache(self, tmp_path):
        research_file = tmp_path / "research.md"
        research_file.write_text("# Cached research\nOld results.")

        svc = ResearchService(cache_ttl=3600)
        result = svc.execute("brief", "outline", research_file=research_file)
        assert result.from_cache is True
        assert "Cached research" in result.markdown

    def test_full_execute(self, tmp_path):
        research_file = tmp_path / "research.md"

        mock_search = MagicMock()
        mock_search.search_many.return_value = [
            SearchResult(title="R1", url="https://r1.com", snippet="result 1"),
        ]

        mock_llm = MagicMock()
        mock_llm.chat.return_value = '["test query"]'

        svc = ResearchService(search_client=mock_search, llm_client=mock_llm)
        result = svc.execute("brief text", "outline text", research_file=research_file)

        assert result.from_cache is False
        assert len(result.queries) == 1
        assert len(result.results) == 1
        assert "R1" in result.markdown
        mock_search.search_many.assert_called_once()

    def test_empty_results(self, tmp_path):
        research_file = tmp_path / "research.md"

        mock_search = MagicMock()
        mock_search.search_many.return_value = []

        mock_llm = MagicMock()
        mock_llm.chat.return_value = '["query"]'

        svc = ResearchService(search_client=mock_search, llm_client=mock_llm)
        result = svc.execute("brief", "outline", research_file=research_file)

        assert "No results" in result.markdown
