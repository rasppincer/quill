"""ResearchService — orchestrates web research for a piece.

Reads the brief/outline, generates search queries via LLM,
executes them through SearchClient, and saves results as research.md.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .llm import LLMClient
from .search_client import SearchClient, SearchResult

logger = logging.getLogger(__name__)

# research.md is considered fresh for this many seconds
CACHE_TTL_SECONDS = 3600  # 1 hour

# Maximum characters before we truncate results
MAX_RESULT_CHARS = 15000


@dataclass
class ResearchResult:
    """Outcome of a research run."""

    queries: list[str]
    results: list[SearchResult]
    markdown: str
    from_cache: bool = False
    used_fallback: bool = False


class ResearchService:
    """Orchestrates research: query generation → search → formatting.

    Args:
        search_client: SearXNG client instance.
        llm_client: LLM client for query generation.
        cache_ttl: Seconds before research.md is considered stale.
    """

    def __init__(
        self,
        search_client: SearchClient | None = None,
        llm_client: LLMClient | None = None,
        cache_ttl: int = CACHE_TTL_SECONDS,
    ):
        self.search_client = search_client or SearchClient()
        self.llm_client = llm_client
        self.cache_ttl = cache_ttl

    def is_fresh(self, research_file: Path) -> bool:
        """Check if research.md exists and is within TTL."""
        if not research_file.exists():
            return False
        age = time.time() - research_file.stat().st_mtime
        return age < self.cache_ttl

    def generate_queries(self, brief_text: str, outline_text: str) -> tuple[list[str], bool]:
        """Use the LLM to generate search queries from brief + outline.

        Returns a tuple of (queries, used_fallback).
        Falls back to keyword extraction if LLM is unavailable.
        """
        if not self.llm_client:
            logger.warning("No LLM client — falling back to keyword extraction")
            return self._fallback_queries(brief_text, outline_text), True

        system = (
            "You are a research assistant. Given a writing brief and outline, "
            "generate 3-5 web search queries that would find useful reference "
            "material for writing this piece.\n\n"
            "Return your answer as a JSON array of strings, wrapped in a "
            "```json code block.\n"
            'Example:\n```json\n["query 1", "query 2", "query 3"]\n```'
        )

        user = f"## Brief\n{brief_text[:2000]}\n\n## Outline\n{outline_text[:2000]}"

        try:
            response = self.llm_client.chat(
                system=system,
                user=user,
                temperature=0.3,
                max_tokens=1024,
            )
            queries = self._parse_queries(response)
            if queries:
                logger.info("LLM generated %d research queries", len(queries))
                return queries, False
        except Exception:
            logger.exception("LLM query generation failed")

        return self._fallback_queries(brief_text, outline_text), True

    def _parse_queries(self, response: str) -> list[str]:
        """Parse LLM response into a list of query strings."""
        # Try direct JSON parse
        try:
            data = json.loads(response)
            if isinstance(data, list):
                return [str(q).strip() for q in data if q]
            if isinstance(data, dict):
                # Maybe wrapped in {"queries": [...]}
                for val in data.values():
                    if isinstance(val, list):
                        return [str(q).strip() for q in val if q]
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from ```json code block
        code_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', response, re.DOTALL)
        if code_match:
            try:
                return [str(q).strip() for q in json.loads(code_match.group(1)) if q]
            except json.JSONDecodeError:
                pass

        # Try extracting JSON array from text
        match = re.search(r'\[.*?\]', response, re.DOTALL)
        if match:
            try:
                return [str(q).strip() for q in json.loads(match.group()) if q]
            except json.JSONDecodeError:
                pass

        return []

    def _fallback_queries(self, brief_text: str, outline_text: str) -> list[str]:
        """Extract keywords mechanically when LLM is unavailable."""
        # Simple: take first line of brief + first section heading from outline
        queries = []
        for line in brief_text.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                queries.append(line[:100])
                break

        for line in outline_text.split("\n"):
            line = line.strip().lstrip("#").strip()
            if line and len(line) > 3:
                queries.append(line[:100])
                break

        return queries[:3] if queries else ["research"]

    def execute(
        self,
        brief_text: str,
        outline_text: str,
        research_file: Path | None = None,
        force: bool = False,
    ) -> ResearchResult:
        """Run the full research pipeline.

        Args:
            brief_text: Content of brief.md.
            outline_text: Content of outline.md.
            research_file: Path to research.md for caching.
            force: If True, bypass cache.

        Returns:
            ResearchResult with queries, results, and markdown.
        """
        # Check cache
        if not force and research_file and self.is_fresh(research_file):
            cached = research_file.read_text(encoding="utf-8")
            logger.info("Research cache hit (%d chars)", len(cached))
            return ResearchResult(
                queries=[],
                results=[],
                markdown=cached,
                from_cache=True,
            )

        # Generate queries
        queries, used_fallback = self.generate_queries(brief_text, outline_text)
        if not queries:
            logger.warning("No research queries generated")
            return ResearchResult(
                queries=[], results=[], markdown="*No search queries generated.*\n",
                used_fallback=used_fallback,
            )

        # Execute searches
        all_results = self.search_client.search_many(queries, limit_per_query=5)
        logger.info("Research: %d queries → %d results", len(queries), len(all_results))

        # Format
        markdown = self.format_markdown(queries, all_results)

        # Truncate if too large
        if len(markdown) > MAX_RESULT_CHARS:
            markdown = markdown[:MAX_RESULT_CHARS] + "\n\n*[Results truncated]*\n"

        return ResearchResult(
            queries=queries,
            results=all_results,
            markdown=markdown,
            used_fallback=used_fallback,
        )

    @staticmethod
    def format_markdown(queries: list[str], results: list[SearchResult]) -> str:
        """Format search results as markdown for research.md."""
        parts = ["# Research\n"]

        parts.append("## Search Queries\n")
        for i, q in enumerate(queries, 1):
            parts.append(f"{i}. {q}")
        parts.append("")

        if not results:
            parts.append("*No results found.*\n")
            return "\n".join(parts)

        parts.append(f"## Results ({len(results)} sources)\n")
        for result in results:
            parts.append(result.to_markdown())
            parts.append("")

        return "\n".join(parts)
