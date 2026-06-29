"""Orchestrator — per-stage, per-chapter execution with sliding context window.

For multi-chapter pieces, the orchestrator iterates over chapters
sequentially for each pipeline stage, assembling a sliding context
window that maintains narrative continuity.

Architecture:
- Parent piece reaches stage S
- Orchestrator detects chapters (from structure output)
- For each chapter N (sequentially):
  1. Build sliding context (NarrativeState for distant, full text for close)
  2. Run stage S on chapter N's content
  3. If S == state: parse NarrativeState, merge into cumulative
  4. Store result on child piece
- Concatenate per-chapter results → parent's stage file (view artifact)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .narrative_state import NarrativeState
from .piece import Piece, load_piece, _stage_filename, _FRONTMATTER_RE

logger = logging.getLogger(__name__)


class Orchestrator:
    """Manages per-stage, per-chapter execution for multi-chapter pieces."""

    def __init__(self, agent_set: str = "default"):
        self.agent_set = agent_set

    def _build_sliding_context(
        self,
        chapter_index: int,
        total_chapters: int,
        stage: str,
        chapter_content: str,
        prior_states: list[NarrativeState],
        prior_full_texts: dict[int, str],
        forward_outlines: list[str],
        parent_brief: str,
    ) -> dict:
        """Build the sliding context window for a chapter at a given stage.

        Args:
            chapter_index: 0-based index of the current chapter
            total_chapters: total number of chapters
            stage: pipeline stage being executed
            chapter_content: current chapter's content for this stage
            prior_states: NarrativeState objects for distant chapters (1..N-2)
            prior_full_texts: {chapter_index: full_text} for close neighbor (N-1)
            forward_outlines: outline sketches for chapters N+1..N+2
            parent_brief: the parent piece's brief text

        Returns:
            dict of template variables for prompt rendering
        """
        # Build prior context section
        prior_parts = []

        # Distant chapters: NarrativeState summaries
        if prior_states:
            merged = NarrativeState.merge(prior_states)
            state_yaml = merged.to_yaml()
            prior_parts.append(
                f"=== Narrative State (chapters 1-{chapter_index}) ===\n{state_yaml}"
            )

        # Close neighbor: full text
        for idx in sorted(prior_full_texts.keys()):
            text = prior_full_texts[idx]
            prior_parts.append(
                f"=== Chapter {idx + 1} full text ===\n{text}"
            )

        prior_context = "\n\n".join(prior_parts) if prior_parts else ""

        # Forward outlines
        forward_text = "\n".join(forward_outlines) if forward_outlines else ""

        return {
            "CHAPTER_INDEX": chapter_index + 1,
            "TOTAL_CHAPTERS": total_chapters,
            "CONTENT": chapter_content,
            "PRIOR_CONTEXT": prior_context,
            "FORWARD_OUTLINES": forward_text,
            "PARENT_BRIEF": parent_brief,
        }

    @staticmethod
    def _extract_forward_outlines(
        structure_text: str, current_index: int, lookahead: int = 2,
    ) -> list[str]:
        """Extract outline sketches for chapters after current_index.

        Args:
            structure_text: content of structure.md (segment headers)
            current_index: 0-based index of current chapter
            lookahead: how many forward chapters to include

        Returns:
            list of outline text strings for forward chapters
        """
        if not structure_text:
            return []

        # Parse segment headers
        headers = re.findall(
            r'^##\s+(?:Segment|Part|Chapter)\s*\d+[:\s]*(.*)',
            structure_text,
            re.MULTILINE,
        )

        outlines = []
        for i in range(current_index + 1, min(current_index + 1 + lookahead, len(headers))):
            outlines.append(f"Segment {i + 1}: {headers[i].strip()}")

        return outlines

    @staticmethod
    def _strip_frontmatter(text: str) -> str:
        """Strip YAML frontmatter from text."""
        m = _FRONTMATTER_RE.match(text)
        return text[m.end():] if m else text
