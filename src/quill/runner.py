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
import time
import uuid
from collections import namedtuple
from pathlib import Path

from .agent import AgentDecision, load_agent_config, parse_agent_response
from .llm import LLMClient
from .piece import Piece, load_piece, _FRONTMATTER_RE, _stage_filename
from .run_logger import RunLogger
from .run_manager import RunManager
from .metrics_service import MetricsService
from .prompt_builder import PromptBuilder, render_prompt
from .token_budget import check_and_truncate, load_context_window

# Re-export RunManager so tests can import it from quill.runner
__all__ = ["StageRunner", "RunManager", "StageContext"]

logger = logging.getLogger(__name__)

# Context bundle returned by _prepare_stage().
StageContext = namedtuple("StageContext", [
    "pipeline", "stage_def", "piece", "agent_cfg", "loop_count",
    "input_content", "metrics_context", "prompt",
])


class StageRunner:
    """Executes a pipeline stage using an LLM agent."""

    def __init__(self, agent_set: str = "default"):
        self.agent_set = agent_set
        self.run_logger = RunLogger()
        self.metrics_svc = MetricsService()
        self.prompt_builder = PromptBuilder()

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _load_chain_retry(self) -> int:
        """Load chain_retry setting from the agent set's config.yaml.

        Returns the number of retries allowed for transient LLM failures.
        Defaults to 0 (no retries) if not configured.
        """
        from .agent import AGENTS_DIR
        import yaml
        config_file = AGENTS_DIR / self.agent_set / "config.yaml"
        if not config_file.exists():
            return 0
        cfg = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        return cfg.get("chain_retry", 0)

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
            PromptBuilder.resolve_input_stages(stage, pipeline),
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
        is_content = sc.pipeline.is_content_stage(stage)

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
    def _apply_token_budget(
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
            self._emit(event_queue, "token_budget_truncated", {
                "call": call_label, "context_window": context_window,
                "max_tokens": max_tokens,
            })
        return truncated, was_truncated

    # ------------------------------------------------------------------
    # Stage execution
    # Stage execution
    # ------------------------------------------------------------------

    def run_stage(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
        event_queue=None, trace_id: str | None = None,
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
        # Research is a special stage — no agent prompt, uses ResearchService
        if stage == "research":
            return self._run_research(piece_id, stage, output_dir, event_queue)

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
            # Actually advance the piece to prevent chain loop
            piece.advance_to(sc.stage_def.next) if sc.stage_def and sc.stage_def.next else None
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

        is_content = sc.pipeline.is_content_stage(stage)

        self._emit(event_queue, "stage_start", {
            "stage": stage, "is_content_stage": is_content,
            "prompt_chars": len(sc.prompt), "loop_count": loop_count,
        })

        if is_content:
            decision = self._run_content_stage(client, stage, piece, sc, event_queue, trace_id=trace_id)
        else:
            decision = self._run_feedback_stage(client, stage, piece, sc, event_queue, trace_id=trace_id)

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

    def _run_content_stage(self, client, stage, piece, sc, event_queue, trace_id=None):
        """Two-call approach: generate content, then evaluate."""
        gen_system = PromptBuilder.system_prompt(stage, piece, "generate")
        self.run_logger.log(piece, stage, "generate", gen_system, sc.prompt, trace_id=trace_id)
        self._emit(event_queue, "stage_llm_call", {
            "stage": stage, "call": "generate", "prompt_chars": len(sc.prompt),
        })
        # Token budget check for generate call (use agent_cfg.max_tokens, not
        # client.max_tokens, because tests mock the client)
        prompt_for_generate, _ = self._apply_token_budget(
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
        self._write_output(piece, stage, generated)

        # Second call: evaluate the generated content
        self._emit(event_queue, "stage_llm_call", {
            "stage": stage, "call": "evaluate", "output_chars": len(generated),
        })
        decision = self._evaluate_output(
            client, stage, piece, generated, sc.pipeline, sc.input_content,
            agent_set=self.agent_set, max_tokens=sc.agent_cfg.max_tokens,
            trace_id=trace_id,
        )
        decision.body = generated
        decision.output = generated

        # Persist evaluation result to separate file
        self._write_decision(piece, stage, decision)
        return decision

    def _run_feedback_stage(self, client, stage, piece, sc, event_queue, trace_id=None):
        """Single call with JSON decision expected."""
        eval_system = PromptBuilder.system_prompt(stage, piece, "feedback")
        self.run_logger.log(piece, stage, "agent", eval_system, sc.prompt, trace_id=trace_id)
        response_format = PromptBuilder.get_structured_output_format()
        self._emit(event_queue, "stage_llm_call", {
            "stage": stage, "call": "agent", "prompt_chars": len(sc.prompt),
        })
        # Token budget check for feedback call
        prompt_for_feedback, _ = self._apply_token_budget(
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
    # Research stage
    # ------------------------------------------------------------------

    def _run_research(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
        event_queue=None,
    ) -> AgentDecision:
        """Execute the research stage: generate queries, search, save results."""
        from .piece import DEFAULT_OUTPUT_DIR, load_piece
        from .pipeline import load_pipeline
        from .research_service import ResearchService

        base = output_dir or DEFAULT_OUTPUT_DIR
        piece_dir = base / piece_id
        if not piece_dir.exists():
            return AgentDecision(
                decision="error", critique="", output="",
                error=f"Piece '{piece_id}' not found",
            )

        piece = load_piece(piece_dir)
        pipeline = load_pipeline("default")

        self._emit(event_queue, "stage_start", {
            "stage": stage, "is_content_stage": False, "is_research": True,
        })

        # Read inputs (brief + outline)
        input_content = self._read_inputs(piece, stage, pipeline)
        stage_dir = piece.stage_dir()
        research_file = stage_dir / "research.md"

        # Check cache
        svc = ResearchService()
        if svc.is_fresh(research_file):
            self._emit(event_queue, "research_cached", {
                "stage": stage, "file": str(research_file),
            })
            return AgentDecision(
                decision="advance", critique="Research cache hit.",
                output="", stage=stage,
            )

        # Split inputs into brief and outline
        brief_text, outline_text = "", ""
        for block in input_content.split("=== "):
            if block.startswith(_stage_filename("brief")):
                brief_text = block.split("\n", 1)[-1] if "\n" in block else ""
            elif block.startswith(_stage_filename("outline")):
                outline_text = block.split("\n", 1)[-1] if "\n" in block else ""

        # Load LLM client for query generation
        from .agent import load_model_config
        from .llm import LLMClient
        model_cfg = load_model_config()
        llm_client = LLMClient(
            api_base=model_cfg.get("api_base", "https://api.openai.com/v1"),
            api_key=model_cfg.get("api_key", ""),
            model=model_cfg.get("model", "gpt-4o"),
            temperature=0.3,
            max_tokens=200,
        )

        svc = ResearchService(llm_client=llm_client)
        result = svc.execute(
            brief_text=brief_text,
            outline_text=outline_text,
            research_file=research_file,
        )

        if result.from_cache:
            critique = "Research cache hit."
        elif result.results:
            research_file.write_text(result.markdown, encoding="utf-8")
            critique = f"Found {len(result.results)} sources from {len(result.queries)} queries."
            logger.info("Research complete: %s", critique)
        else:
            research_file.write_text(result.markdown, encoding="utf-8")
            critique = "No research results found."
            logger.warning("Research returned no results")

        self._emit(event_queue, "research_complete", {
            "stage": stage, "queries": len(result.queries),
            "results": len(result.results), "cached": result.from_cache,
        })

        # Advance to next stage
        stage_def = pipeline.get_stage(stage)
        if stage_def and stage_def.next:
            piece.advance_to(stage_def.next)

        return AgentDecision(
            decision="advance", critique=critique,
            output=result.markdown[:500], stage=stage,
        )

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
        trace_id = str(uuid.uuid4())

        self._emit(event_queue, "chain_start", {
            "piece_id": piece_id, "from_stage": current,
            "agent_set": self.agent_set,
        })

        while current and current != "done" and len(results) < max_stages:
            # Load retry config once per stage (refreshed each iteration
            # in case config changes, but practically loaded once)
            chain_retry = self._load_chain_retry()
            # Research stage runs without an agent prompt
            if current == "research":
                from .agent import load_research_config
                research_cfg = load_research_config(self.agent_set)
                if not research_cfg.get("enabled"):
                    logger.info("Research disabled for agent set '%s', skipping", self.agent_set)
                    skipped_stages.append(current)
                    stage_def = pipeline.get_stage(current)
                    current = stage_def.next if stage_def else None
                    continue
                result = self._run_research(piece_id, current, output_dir, event_queue=event_queue)
                results.append(result)
                if result.decision == "advance":
                    piece = load_piece(piece_dir)
                    current = piece.current_stage
                continue

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

            result = None
            for attempt in range(chain_retry + 1):
                try:
                    result = self.run_stage(piece_id, current, output_dir, event_queue=event_queue, trace_id=trace_id)
                except (ConnectionError, TimeoutError, OSError) as exc:
                    # Transient LLM failure — retry with exponential backoff
                    if attempt < chain_retry:
                        backoff = 2 ** attempt  # 1s, 2s, 4s
                        logger.warning(
                            "Stage '%s' transient failure (attempt %d/%d), "
                            "retrying in %ds: %s",
                            current, attempt + 1, chain_retry + 1, backoff, exc,
                        )
                        self._emit(event_queue, "chain_retry", {
                            "stage": current, "attempt": attempt + 1,
                            "max_attempts": chain_retry + 1,
                            "backoff_seconds": backoff,
                            "error": str(exc),
                        })
                        time.sleep(backoff)
                        continue
                    else:
                        result = AgentDecision(
                            decision="error", critique="", output="",
                            error=f"Transient LLM failure after {chain_retry + 1} attempts: {exc}",
                        )
                except ValueError as exc:
                    # Permanent failure (missing piece, missing config) — break immediately
                    result = AgentDecision(
                        decision="error", critique="", output="",
                        error=str(exc),
                    )
                break

            if result is None:
                # Should not happen, but safety fallback
                result = AgentDecision(
                    decision="error", critique="", output="",
                    error="Unexpected empty result",
                )

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
        stage_inputs = pipeline.stage_inputs if pipeline else {}
        if stage in stage_inputs:
            for input_stage in stage_inputs[stage]:
                input_stage_name = input_stage.replace(".md", "")
                fpath = stage_dir / _stage_filename(input_stage_name)
                if fpath.exists():
                    text = fpath.read_text(encoding="utf-8")
                    m = _FRONTMATTER_RE.match(text)
                    inputs.append(f"=== {fpath.name} ===\n{text[m.end():] if m else text}")
        else:
            # Default: read previous stage's output
            stage_order = pipeline.stage_order if pipeline else []
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
        agent_set: str = "default", max_tokens: int = 4096,
        trace_id: str | None = None,
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
            self.run_logger.log(piece, stage, "evaluate", eval_system, prompt, trace_id=trace_id)
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
        # Token budget check for evaluate call
        eval_prompt, _ = self._apply_token_budget(
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
