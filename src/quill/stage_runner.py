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
from .prompt_builder import PromptBuilder, render_prompt
from .run_logger import RunLogger
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

    def run_content_stage(
        self, client: LLMClient, stage: str, piece: Piece,
        sc, event_queue=None, trace_id: str | None = None,
    ) -> AgentDecision:
        """Two-call approach: generate content, then evaluate."""
        gen_system = PromptBuilder.system_prompt(stage, piece, "generate")
        self.run_logger.log(piece, stage, "generate", gen_system, sc.prompt, trace_id=trace_id)
        _emit(event_queue, "stage_llm_call", {
            "stage": stage, "call": "generate", "prompt_chars": len(sc.prompt),
        })
        prompt_for_generate, _ = self.apply_token_budget(
            gen_system, sc.prompt, sc.agent_cfg.max_tokens,
            call_label="generate", event_queue=event_queue,
        )
        try:
            generated = client.chat(gen_system, prompt_for_generate)
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
            response = client.chat(eval_system, prompt_for_feedback, response_format=response_format)
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
            eval_response = client.chat(eval_system, eval_prompt, response_format=response_format)
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


def _emit(event_queue, event_type: str, data: dict):
    """Emit an event to the queue if provided."""
    if event_queue is not None:
        event_queue.put({"type": event_type, "data": data})
