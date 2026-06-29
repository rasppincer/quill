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

    @staticmethod
    def _get_segment_target(target_length: str) -> int:
        """Get the per-segment word target from piece's target_length."""
        from .structure import calculate_segments, parse_target_length
        parsed = parse_target_length(target_length)
        seg = calculate_segments(parsed)
        return seg["target"]

    @staticmethod
    def _extract_chapters(structure_text: str | None) -> list[dict]:
        """Extract chapter list from structure output.

        Parses ## Segment N: Title, ## Part N: Title, ## Chapter N: Title headers.

        Returns:
            list of {"index": int, "title": str} dicts (0-based index)
        """
        if not structure_text:
            return []

        # Strip frontmatter
        m = _FRONTMATTER_RE.match(structure_text)
        body = structure_text[m.end():] if m else structure_text

        headers = re.findall(
            r'^##\s+(?:Segment|Part|Chapter)\s*\d+[:\s]+(.+)',
            body,
            re.MULTILINE,
        )

        return [
            {"index": i, "title": title.strip()}
            for i, title in enumerate(headers)
        ]

    @staticmethod
    def _has_chapters(piece_dir: Path) -> bool:
        """Check if a piece has multiple chapters (from structure output).

        Returns True if structure.md exists and has 2+ segment headers.
        Single-segment pieces are not considered chaptered.
        """
        from .piece import _stage_filename
        structure_file = piece_dir / _stage_filename("structure")
        if not structure_file.exists():
            return False

        text = structure_file.read_text(encoding="utf-8")
        chapters = Orchestrator._extract_chapters(text)
        return len(chapters) >= 2

    def run_stage(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
    ) -> "AgentDecision | None":
        """Execute a pipeline stage for a multi-chapter piece.

        If the piece has chapters (from structure output), the orchestrator
        iterates over chapters sequentially, building a sliding context
        window for each. Returns None if the piece is not chaptered
        (caller should use the normal StageRunner instead).

        Args:
            piece_id: parent piece ID
            stage: pipeline stage to execute
            output_dir: output directory (defaults to DEFAULT_OUTPUT_DIR)

        Returns:
            AgentDecision if orchestrated, None if not chaptered
        """
        from .piece import DEFAULT_OUTPUT_DIR, _stage_filename, load_piece

        base = output_dir or DEFAULT_OUTPUT_DIR
        piece_dir = base / piece_id

        if not self._has_chapters(piece_dir):
            return None

        # Load parent piece
        parent = load_piece(piece_dir)

        # Get chapter list from structure
        structure_file = piece_dir / _stage_filename("structure")
        structure_text = structure_file.read_text(encoding="utf-8")
        chapters = self._extract_chapters(structure_text)

        logger.info(
            "Orchestrator: running stage '%s' on %d chapters for piece '%s'",
            stage, len(chapters), piece_id,
        )

        # Ensure child pieces exist
        child_ids = self._ensure_children(parent, chapters, base)

        # Read forward outlines from structure
        forward_outlines_all = []
        for ch in chapters:
            forward_outlines_all.append(f"Segment {ch['index'] + 1}: {ch['title']}")

        # Process each chapter sequentially
        narrative_states: list[NarrativeState] = []
        prior_full_texts: dict[int, str] = {}
        results = []

        for i, chapter in enumerate(chapters):
            child_id = child_ids[i]
            child_dir = base / child_id

            # Generate chapter brief if not already present
            brief_file = child_dir / "01_brief.md"
            if not brief_file.exists() or not brief_file.read_text(encoding="utf-8").strip():
                self._generate_chapter_brief(
                    child_dir=child_dir,
                    chapter_index=i,
                    total_chapters=len(chapters),
                    chapter_title=chapter["title"],
                    parent_outline=self._strip_frontmatter(
                        (piece_dir / _stage_filename("outline")).read_text(encoding="utf-8")
                        if (piece_dir / _stage_filename("outline")).exists() else ""
                    ),
                    structure_text=structure_text,
                    prior_states=narrative_states,
                    piece_title=parent.title,
                    genre=parent.genre,
                    type=parent.type,
                    language=parent.language,
                    segment_target=self._get_segment_target(parent.target_length),
                )

            # Build sliding context
            chapter_content = self._read_chapter_content(child_dir, stage)
            forward = self._extract_forward_outlines(structure_text, i, lookahead=2)

            ctx = self._build_sliding_context(
                chapter_index=i,
                total_chapters=len(chapters),
                stage=stage,
                chapter_content=chapter_content,
                prior_states=narrative_states,
                prior_full_texts=prior_full_texts,
                forward_outlines=forward,
                parent_brief=self._read_parent_brief(piece_dir),
            )

            # Run stage on child piece with orchestrator context
            result = self._run_stage_on_child(
                child_id, stage, ctx, base,
            )
            results.append(result)

            # If state stage, parse NarrativeState
            if stage == "state":
                state_file = child_dir / _stage_filename("state")
                if state_file.exists():
                    raw = self._strip_frontmatter(
                        state_file.read_text(encoding="utf-8")
                    )
                    ns = NarrativeState.from_yaml(raw)
                    narrative_states.append(ns)
                    logger.info(
                        "Orchestrator: parsed NarrativeState for chapter %d", i + 1,
                    )

            # Store full text for close neighbor context
            output_file = child_dir / _stage_filename(stage)
            if output_file.exists():
                prior_full_texts[i] = self._strip_frontmatter(
                    output_file.read_text(encoding="utf-8")
                )

        # Update parent's children list
        parent.children = child_ids
        parent.save()

        # Assemble per-chapter outputs into parent's stage file (view artifact)
        self._assemble_outputs(child_ids, stage, base)

        logger.info(
            "Orchestrator: completed stage '%s' on %d chapters", stage, len(chapters),
        )

        # Return a combined decision
        from .agent import AgentDecision
        return AgentDecision(
            decision="advance",
            critique=f"Orchestrated {len(chapters)} chapters for stage '{stage}'.",
            output="",
            stage=stage,
        )

    def _ensure_children(
        self, parent: "Piece", chapters: list[dict], base: Path,
    ) -> list[str]:
        """Create child pieces for each chapter if they don't exist.

        Returns list of child piece IDs.
        """
        from .piece import Piece
        import yaml as _yaml
        from datetime import datetime, timezone

        child_ids = []
        for ch in chapters:
            child_id = f"{parent.id}-chapter-{ch['index'] + 1}"
            child_dir = base / child_id

            if not child_dir.exists():
                child_dir.mkdir(parents=True)

                # Create meta.yaml
                meta = {
                    "id": child_id,
                    "title": f"{parent.title} — Chapter {ch['index'] + 1}: {ch['title']}",
                    "genre": parent.genre,
                    "type": parent.type,
                    "audience": parent.audience,
                    "tone": parent.tone,
                    "language": parent.language,
                    "target_length": parent.target_length,
                    "current_stage": "brief",
                    "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "parent": parent.id,
                    "trigger": "auto",
                }
                (child_dir / "meta.yaml").write_text(
                    _yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )

                # Create stage output directory
                stages_dir = child_dir / "stages"
                stages_dir.mkdir(exist_ok=True)

                logger.info("Orchestrator: created child piece '%s'", child_id)

            child_ids.append(child_id)

        return child_ids

    def _generate_chapter_brief(
        self,
        child_dir: Path,
        chapter_index: int,
        total_chapters: int,
        chapter_title: str,
        parent_outline: str,
        structure_text: str,
        prior_states: list[NarrativeState],
        piece_title: str,
        genre: str,
        type: str,
        language: str,
        segment_target: int,
    ) -> str:
        """Generate a chapter brief using the LLM.

        Args:
            child_dir: child piece directory to write brief.md
            chapter_index: 0-based chapter index
            total_chapters: total number of chapters
            chapter_title: title from structure output
            parent_outline: parent piece's outline text (body, no frontmatter)
            structure_text: full structure output text
            prior_states: NarrativeState from completed chapters
            piece_title: parent piece title
            genre, type, language: piece metadata
            segment_target: target word count per segment

        Returns:
            The generated brief text.
        """
        from .agent import load_model_config
        from .llm import LLMClient
        from .prompt_builder import render_prompt

        # Build prior context
        prior_context = ""
        if prior_states:
            merged = NarrativeState.merge(prior_states)
            prior_context = (
                f"## Context from Previous Chapters\n\n"
                f"```yaml\n{merged.to_yaml()}```"
            )

        # Load prompt template
        from .agent import AGENTS_DIR
        template_path = AGENTS_DIR / self.agent_set / "chapter_brief.prompt.md"
        if not template_path.exists():
            # Fall back to default
            template_path = AGENTS_DIR / "default" / "chapter_brief.prompt.md"

        template = template_path.read_text(encoding="utf-8")

        # Strip frontmatter from structure text for the prompt
        structure_body = self._strip_frontmatter(structure_text)

        # Build context
        ctx = {
            "TITLE": piece_title,
            "GENRE": genre,
            "TYPE": type,
            "LANGUAGE": language,
            "CHAPTER_INDEX": chapter_index + 1,
            "TOTAL_CHAPTERS": total_chapters,
            "CHAPTER_TITLE": chapter_title,
            "SEGMENT_TARGET": segment_target,
            "PARENT_OUTLINE": parent_outline,
            "STRUCTURE": structure_body,
            "PRIOR_CONTEXT": prior_context,
        }

        prompt = render_prompt(template, ctx)

        # Call LLM
        model_cfg = load_model_config()
        client = LLMClient(
            api_base=model_cfg.get("api_base", "https://api.openai.com/v1"),
            api_key=model_cfg.get("api_key", ""),
            model=model_cfg.get("model", "gpt-4o"),
            temperature=0.7,
            max_tokens=2048,
        )

        system = (
            f"You are a chapter brief writer for a {genre} {type} in {language}. "
            f"Write detailed, specific briefs that guide an AI writer. "
            f"Do NOT include JSON or decision blocks — just write the brief."
        )

        logger.info(
            "Orchestrator: generating brief for chapter %d/%d '%s'",
            chapter_index + 1, total_chapters, chapter_title,
        )

        brief_text = client.chat(system, prompt)

        # Write brief to child piece
        brief_file = child_dir / "01_brief.md"
        brief_file.write_text(brief_text, encoding="utf-8")

        logger.info(
            "Orchestrator: wrote brief for chapter %d (%d chars)",
            chapter_index + 1, len(brief_text),
        )

        return brief_text

    def _read_chapter_content(self, child_dir: Path, stage: str) -> str:
        """Read the current content for a chapter at a given stage."""
        from .piece import _stage_filename

        # For draft stage, read the brief
        if stage == "draft":
            brief_file = child_dir / _stage_filename("brief")
            if brief_file.exists():
                return self._strip_frontmatter(
                    brief_file.read_text(encoding="utf-8")
                )

        # For other stages, read the previous stage's output
        from .pipeline import load_pipeline
        pipeline = load_pipeline("default")
        stage_def = pipeline.get_stage(stage)
        if stage_def:
            # Find the stage that feeds into this one
            for s in pipeline.stage_order:
                s_def = pipeline.get_stage(s)
                if s_def and s_def.next == stage:
                    prev_file = child_dir / _stage_filename(s)
                    if prev_file.exists():
                        return self._strip_frontmatter(
                            prev_file.read_text(encoding="utf-8")
                        )

        return ""

    def _read_parent_brief(self, piece_dir: Path) -> str:
        """Read the parent piece's brief text."""
        from .piece import _stage_filename
        brief_file = piece_dir / _stage_filename("brief")
        if brief_file.exists():
            return self._strip_frontmatter(
                brief_file.read_text(encoding="utf-8")
            )
        return ""

    def _run_stage_on_child(
        self, child_id: str, stage: str, context: dict, base: Path,
    ) -> "AgentDecision":
        """Run a pipeline stage on a child piece with orchestrator context.

        Uses the existing StageRunner, passing orchestrator sliding context
        as extra template variables.
        """
        from .runner import StageRunner
        from .agent import AgentDecision

        runner = StageRunner(agent_set=self.agent_set)

        try:
            result = runner.run_stage(
                child_id, stage, output_dir=base,
                extra_context=context,
            )
            return result
        except Exception as e:
            logger.error(
                "Orchestrator: stage '%s' failed on child '%s': %s",
                stage, child_id, e,
            )
            return AgentDecision(
                decision="error",
                critique="",
                output="",
                error=str(e),
                stage=stage,
            )

    @staticmethod
    def _assemble_outputs(
        child_ids: list[str], stage: str, base: Path,
    ) -> None:
        """Concatenate per-chapter stage outputs into the parent's stage file.

        This is a VIEW artifact — the orchestrator does not read it for
        subsequent stages. It exists for display/export purposes.

        Args:
            child_ids: list of child piece IDs
            stage: pipeline stage whose outputs to concatenate
            base: output directory
        """
        from .piece import _stage_filename

        if not child_ids:
            return

        stage_file = _stage_filename(stage)
        parts = []

        for child_id in child_ids:
            child_file = base / child_id / stage_file
            if child_file.exists():
                text = child_file.read_text(encoding="utf-8")
                # Strip frontmatter
                m = _FRONTMATTER_RE.match(text)
                body = text[m.end():] if m else text
                if body.strip():
                    parts.append(body.strip())

        if not parts:
            return

        # Write assembled output to parent (at base level)
        # The parent piece directory is the base itself for child pieces
        # But the parent's own directory is one level up from children
        # For now, write to the parent piece directory
        # (parent_id is derived from child_id pattern: parent-chapter-N)
        parent_id = child_ids[0].rsplit("-chapter-", 1)[0]
        parent_dir = base / parent_id
        if not parent_dir.exists():
            parent_dir.mkdir(parents=True, exist_ok=True)

        assembled = "\n\n---\n\n".join(parts)
        output_file = parent_dir / stage_file
        output_file.write_text(assembled, encoding="utf-8")

        logger.info(
            "Orchestrator: assembled %d chapters into %s", len(parts), output_file,
        )
