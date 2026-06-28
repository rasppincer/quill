"""StageRunner — focused generate→evaluate loop for a single stage.

Handles the LLM calls for content stages (two-call: generate + evaluate)
and feedback stages (single call). Does NOT handle context assembly,
state transitions, or chain orchestration — those live in runner.py.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .agent import AgentDecision, parse_agent_response
from .llm import LLMClient
from .piece import Piece, _stage_filename
from .logging_config import get_piece_logger
from .prompt_builder import PromptBuilder, render_prompt
from .run_logger import RunLogger
from .timeit import timeit, log_timing
from .token_budget import check_and_truncate, load_context_window

logger = logging.getLogger(__name__)


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
    # Content stage (two-call: generate + evaluate)
    # ------------------------------------------------------------------

    @timeit("LLMCaller.run_content_stage")
    def run_content_stage(
        self, client: LLMClient, stage: str, piece: Piece,
        sc, event_queue=None, trace_id: str | None = None,
    ) -> AgentDecision:
        """Two-call approach: generate content, then evaluate.

        For draft stage with multi-part outlines, generates each part
        separately to overcome token limits, then evaluates the full text.
        """
        gen_system = PromptBuilder.system_prompt(stage, piece, "generate")

        # Check if this is a chaptered draft (outline has ## Part N sections)
        chapters = self._parse_chapters(sc.input_content) if stage == "draft" else []

        # Fallback: try parsing the brief if outline doesn't have chapters
        if not chapters and stage == "draft":
            brief_file = piece.stage_dir() / _stage_filename("brief")
            if brief_file.exists():
                brief_text = brief_file.read_text(encoding="utf-8")
                # Strip frontmatter
                import re as _re
                m = _re.match(r'^---.*?---\s*', brief_text, _re.DOTALL)
                brief_body = brief_text[m.end():] if m else brief_text
                chapters = self._parse_chapters(brief_body)

                # Fallback: parse "- Part N: Title - Description" bullet format
                if not chapters:
                    chapters = self._parse_bullet_chapters(brief_body)

        logger.info("Chapter detection for stage='%s': %d chapters found", stage, len(chapters))
        if chapters and len(chapters) > 1:
            generated = self._generate_chaptered(
                client, gen_system, stage, piece, sc, chapters, event_queue, trace_id,
            )
        else:
            # Standard single-call generation
            self.run_logger.log(piece, stage, "generate", gen_system, sc.prompt, trace_id=trace_id)
            _emit(event_queue, "stage_llm_call", {
                "stage": stage, "call": "generate", "prompt_chars": len(sc.prompt),
            })
            prompt_for_generate, _ = self.apply_token_budget(
                gen_system, sc.prompt, sc.agent_cfg.max_tokens,
                call_label="generate", event_queue=event_queue,
            )
            try:
                generated = client.chat(gen_system, prompt_for_generate, piece_id=piece.id)
            except ConnectionError as e:
                return AgentDecision(
                    decision="error", critique="", output="",
                    error=str(e), stage=stage,
                )

        # Persist generated content immediately (survives loop_back)
        piece.write_output(stage, generated)

        # Second call: evaluate the generated content
        _emit(event_queue, "stage_llm_call", {
            "stage": stage, "call": "evaluate", "output_chars": len(generated),
        })
        decision = self.evaluate_output(
            client, stage, piece, generated, sc.pipeline, sc.input_content,
            agent_set=piece.agent_set or "default",
            max_tokens=sc.agent_cfg.max_tokens,
            trace_id=trace_id,
        )
        decision.body = generated
        decision.output = generated

        # Persist evaluation result to separate file
        piece.write_decision(stage, decision.decision, decision.critique)
        return decision

    # ------------------------------------------------------------------
    # Feedback stage (single call)
    # ------------------------------------------------------------------

    @timeit("LLMCaller.run_feedback_stage")
    def run_feedback_stage(
        self, client: LLMClient, stage: str, piece: Piece,
        sc, event_queue=None, trace_id: str | None = None,
    ) -> AgentDecision:
        """Single call with JSON decision expected."""
        eval_system = PromptBuilder.system_prompt(stage, piece, "feedback")
        self.run_logger.log(piece, stage, "agent", eval_system, sc.prompt, trace_id=trace_id)
        response_format = PromptBuilder.get_structured_output_format()
        _emit(event_queue, "stage_llm_call", {
            "stage": stage, "call": "agent", "prompt_chars": len(sc.prompt),
        })
        prompt_for_feedback, _ = self.apply_token_budget(
            eval_system, sc.prompt, sc.agent_cfg.max_tokens,
            call_label="feedback", event_queue=event_queue,
        )
        try:
            response = client.chat(eval_system, prompt_for_feedback, response_format=response_format, piece_id=piece.id)
        except ConnectionError as e:
            return AgentDecision(
                decision="error", critique="", output="",
                error=str(e), stage=stage,
            )
        decision = parse_agent_response(response)
        decision.output = response
        self.run_logger.log(piece, stage, "agent", eval_system, sc.prompt, {
            "decision": decision.decision, "critique": decision.critique[:500],
        }, trace_id=trace_id)
        return decision

    # ------------------------------------------------------------------
    # Evaluate (second call for content stages)
    # ------------------------------------------------------------------

    @timeit("LLMCaller.evaluate_output")
    def evaluate_output(
        self, client: LLMClient, stage: str, piece: Piece,
        generated: str, pipeline, input_content: str,
        agent_set: str = "default", max_tokens: int = 4096,
        trace_id: str | None = None,
    ) -> AgentDecision:
        """Evaluate generated content and return a JSON decision.

        Loads the evaluate.prompt.md template, fills in {{GENERATED}},
        {{INPUT_CONTENT}}, and standard variables, then calls the LLM.
        """
        eval_template = PromptBuilder.load_evaluate_template(agent_set)

        if eval_template:
            from .metrics import compute_and_save, load_metrics
            stage_file = piece.stage_dir() / _stage_filename(stage)
            metrics_str = ""
            if stage_file.exists():
                try:
                    compute_and_save(stage_file)
                    m = load_metrics(stage_file)
                    if m:
                        metrics_str = "\n".join([
                            f"--- {stage} metrics ---",
                            f"  Flesch Reading Ease: {m.get('flesch_ease', 'n/a')}",
                            f"  Flesch-Kincaid Grade: {m.get('flesch_kincaid', 'n/a')}",
                            f"  Word count: {m.get('word_count', 'n/a')}",
                            f"  Avg sentence length: {m.get('avg_sentence_length', 'n/a')} words",
                            f"  Vocabulary diversity: {round(m.get('type_token_ratio', 0) * 100, 1)}%",
                            f"  Passive voice: {m.get('passive_voice_pct', 'n/a')}%",
                        ])
                except Exception as e:
                    logger.warning("Failed to compute metrics for evaluate prompt: %s", e)

            from .context_assembler import ContextAssembler
            assembler = ContextAssembler(agent_set)
            eval_ctx = assembler.build_render_context(
                piece, stage, input_content, metrics_str, 0,
                extra={"GENERATED": generated, "INPUT_CONTENT": input_content},
            )
            prompt = render_prompt(eval_template, eval_ctx)
            eval_system = PromptBuilder.system_prompt(stage, piece, "evaluate")
            self.run_logger.log(piece, stage, "evaluate", eval_system, prompt, trace_id=trace_id)
        else:
            logger.warning("No evaluate.prompt.md in agent set '%s', using fallback", agent_set)
            prompt = (
                f"You are a quality evaluator for a {piece.genre} {piece.type}.\n\n"
                f"## Stage: {stage}\n\n"
                f"## Input given to the {stage} agent:\n{input_content}\n\n"
                f"## Generated {stage} output:\n{generated}\n\n"
                f"## Task\n"
                f"Evaluate the generated {stage} output. Is it high quality? "
                f"Does it meet the requirements? Respond with ONLY a JSON block:\n\n"
                f'{{"decision": "advance", "critique": "brief feedback"}}\n'
                f'or\n'
                f'{{"decision": "loop_back", "critique": "specific issues to fix"}}\n\n'
                f"Be strict but fair. Only loop_back if there are real, fixable problems."
            )
            eval_system = PromptBuilder.system_prompt(stage, piece, "evaluate")

        response_format = PromptBuilder.get_structured_output_format()
        eval_prompt, _ = self.apply_token_budget(
            eval_system, prompt, max_tokens,
            call_label="evaluate",
        )
        try:
            eval_response = client.chat(eval_system, eval_prompt, response_format=response_format, piece_id=piece.id)
        except ConnectionError as e:
            return AgentDecision(
                decision="error", critique="", output="",
                error=f"Evaluation call failed: {e}", stage=stage,
            )

        result = parse_agent_response(eval_response)
        self.run_logger.log(piece, stage, "evaluate", eval_system, prompt, {
            "decision": result.decision, "critique": result.critique[:500],
        }, trace_id=trace_id)
        return result

    # ------------------------------------------------------------------
    # Chaptered generation (for long-form content)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_chapters(outline_text: str) -> list[dict]:
        """Parse outline into chapters based on ## Part N / ## Chapter N headers.

        Handles formats like:
        - ## Part 1: Title
        - ## I. Part 1: Title
        - ## Chapter 1: Title
        - ## 1. Title

        Returns list of {"heading": str, "body": str} dicts.
        If no chapter headers found, returns empty list.
        """
        import re
        if not outline_text:
            return []

        # Split on headers that contain Part/Chapter/Section with numbers,
        # or numbered headers like ## 1. Title or ## I. Title
        parts = re.split(
            r'(?=^##\s+(?:[IVX]+\.\s*)?(?:Part|Chapter|Section)\s*\d)',
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
        chapter_words = max(1500, int(piece.target_length or 10000) // len(chapters))
        all_chapters = []

        for i, ch in enumerate(chapters):
            ch_num = i + 1
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
                f"## Your Assignment: {ch['heading']}\n\n"
                f"Write this chapter in full prose. Target ~{chapter_words} words.\n\n"
                f"Chapter outline:\n{ch['body']}\n\n"
                f"Requirements:\n"
                f"- Rich, vivid prose with sensory details\n"
                f"- Show don't tell — action, dialogue, internal monologue\n"
                f"- Maintain consistent tone ({piece.tone or 'engaging'})\n"
                f"- Smooth transitions from previous chapters\n"
                f"- Do NOT include chapter headings — just the prose\n"
            )

            self.run_logger.log(piece, stage, f"generate_ch{ch_num}", gen_system, chapter_prompt, trace_id=trace_id)

            try:
                chapter_text = client.chat(gen_system, chapter_prompt, piece_id=piece.id)
                all_chapters.append(f"## {ch['heading']}\n\n{chapter_text}")
                plog.info("Chapter %d done: %d chars", ch_num, len(chapter_text))
            except ConnectionError as e:
                plog.error("Chapter %d failed: %s", ch_num, e)
                all_chapters.append(f"## {ch['heading']}\n\n[Generation failed: {e}]")

        generated = "\n\n---\n\n".join(all_chapters)
        plog.info("All %d chapters generated: %d total chars", len(chapters), len(generated))
        return generated


def _emit(event_queue, event_type: str, data: dict):
    """Emit an event to the queue if provided."""
    if event_queue is not None:
        event_queue.put({"type": event_type, "data": data})
