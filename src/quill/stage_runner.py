"""StageRunner — execution engine for a single stage.

Handles the single-call LLM execution returning schema-guaranteed JSON.
Does NOT handle context assembly, state transitions, or chain orchestration
— those live in runner.py.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .agent import AgentDecision, FeedbackStageOutput, ContentStageOutput, load_model_config
from .llm import LLMClient
from .piece import Piece, _stage_filename
from .logging_config import get_piece_logger
from .prompt_builder import PromptBuilder, render_prompt
from .run_logger import RunLogger
from .timeit import timeit, log_timing
from .token_budget import check_and_truncate, load_context_window

logger = logging.getLogger(__name__)


def is_local_api(api_base: str | None) -> bool:
    if not api_base:
        return False
    from urllib.parse import urlparse
    try:
        parsed = urlparse(api_base)
        hostname = parsed.hostname
        if not hostname:
            return False
        hostname = hostname.lower()
        if hostname in ("localhost", "127.0.0.1", "::1"):
            return True
        if hostname.startswith("192.168.") or hostname.startswith("10."):
            return True
        if hostname.startswith("172."):
            parts = hostname.split('.')
            if len(parts) >= 2:
                try:
                    second_octet = int(parts[1])
                    if 16 <= second_octet <= 31:
                        return True
                except ValueError:
                    pass
    except Exception:
        pass
    return False


class LLMCaller:
    """Execute a single stage's LLM calls (generate→evaluate or feedback)."""

    def __init__(self):
        self.run_logger = RunLogger()

    # ------------------------------------------------------------------
    # Token budget
    # ------------------------------------------------------------------

    def apply_token_budget(
        self, system_prompt: str, user_prompt: str, max_tokens: int,
        call_label: str = "", event_queue=None,
    ) -> tuple[str, bool]:
        """Check context window budget and truncate *user_prompt* if needed.

        Returns ``(possibly_truncated_user_prompt, was_truncated)``.
        """
        context_window = load_context_window()
        truncated, was_truncated = check_and_truncate(
            system_prompt, user_prompt, max_tokens, context_window,
        )
        if was_truncated:
            logger.warning(
                "Token budget: truncated %s prompt to fit context window "
                "(context_window=%d, max_tokens=%d)",
                call_label or "LLM", context_window, max_tokens,
            )
            _emit(event_queue, "token_budget_truncated", {
                "call": call_label, "context_window": context_window,
                "max_tokens": max_tokens,
            })
        return truncated, was_truncated

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Single-call Stage Execution
    # ------------------------------------------------------------------

    @timeit("LLMCaller.run_stage")
    def run_stage(
        self, client: LLMClient, stage: str, piece: Piece,
        sc, event_queue=None, trace_id: str | None = None,
    ) -> AgentDecision:
        """Single-call execution engine returning schema-guaranteed JSON."""
        is_content = sc.pipeline.is_content_stage(stage)
        cfg = load_model_config()
        use_structured = cfg.get("structured_output", False)
        if use_structured and is_local_api(client.api_base):
            use_structured = False

        if is_content:
            gen_system = PromptBuilder.system_prompt(stage, piece, "generate")
            chapters = self._parse_chapters(sc.input_content) if stage == "draft" else []

            # Chapter fallback
            if not chapters and stage == "draft":
                structure_file = piece.stage_dir() / _stage_filename("structure")
                if structure_file.exists():
                    structure_text = structure_file.read_text(encoding="utf-8")
                    import re as _re
                    m = _re.match(r'^---.*?---\s*', structure_text, _re.DOTALL)
                    structure_body = structure_text[m.end():] if m else structure_text
                    chapters = self._parse_chapters(structure_body)

                if not chapters:
                    brief_file = piece.stage_dir() / _stage_filename("brief")
                    if brief_file.exists():
                        brief_text = brief_file.read_text(encoding="utf-8")
                        import re as _re
                        m = _re.match(r'^---.*?---\s*', brief_text, _re.DOTALL)
                        brief_body = brief_text[m.end():] if m else brief_text
                        chapters = self._parse_chapters(brief_body)
                        if not chapters:
                            chapters = self._parse_bullet_chapters(brief_body)

            if chapters and len(chapters) > 1:
                generated_content = self._generate_chaptered(
                    client, gen_system, stage, piece, sc, chapters, event_queue, trace_id,
                )
                import json
                raw_response = json.dumps({"content": generated_content})
            else:
                self.run_logger.log(piece, stage, "generate", gen_system, sc.prompt, trace_id=trace_id)
                _emit(event_queue, "stage_llm_call", {
                    "stage": stage, "call": "generate", "prompt_chars": len(sc.prompt),
                })
                prompt_for_generate, _ = self.apply_token_budget(
                    gen_system, sc.prompt, sc.agent_cfg.max_tokens,
                    call_label="generate", event_queue=event_queue,
                )
                try:
                    raw_response = client.chat(
                        gen_system,
                        prompt_for_generate,
                        response_format=ContentStageOutput if use_structured else None,
                        piece_id=piece.id,
                        stage=stage,
                        call_type="generate",
                        trace_id=trace_id,
                    )
                except ConnectionError as e:
                    return AgentDecision(
                        decision="error", critique="", output="",
                        error=str(e), stage=stage,
                    )

                try:
                    parsed = ContentStageOutput.model_validate_json(raw_response)
                    generated_content = parsed.content
                except Exception as e:
                    logger.error("Failed to parse schema-guaranteed content JSON: %s", e)
                    generated_content = raw_response

            piece.write_json(stage, raw_response)
            piece.write_output(stage, generated_content)

            return AgentDecision(
                decision="advance",
                critique="",
                output=raw_response,
                body=generated_content,
            )

        else:
            # Feedback/Critique stage
            eval_system = PromptBuilder.system_prompt(stage, piece, "feedback")
            self.run_logger.log(piece, stage, "agent", eval_system, sc.prompt, trace_id=trace_id)
            _emit(event_queue, "stage_llm_call", {
                "stage": stage, "call": "agent", "prompt_chars": len(sc.prompt),
            })
            prompt_for_feedback, _ = self.apply_token_budget(
                eval_system, sc.prompt, sc.agent_cfg.max_tokens,
                call_label="feedback", event_queue=event_queue,
            )
            try:
                response = client.chat(
                    eval_system,
                    prompt_for_feedback,
                    response_format=FeedbackStageOutput if use_structured else None,
                    piece_id=piece.id,
                    stage=stage,
                    call_type="agent",
                    trace_id=trace_id,
                )
            except ConnectionError as e:
                return AgentDecision(
                    decision="error", critique="", output="",
                    error=str(e), stage=stage,
                )

            try:
                parsed = FeedbackStageOutput.model_validate_json(response)
                critique = parsed.critique
            except Exception as e:
                logger.error("Failed to parse schema-guaranteed feedback JSON: %s", e)
                critique = response

            piece.write_json(stage, response)
            piece.write_output(stage, critique)

            decision = AgentDecision(
                decision="advance",
                critique=critique,
                output=response,
                body=critique,
            )
            self.run_logger.log(piece, stage, "agent", eval_system, sc.prompt, {
                "decision": decision.decision, "critique": (decision.critique or "")[:500],
            }, trace_id=trace_id)
            return decision

    # ------------------------------------------------------------------
    # Chaptered generation (for long-form content)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_chapters(outline_text: str) -> list[dict]:
        """Parse outline into chapters based on ## Part N / ## Chapter N / ## Segment N headers.

        Handles formats like:
        - ## Part 1: Title
        - ## I. Part 1: Title
        - ## Chapter 1: Title
        - ## Segment 1: Title
        - ## 1. Title

        Returns list of {"heading": str, "body": str} dicts.
        If no chapter headers found, returns empty list.
        """
        import re
        if not outline_text:
            return []

        # Split on headers that contain Part/Chapter/Section/Segment with numbers,
        # or numbered headers like ## 1. Title or ## I. Title
        parts = re.split(
            r'(?=^##\s+(?:[IVX]+\.\s*)?(?:Part|Chapter|Section|Segment)\s*\d)',
            outline_text, flags=re.MULTILINE,
        )
        # Fallback: try splitting on ## I. / ## II. / ## III. etc.
        if len(parts) <= 1:
            parts = re.split(
                r'(?=^##\s+[IVX]+\.)',
                outline_text, flags=re.MULTILINE,
            )

        # NOTE: Do NOT fall back to ## N. — too many false positives from
        # outline meta-headers like "## 1. Narrative Arc", "## 2. Character Arcs"

        chapters = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Extract heading from first line
            lines = part.split('\n', 1)
            heading = lines[0].strip().lstrip('#').strip()
            body = lines[1].strip() if len(lines) > 1 else ""
            # Skip separator-style headings (e.g. "=== 02_outline.md ===")
            if heading.startswith('===') or heading.startswith('---'):
                continue
            if body:
                chapters.append({"heading": heading, "body": body})

        return chapters

    @staticmethod
    def _parse_bullet_chapters(text: str) -> list[dict]:
        """Parse bullet-point chapter format: - Part N: Title - Description.

        Also handles:
        - Chapter N: Title
        - Part N — Title
        """
        import re
        if not text:
            return []

        # Find lines matching "- Part N: ..." or "- Chapter N: ..."
        pattern = re.compile(
            r'^[-*]\s+(?:Part|Chapter)\s+(\d+)\s*[:\-—]\s*(.+)',
            re.MULTILINE,
        )
        matches = list(pattern.finditer(text))
        if len(matches) < 2:
            return []

        chapters = []
        for i, m in enumerate(matches):
            heading = f"Part {m.group(1)}: {m.group(2).strip()}"
            # Get body: text between this match and the next (or end)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            chapters.append({"heading": heading, "body": body})

        return chapters

    def _generate_chaptered(
        self, client: LLMClient, gen_system: str, stage: str,
        piece: Piece, sc, chapters: list[dict],
        event_queue=None, trace_id: str | None = None,
    ) -> str:
        """Generate each chapter separately, then concatenate.

        Each chapter gets its own LLM call with the full outline as context
        but focused instructions for that specific part.
        """
        plog = get_piece_logger("stage_runner", piece.id)
        full_outline = sc.input_content
        from .structure import parse_target_length
        target = parse_target_length(piece.target_length) or 10000
        chapter_words = max(2000, int(target * 1.2) // len(chapters))
        cfg = load_model_config()
        use_structured = cfg.get("structured_output", False)
        if use_structured and is_local_api(client.api_base):
            use_structured = False
        all_chapters = []

        # Extract character sheet from brief for persistent context
        character_sheet = self._extract_character_sheet(piece)

        for i, ch in enumerate(chapters):
            ch_num = i + 1
            is_last = (i == len(chapters) - 1)
            plog.info("Generating chapter %d/%d: %s", ch_num, len(chapters), ch["heading"])
            _emit(event_queue, "stage_llm_call", {
                "stage": stage, "call": f"generate_chapter_{ch_num}",
                "prompt_chars": len(ch["body"]),
            })

            # Build chapter-specific prompt
            chapter_prompt = (
                f"You are writing Chapter {ch_num} of {len(chapters)} for a "
                f"{piece.genre or 'story'} titled \"{piece.title}\".\n\n"
                f"## Full Outline\n{full_outline}\n\n"
            )

            if character_sheet:
                chapter_prompt += f"## Character Reference\n{character_sheet}\n\n"

            chapter_prompt += (
                f"## Your Assignment: {ch['heading']}\n\n"
                f"Write this chapter in full prose. Target ~{chapter_words} words.\n\n"
            )

            if ch["body"]:
                chapter_prompt += f"Chapter outline:\n{ch['body']}\n\n"

            chapter_prompt += (
                f"Requirements:\n"
                f"- Rich, vivid prose with sensory details\n"
                f"- Show don't tell — action, dialogue, internal monologue\n"
                f"- Maintain consistent tone ({piece.tone or 'engaging'})\n"
            )

            if ch_num == 1:
                chapter_prompt += (
                    f"- Start with action, dialogue, or a striking image — "
                    f"NOT weather description or atmospheric preamble\n"
                )

            if is_last:
                chapter_prompt += (
                    f"- This is the FINAL chapter — give each character a "
                    f"satisfying conclusion\n"
                    f"- Expand the ending — don't rush the resolution\n"
                )

            if ch_num > 1:
                chapter_prompt += f"- Continue naturally from the previous chapter\n"

            chapter_prompt += f"- Do NOT include chapter headings — just the prose\n"

            self.run_logger.log(piece, stage, f"generate_ch{ch_num}", gen_system, chapter_prompt, trace_id=trace_id)

            try:
                chapter_text = client.chat(
                    gen_system,
                    chapter_prompt,
                    response_format=ContentStageOutput if use_structured else None,
                    piece_id=piece.id,
                    stage=stage,
                    call_type=f"generate_ch{ch_num}",
                    trace_id=trace_id,
                )
                try:
                    parsed_ch = ContentStageOutput.model_validate_json(chapter_text)
                    prose = parsed_ch.content
                except Exception as e:
                    logger.error("Failed to parse chapter content JSON: %s", e)
                    prose = chapter_text
                all_chapters.append(f"## {ch['heading']}\n\n{prose}")
                plog.info("Chapter %d done: %d chars", ch_num, len(prose))
            except ConnectionError as e:
                plog.error("Chapter %d failed: %s", ch_num, e)
                all_chapters.append(f"## {ch['heading']}\n\n[Generation failed: {e}]")

        generated = "\n\n---\n\n".join(all_chapters)
        plog.info("All %d chapters generated: %d total chars", len(chapters), len(generated))
        return generated

    @staticmethod
    def _extract_character_sheet(piece: Piece) -> str:
        """Extract character names and descriptions from the brief.

        Returns a formatted string for persistent context across chapters.
        """
        import re
        brief_file = piece.stage_dir() / _stage_filename("brief")
        if not brief_file.exists():
            return ""

        text = brief_file.read_text(encoding="utf-8")
        # Strip frontmatter
        m = re.match(r'^---.*?---\s*', text, re.DOTALL)
        body = text[m.end():] if m else text

        # Find the Characters section
        char_match = re.search(
            r'## Characters?\s*\n(.*?)(?=\n## |\Z)',
            body, re.DOTALL | re.IGNORECASE,
        )
        if char_match:
            return char_match.group(1).strip()
        return ""


def _emit(event_queue, event_type: str, data: dict):
    """Emit an event to the queue if provided."""
    if event_queue is not None:
        event_queue.put({"type": event_type, "data": data})
