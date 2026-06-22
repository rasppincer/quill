"""Runner — stage execution engine with critique-decide-loop logic.

For each stage:
1. Load agent config + prompt template
2. Read input files (previous stage output)
3. Fill prompt template with content
4. Call LLM
5. Parse response → decision (advance | loop_back)
6. Execute decision: write output file, update meta, loop or advance

Loop tracking is stored in meta.yaml under `loops`:
    loops:
        review: 2    # has looped twice
        revise: 0
"""

from __future__ import annotations

import logging
from collections import namedtuple
from pathlib import Path

from .agent import AgentDecision, load_agent_config, parse_agent_response
from .llm import LLMClient
from .piece import Piece, load_piece, _FRONTMATTER_RE, _stage_filename
from .run_logger import RunLogger
from .run_manager import RunManager
from .metrics_service import MetricsService
from .prompt_builder import PromptBuilder, render_prompt

# Re-export RunManager so tests can import it from quill.runner
__all__ = ["StageRunner", "RunManager", "CONTENT_STAGES", "StageContext"]

logger = logging.getLogger(__name__)

# Content stages use two LLM calls (generate + evaluate).
CONTENT_STAGES = {"outline", "draft", "revise", "humanize", "polish"}

# Context bundle returned by _prepare_stage().
StageContext = namedtuple("StageContext", [
    "pipeline", "stage_def", "piece", "agent_cfg", "loop_count",
    "input_content", "metrics_context", "prompt",
])


class StageRunner:
    """Executes a pipeline stage using an LLM agent."""

    # Stage-specific input requirements (override default "previous stage" logic).
    # Content stages read from the PREVIOUS CONTENT stage, not the feedback
    # stage before them.
    _STAGE_INPUTS = {
        "outline": ["brief.md"],
        "draft": ["outline.md", "brief.md"],
        "revise": ["draft.md", "review.md"],
        "humanize": ["revise.md"],
        "polish": ["humanize.md", "validate.md"],
    }

    def __init__(self, agent_set: str = "default"):
        self.agent_set = agent_set
        self.run_logger = RunLogger()
        self.metrics_svc = MetricsService()
        self.prompt_builder = PromptBuilder()

    # ------------------------------------------------------------------
    # Thin wrappers — delegate to Piece methods for backward compatibility
    # ------------------------------------------------------------------

    def get_loop_count(self, piece: Piece, stage: str) -> int:
        """Get the current loop count for a stage."""
        return piece.get_loop_count(stage)

    def set_loop_count(self, piece: Piece, stage: str, count: int):
        """Update the loop count for a stage in meta.yaml."""
        piece.set_loop_count(stage, count)

    def _write_output(self, piece: Piece, stage: str, content: str):
        """Write agent output to a stage file."""
        piece.write_output(stage, content)

    def _write_decision(self, piece: Piece, stage: str, decision: AgentDecision):
        """Write evaluation decision to a separate .decision.md file."""
        piece.write_decision(stage, decision.decision, decision.critique)

    def _build_render_context(
        self, piece: Piece, stage: str, input_content: str, metrics_context: str,
        loop_count: int | None = None, extra: dict | None = None,
    ) -> dict:
        """Build the full template variable context for prompt rendering."""
        if loop_count is None:
            loop_count = self.get_loop_count(piece, stage)
        return self.prompt_builder.build_context(
            piece, stage, input_content, metrics_context, loop_count, extra,
        )

    # ------------------------------------------------------------------
    # Stage preparation (shared by compose_prompt and run_stage)
    # ------------------------------------------------------------------

    def _prepare_stage(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
    ) -> StageContext:
        """Load pipeline, piece, agent config, and render the prompt.

        Raises ValueError if the piece or agent config is not found.
        """
        from .pipeline import load_pipeline
        pipeline = load_pipeline("default")

        from .piece import DEFAULT_OUTPUT_DIR
        base = output_dir or DEFAULT_OUTPUT_DIR
        piece_dir = base / piece_id
        if not piece_dir.exists():
            raise ValueError(f"Piece '{piece_id}' not found")

        piece = load_piece(piece_dir)

        agent_cfg = load_agent_config(self.agent_set, stage)
        if not agent_cfg or not agent_cfg.prompt_template:
            raise ValueError(
                f"No agent config for stage '{stage}' in set '{self.agent_set}'"
            )

        loop_count = piece.get_loop_count(stage)
        input_content = self._read_inputs(piece, stage, pipeline, loop_count)
        metrics_context = self.metrics_svc.build_context(
            piece, stage, pipeline,
            PromptBuilder.resolve_input_stages(stage, pipeline, self._STAGE_INPUTS),
        )
        ctx = self.prompt_builder.build_context(
            piece, stage, input_content, metrics_context, loop_count,
        )
        prompt = render_prompt(agent_cfg.prompt_template, ctx)

        return StageContext(
            pipeline=pipeline,
            stage_def=pipeline.get_stage(stage),
            piece=piece,
            agent_cfg=agent_cfg,
            loop_count=loop_count,
            input_content=input_content,
            metrics_context=metrics_context,
            prompt=prompt,
        )

    # ------------------------------------------------------------------
    # Prompt composition (inspect without calling LLM)
    # ------------------------------------------------------------------

    def compose_prompt(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
    ) -> dict:
        """Assemble the full prompt for a stage without calling the LLM.

        Returns a dict with the system prompt, user prompt, and metadata
        so you can inspect exactly what would be sent.
        """
        try:
            sc = self._prepare_stage(piece_id, stage, output_dir)
        except ValueError as e:
            return {"error": str(e)}

        piece, agent_cfg = sc.piece, sc.agent_cfg
        is_content = stage in CONTENT_STAGES

        base = {
            "piece_id": piece_id, "stage": stage, "agent_set": self.agent_set,
            "loop_count": sc.loop_count, "max_loops": agent_cfg.max_loops,
            "is_content_stage": is_content,
            "model": agent_cfg.model, "api_base": agent_cfg.api_base,
            "temperature": agent_cfg.temperature, "max_tokens": agent_cfg.max_tokens,
            "input_content_char_count": len(sc.input_content),
            "template_vars": {
                "TITLE": piece.title, "GENRE": piece.genre, "TYPE": piece.type,
                "LANGUAGE": piece.language, "STAGE": stage, "PIECE_ID": piece_id,
                "METRICS": sc.metrics_context, "loop_count": sc.loop_count,
                "is_looping": sc.loop_count > 0, "max_loops": agent_cfg.max_loops,
            },
        }

        if is_content:
            gen_system = PromptBuilder.system_prompt(stage, piece, "generate")
            eval_template = PromptBuilder.load_evaluate_template(self.agent_set)
            if eval_template:
                eval_ctx = self.prompt_builder.build_context(
                    piece, stage, sc.input_content, "", sc.loop_count,
                    extra={
                        "GENERATED": "<not yet generated — will be filled at runtime>",
                        "INPUT_CONTENT": sc.input_content,
                    },
                )
                eval_prompt = render_prompt(eval_template, eval_ctx)
            else:
                eval_prompt = (
                    f"You are a quality evaluator for a {piece.genre} {piece.type}.\n\n"
                    f"## Stage: {stage}\n\n"
                    f"## Input given to the {stage} agent:\n{sc.input_content}\n\n"
                    f"## Generated {stage} output:\n<not yet generated>\n\n"
                    f"## Task\n"
                    f"Evaluate the generated {stage} output.\n\n"
                    f"Be strict but fair. Only loop_back if there are real, fixable problems."
                )
            eval_system = PromptBuilder.system_prompt(stage, piece, "evaluate")
            base["generate"] = {
                "system": gen_system, "user": sc.prompt,
                "char_count": len(sc.prompt),
            }
            base["evaluate"] = {
                "system": eval_system, "user": eval_prompt,
                "char_count": len(eval_prompt),
                "note": (
                    "The 'Generated output' section above shows '<not yet generated>' "
                    "— the real evaluate prompt includes the actual generated text "
                    "from the generate call."
                ),
            }
        else:
            eval_system = PromptBuilder.system_prompt(stage, piece, "feedback")
            base["single_call"] = {
                "system": eval_system, "user": sc.prompt,
                "char_count": len(sc.prompt),
            }

        return base

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def _emit(self, event_queue, event_type: str, data: dict):
        """Emit an event to the queue if provided."""
        if event_queue is not None:
            event_queue.put({"type": event_type, "data": data})

    # ------------------------------------------------------------------
    # Stage execution
    # ------------------------------------------------------------------

    def run_stage(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
        event_queue=None,
    ) -> AgentDecision:
        """Execute a pipeline stage.

        Args:
            piece_id: The piece ID to process.
            stage: The stage to execute (e.g. "review", "revise").
            output_dir: Override output directory.
            event_queue: Optional queue for SSE event emission.

        Returns:
            AgentDecision with the result.
        """
        try:
            sc = self._prepare_stage(piece_id, stage, output_dir)
        except ValueError as e:
            return AgentDecision(
                decision="error", critique="", output="", error=str(e),
            )

        piece, agent_cfg = sc.piece, sc.agent_cfg
        loop_count = sc.loop_count

        # Check loop limit
        if loop_count >= agent_cfg.max_loops:
            logger.info("Stage '%s' reached max loops (%d), forcing advance",
                        stage, agent_cfg.max_loops)
            return AgentDecision(
                decision="advance",
                critique=f"Max loops ({agent_cfg.max_loops}) reached. Forcing advance.",
                output="", loop_count=loop_count, stage=stage,
            )

        client = LLMClient(
            api_base=agent_cfg.api_base, api_key=agent_cfg.api_key,
            model=agent_cfg.model, temperature=agent_cfg.temperature,
            max_tokens=agent_cfg.max_tokens,
        )

        is_content = stage in CONTENT_STAGES

        self._emit(event_queue, "stage_start", {
            "stage": stage, "is_content_stage": is_content,
            "prompt_chars": len(sc.prompt), "loop_count": loop_count,
        })

        if is_content:
            decision = self._run_content_stage(client, stage, piece, sc, event_queue)
        else:
            decision = self._run_feedback_stage(client, stage, piece, sc, event_queue)

        decision.loop_count = loop_count
        decision.stage = stage

        # Loop guardrail: check for metric degradation across iterations
        if decision.decision == "loop_back" and loop_count > 0:
            guardrail = self.metrics_svc.check_guardrail(piece, stage, loop_count)
            if guardrail:
                decision.decision = "advance"
                decision.critique = (
                    f"[Loop guardrail] Forcing advance after {loop_count} loops. "
                    f"Metrics degraded: {guardrail}. "
                    f"Original critique: {decision.critique}"
                )
                logger.warning("Loop guardrail triggered for '%s': %s", stage, guardrail)
                self._emit(event_queue, "loop_guardrail", {
                    "stage": stage, "loop_count": loop_count,
                    "reason": guardrail, "forced_advance": True,
                })
        elif decision.decision == "loop_back" and loop_count == 0:
            # Save baseline metrics snapshot for future guardrail comparisons
            self.metrics_svc.save_guardrail_snapshot(piece, stage)

        # Execute decision
        if decision.decision == "loop_back":
            piece.set_loop_count(stage, loop_count + 1)
            if not is_content:
                self._write_decision(piece, stage, decision)
            # Content stages already wrote both output and decision above
            logger.info("Stage '%s' loop_back (loop %d/%d)",
                        stage, loop_count + 1, agent_cfg.max_loops)
            self._emit(event_queue, "loop_start", {
                "stage": stage, "loop_count": loop_count + 1,
                "max_loops": agent_cfg.max_loops,
                "critique": decision.critique[:300],
            })
        elif decision.decision == "advance":
            piece.set_loop_count(stage, 0)
            self.metrics_svc.cleanup_guardrail_snapshot(piece, stage)
            if not is_content:
                self._write_output(piece, stage, self._format_feedback(decision.critique))
            if is_content:
                self.metrics_svc.compute(piece, stage)
            if sc.stage_def and sc.stage_def.next:
                piece.advance_to(sc.stage_def.next)
            logger.info("Stage '%s' → advance to '%s'", stage,
                        sc.stage_def.next if sc.stage_def else "?")
        else:
            logger.warning("Stage '%s' returned unknown decision: '%s'",
                           stage, decision.decision)

        self._emit(event_queue, "stage_complete", {
            "stage": stage, "decision": decision.decision,
            "critique": decision.critique[:500],
            "loop_count": loop_count, "error": decision.error,
        })

        return decision

    def _run_content_stage(self, client, stage, piece, sc, event_queue):
        """Two-call approach: generate content, then evaluate."""
        gen_system = PromptBuilder.system_prompt(stage, piece, "generate")
        self.run_logger.log(piece, stage, "generate", gen_system, sc.prompt)
        self._emit(event_queue, "stage_llm_call", {
            "stage": stage, "call": "generate", "prompt_chars": len(sc.prompt),
        })
        try:
            generated = client.chat(gen_system, sc.prompt)
        except ConnectionError as e:
            return AgentDecision(
                decision="error", critique="", output="",
                error=str(e), stage=stage,
            )

        # Persist generated content immediately (survives loop_back)
        self._write_output(piece, stage, generated)

        # Second call: evaluate the generated content
        self._emit(event_queue, "stage_llm_call", {
            "stage": stage, "call": "evaluate", "output_chars": len(generated),
        })
        decision = self._evaluate_output(
            client, stage, piece, generated, sc.pipeline, sc.input_content,
            agent_set=self.agent_set,
        )
        decision.body = generated
        decision.output = generated

        # Persist evaluation result to separate file
        self._write_decision(piece, stage, decision)
        return decision

    def _run_feedback_stage(self, client, stage, piece, sc, event_queue):
        """Single call with JSON decision expected."""
        eval_system = PromptBuilder.system_prompt(stage, piece, "feedback")
        self.run_logger.log(piece, stage, "agent", eval_system, sc.prompt)
        response_format = PromptBuilder.get_structured_output_format()
        self._emit(event_queue, "stage_llm_call", {
            "stage": stage, "call": "agent", "prompt_chars": len(sc.prompt),
        })
        try:
            response = client.chat(eval_system, sc.prompt, response_format=response_format)
        except ConnectionError as e:
            return AgentDecision(
                decision="error", critique="", output="",
                error=str(e), stage=stage,
            )
        decision = parse_agent_response(response)
        decision.output = response
        self.run_logger.log(piece, stage, "agent", eval_system, sc.prompt, {
            "decision": decision.decision, "critique": decision.critique[:500],
        })
        return decision

    # ------------------------------------------------------------------
    # Chain execution
    # ------------------------------------------------------------------

    def run_chain(
        self, piece_id: str, from_stage: str | None = None,
        output_dir: Path | None = None, event_queue=None,
    ) -> list[AgentDecision]:
        """Run a chain of stages from the current stage to done.

        Args:
            piece_id: The piece ID to process.
            from_stage: Start from this stage (default: current stage).
            output_dir: Override output directory.
            event_queue: Optional queue for SSE event emission.

        Returns:
            List of AgentDecision results for each stage run.
        """
        from .pipeline import load_pipeline
        from .piece import DEFAULT_OUTPUT_DIR
        pipeline = load_pipeline("default")
        base = output_dir or DEFAULT_OUTPUT_DIR

        piece_dir = base / piece_id
        if not piece_dir.exists():
            return [AgentDecision(
                decision="error", critique="", output="",
                error=f"Piece '{piece_id}' not found",
            )]

        piece = load_piece(piece_dir)
        current = from_stage or piece.current_stage
        results: list[AgentDecision] = []
        max_stages = 20  # safety limit
        skipped_stages: list[str] = []

        self._emit(event_queue, "chain_start", {
            "piece_id": piece_id, "from_stage": current,
            "agent_set": self.agent_set,
        })

        while current and current != "done" and len(results) < max_stages:
            # Check if agent set has a prompt for this stage
            agent_cfg = load_agent_config(self.agent_set, current)
            if not agent_cfg or not agent_cfg.prompt_template:
                logger.warning(
                    "Skipping stage '%s' — no agent prompt in set '%s'",
                    current, self.agent_set,
                )
                skipped_stages.append(current)
                stage_def = pipeline.get_stage(current)
                if stage_def and stage_def.next:
                    current = stage_def.next
                    continue
                else:
                    break

            result = self.run_stage(piece_id, current, output_dir, event_queue=event_queue)
            results.append(result)

            self._emit(event_queue, "chain_stage_complete", {
                "stage": result.stage, "decision": result.decision,
                "completed": len(results), "error": result.error,
            })

            if result.error:
                break
            if result.decision == "advance":
                # Reload piece to get updated current_stage
                piece = load_piece(piece_dir)
                current = piece.current_stage
            elif result.decision == "loop_back":
                # Stay on same stage, run again (loop limit handled in run_stage)
                pass
            else:
                break

        # If no stages ran and we only skipped, return an error
        if not results and skipped_stages:
            self._emit(event_queue, "chain_complete", {
                "total_stages": 0, "skipped": skipped_stages, "error": True,
            })
            return [AgentDecision(
                decision="error", critique="", output="",
                error=(
                    f"No agent prompts found for any stage starting from "
                    f"'{from_stage or piece.current_stage}' in set '{self.agent_set}'. "
                    f"Skipped: {', '.join(skipped_stages)}"
                ),
            )]

        self._emit(event_queue, "chain_complete", {
            "total_stages": len(results), "skipped": skipped_stages,
            "last_decision": results[-1].decision if results else None,
        })
        return results

    # ------------------------------------------------------------------
    # Input reading
    # ------------------------------------------------------------------

    def _read_inputs(self, piece: Piece, stage: str, pipeline, loop_count: int = 0) -> str:
        """Read input files for a stage.

        Uses stage-specific input mapping when defined,
        otherwise falls back to reading the previous stage's output.
        """
        stage_dir = piece.stage_dir()
        inputs: list[str] = []

        # Stage-specific inputs
        if stage in self._STAGE_INPUTS:
            for input_stage in self._STAGE_INPUTS[stage]:
                input_stage_name = input_stage.replace(".md", "")
                fpath = stage_dir / _stage_filename(input_stage_name)
                if fpath.exists():
                    text = fpath.read_text(encoding="utf-8")
                    m = _FRONTMATTER_RE.match(text)
                    inputs.append(f"=== {fpath.name} ===\n{text[m.end():] if m else text}")
        else:
            # Default: read previous stage's output
            stage_order = pipeline.stage_order
            if stage in stage_order:
                idx = stage_order.index(stage)
                if idx > 0:
                    prev_stage = stage_order[idx - 1]
                    prev_file = stage_dir / _stage_filename(prev_stage)
                    if prev_file.exists():
                        text = prev_file.read_text(encoding="utf-8")
                        m = _FRONTMATTER_RE.match(text)
                        inputs.append(
                            f"=== {_stage_filename(prev_stage)} ===\n"
                            f"{text[m.end():] if m else text}"
                        )

        # If looping, also read the current stage's existing content and decision
        if loop_count > 0:
            current_file = stage_dir / _stage_filename(stage)
            if current_file.exists():
                text = current_file.read_text(encoding="utf-8")
                m = _FRONTMATTER_RE.match(text)
                body = text[m.end():] if m else text
                if body.strip():
                    inputs.append(
                        f"=== {_stage_filename(stage)} (previous attempt) ===\n{body}"
                    )

            decision_file = stage_dir / _stage_filename(stage, ".decision.md")
            if decision_file.exists():
                text = decision_file.read_text(encoding="utf-8")
                inputs.append(
                    f"=== {_stage_filename(stage, '.decision.md')} "
                    f"(evaluation feedback) ===\n{text}"
                )

        return "\n\n".join(inputs) if inputs else "(no input files found)"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_feedback(self, critique: str) -> str:
        """Clean feedback text by stripping JSON code fences and formatting."""
        from .agent import _strip_json_block
        cleaned = _strip_json_block(critique)
        return cleaned if cleaned else critique

    def _evaluate_output(
        self, client: LLMClient, stage: str, piece: Piece,
        generated: str, pipeline, input_content: str,
        agent_set: str = "default",
    ) -> AgentDecision:
        """Second call: evaluate generated content and return a JSON decision.

        Loads the evaluate.prompt.md template from the agent set, fills in
        {{GENERATED}}, {{INPUT_CONTENT}}, and standard variables, then calls
        the LLM with the full (untruncated) content.
        """
        eval_template = PromptBuilder.load_evaluate_template(agent_set)

        if eval_template:
            # Compute metrics on the generated text for the evaluator
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

            eval_ctx = self.prompt_builder.build_context(
                piece, stage, input_content, metrics_str, 0,
                extra={"GENERATED": generated, "INPUT_CONTENT": input_content},
            )
            prompt = render_prompt(eval_template, eval_ctx)
            eval_system = PromptBuilder.system_prompt(stage, piece, "evaluate")
            self.run_logger.log(piece, stage, "evaluate", eval_system, prompt)
        else:
            # Fallback to hardcoded if no template exists
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
        try:
            eval_response = client.chat(eval_system, prompt, response_format=response_format)
        except ConnectionError:
            return AgentDecision(
                decision="advance",
                critique="Evaluation call failed, advancing by default.",
                output="",
            )

        result = parse_agent_response(eval_response)
        self.run_logger.log(piece, stage, "evaluate", eval_system, prompt, {
            "decision": result.decision, "critique": result.critique[:500],
        })
        return result
