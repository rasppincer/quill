"""Runner — stage execution engine with critique-decide-loop logic.

Wires together ContextAssembler, LLMCaller, and ChainOrchestrator.
Owns: stage routing, loop guardrails, decision handling, state transitions,
and the research stage (special case).

Context assembly → ContextAssembler
LLM calls (generate/evaluate/feedback) → LLMCaller (stage_runner.py)
Chain orchestration → ChainOrchestrator (chain_orchestrator.py)
"""

from __future__ import annotations

import logging
import time
from collections import namedtuple
from pathlib import Path

from .agent import AgentDecision, load_agent_config
from .context_assembler import ContextAssembler
from .chain_orchestrator import ChainOrchestrator
from .llm import LLMClient
from .piece import Piece, load_piece, _stage_filename
from .metrics_service import MetricsService
from .prompt_builder import PromptBuilder
from .stage_runner import LLMCaller, _emit

__all__ = ["StageRunner", "RunManager", "StageContext"]

logger = logging.getLogger(__name__)

# Context bundle returned by ContextAssembler.prepare_stage().
StageContext = namedtuple("StageContext", [
    "pipeline", "stage_def", "piece", "agent_cfg", "loop_count",
    "input_content", "metrics_context", "prompt",
])


class StageRunner:
    """Facade: routes stage execution, handles decisions, manages state."""

    def __init__(self, agent_set: str = "default"):
        self._agent_set = agent_set
        self.assembler = ContextAssembler(agent_set)
        self.llm = LLMCaller()
        self.chain = ChainOrchestrator(agent_set)
        self.metrics_svc = MetricsService()

    @property
    def agent_set(self) -> str:
        return self._agent_set

    @agent_set.setter
    def agent_set(self, value: str):
        self._agent_set = value
        self.assembler.agent_set = value
        self.chain.agent_set = value

    @property
    def run_logger(self):
        """Backward compat: delegate to LLMCaller's run_logger."""
        return self.llm.run_logger

    # ------------------------------------------------------------------
    # Thin wrappers (backward compatibility for tests/blueprints)
    # ------------------------------------------------------------------

    def get_loop_count(self, piece: Piece, stage: str) -> int:
        return piece.get_loop_count(stage)

    def set_loop_count(self, piece: Piece, stage: str, count: int):
        piece.set_loop_count(stage, count)

    def _write_output(self, piece: Piece, stage: str, content: str):
        piece.write_output(stage, content)

    def _write_decision(self, piece: Piece, stage: str, decision: AgentDecision):
        piece.write_decision(stage, decision.decision, decision.critique)

    def compose_prompt(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
    ) -> dict:
        """Assemble the full prompt for a stage without calling the LLM."""
        return self.assembler.compose_prompt(piece_id, stage, output_dir)

    # ------------------------------------------------------------------
    # Stage execution
    # ------------------------------------------------------------------

    def run_stage(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
        event_queue=None, trace_id: str | None = None, force_advance: bool = False,
    ) -> AgentDecision:
        """Execute a pipeline stage.

        Assembles context, checks limits, delegates to LLMCaller for
        LLM calls, then handles the decision (loop_back/advance) and
        state transitions.
        """
        # Research is a special stage
        if stage == "research":
            return self._run_research(piece_id, stage, output_dir, event_queue, force_advance=force_advance)

        # Assemble context
        try:
            sc = self.assembler.prepare_stage(piece_id, stage, output_dir)
        except ValueError as e:
            return AgentDecision(
                decision="error", critique="", output="", error=str(e),
            )

        piece, agent_cfg = sc.piece, sc.agent_cfg
        loop_count = sc.loop_count

        # Set stage state to generating
        piece.set_stage_state(stage, "generating")

        # Check loop limit
        if loop_count >= agent_cfg.max_loops:
            logger.info("Stage '%s' reached max loops (%d), forcing advance",
                        stage, agent_cfg.max_loops)
            piece.advance_to(sc.stage_def.next) if sc.stage_def and sc.stage_def.next else None
            return AgentDecision(
                decision="advance",
                critique=f"Max loops ({agent_cfg.max_loops}) reached. Forcing advance.",
                output="", loop_count=loop_count, stage=stage,
            )

        # Create LLM client
        client = LLMClient(
            api_base=agent_cfg.api_base, api_key=agent_cfg.api_key,
            model=agent_cfg.model, temperature=agent_cfg.temperature,
            max_tokens=agent_cfg.max_tokens,
        )

        is_content = sc.pipeline.is_content_stage(stage)

        _emit(event_queue, "stage_start", {
            "stage": stage, "is_content_stage": is_content,
            "prompt_chars": len(sc.prompt), "loop_count": loop_count,
        })

        # Delegate to LLMCaller for LLM calls
        if is_content:
            decision = self.llm.run_content_stage(client, stage, piece, sc, event_queue, trace_id=trace_id)
        else:
            decision = self.llm.run_feedback_stage(client, stage, piece, sc, event_queue, trace_id=trace_id)

        decision.loop_count = loop_count
        decision.stage = stage

        # Loop guardrail
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
                _emit(event_queue, "loop_guardrail", {
                    "stage": stage, "loop_count": loop_count,
                    "reason": guardrail, "forced_advance": True,
                })
        elif decision.decision == "loop_back" and loop_count == 0:
            self.metrics_svc.save_guardrail_snapshot(piece, stage)

        # Execute decision
        if decision.decision == "loop_back":
            piece.set_loop_count(stage, loop_count + 1)
            if not is_content:
                piece.write_decision(stage, decision.decision, decision.critique)
            logger.info("Stage '%s' loop_back (loop %d/%d)",
                        stage, loop_count + 1, agent_cfg.max_loops)
            _emit(event_queue, "loop_start", {
                "stage": stage, "loop_count": loop_count + 1,
                "max_loops": agent_cfg.max_loops,
                "critique": decision.critique[:300],
            })
        elif decision.decision == "advance":
            piece.set_loop_count(stage, 0)
            piece.set_stage_state(stage, "ready")
            self.metrics_svc.cleanup_guardrail_snapshot(piece, stage)
            if not is_content:
                piece.write_output(stage, self._format_feedback(decision.critique))
            if is_content:
                self.metrics_svc.compute(piece, stage)
            # Auto-advance only if trigger allows it or forced (chain mode)
            auto_advance = force_advance or agent_cfg.trigger in ("auto",)
            if auto_advance and sc.stage_def and sc.stage_def.next:
                piece.advance_to(sc.stage_def.next)
                logger.info("Stage '%s' → advance to '%s'", stage, sc.stage_def.next)
            else:
                logger.info("Stage '%s' → advance decision (no auto-advance, trigger=%s)", stage, agent_cfg.trigger)
        else:
            logger.warning("Stage '%s' returned unknown decision: '%s'",
                           stage, decision.decision)

        _emit(event_queue, "stage_complete", {
            "stage": stage, "decision": decision.decision,
            "critique": decision.critique[:500],
            "loop_count": loop_count, "error": decision.error,
        })

        return decision

    # ------------------------------------------------------------------
    # Chain execution
    # ------------------------------------------------------------------

    def run_chain(
        self, piece_id: str, from_stage: str | None = None,
        output_dir: Path | None = None, event_queue=None,
    ) -> list[AgentDecision]:
        """Run a chain of stages from the current stage to done."""
        return self.chain.run(
            piece_id, self.llm, self.run_stage,
            from_stage, output_dir, event_queue,
        )

    # ------------------------------------------------------------------
    # Research stage (special — no agent prompt)
    # ------------------------------------------------------------------

    def _run_research(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
        event_queue=None, force_advance: bool = False,
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

        _emit(event_queue, "stage_start", {
            "stage": stage, "is_content_stage": False, "is_research": True,
        })

        input_content = self.assembler.read_inputs(piece, stage, pipeline)
        stage_dir = piece.stage_dir()
        research_file = stage_dir / _stage_filename(stage)

        svc = ResearchService()
        if svc.is_fresh(research_file):
            _emit(event_queue, "research_cached", {
                "stage": stage, "file": str(research_file),
            })
            return AgentDecision(
                decision="advance", critique="Research cache hit.",
                output="", stage=stage,
            )

        brief_text, outline_text = "", ""
        for block in input_content.split("=== "):
            if block.startswith(_stage_filename("brief")):
                brief_text = block.split("\n", 1)[-1] if "\n" in block else ""
            elif block.startswith(_stage_filename("outline")):
                outline_text = block.split("\n", 1)[-1] if "\n" in block else ""

        from .agent import load_model_config
        model_cfg = load_model_config()
        debug = model_cfg.get("debug_prompts", False)
        llm_client = LLMClient(
            api_base=model_cfg.get("api_base", "https://api.openai.com/v1"),
            api_key=model_cfg.get("api_key", ""),
            model=model_cfg.get("model", "gpt-4o"),
            temperature=0.3,
            max_tokens=200,
        )

        svc = ResearchService(llm_client=llm_client)

        if debug:
            debug_file = stage_dir / _stage_filename(stage, ".generate-prompt.md")
            debug_content = (
                f"# Debug: research query generation prompt\n"
                f"# Piece: {piece.id}\n\n"
                f"## System\nYou are a research assistant. Given a writing brief and outline, "
                f"generate 3-5 web search queries.\n\n"
                f"## Brief (first 2000 chars)\n{brief_text[:2000]}\n\n"
                f"## Outline (first 2000 chars)\n{outline_text[:2000]}\n"
            )
            debug_file.write_text(debug_content, encoding="utf-8")
            logger.info("Debug research prompt dumped to %s", debug_file)

        result = svc.execute(
            brief_text=brief_text,
            outline_text=outline_text,
            research_file=research_file,
        )

        def _write_research_with_frontmatter(content: str):
            import yaml
            from datetime import datetime, timezone
            fm = yaml.dump({
                "id": piece.id, "title": piece.title,
                "genre": piece.genre, "type": piece.type,
                "audience": getattr(piece, 'audience', ''),
                "tone": getattr(piece, 'tone', ''),
                "language": piece.language,
                "current_stage": "research",
                "created": getattr(piece, 'created', datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }, default_flow_style=False, allow_unicode=True, sort_keys=False)
            research_file.write_text(f"---\n{fm}---\n{content}", encoding="utf-8")

        if result.from_cache:
            critique = "Research cache hit."
        elif result.results:
            _write_research_with_frontmatter(result.markdown)
            fallback = " (fallback queries)" if result.used_fallback else ""
            critique = f"Found {len(result.results)} sources from {len(result.queries)} queries{fallback}."
            logger.info("Research complete: %s", critique)
        else:
            _write_research_with_frontmatter(result.markdown)
            fallback = " (fallback queries)" if result.used_fallback else ""
            critique = f"No research results found{fallback}."
            logger.warning("Research returned no results")

        _emit(event_queue, "research_complete", {
            "stage": stage, "queries": len(result.queries),
            "results": len(result.results), "cached": result.from_cache,
        })

        from .run_logger import RunLogger
        run_logger = RunLogger()
        run_logger.log(piece, stage, "research", "ResearchService", "\n".join(result.queries), {
            "queries": len(result.queries),
            "results": len(result.results),
            "cached": result.from_cache,
            "used_fallback": result.used_fallback,
        }, trace_id=locals().get("trace_id"))

        agent_cfg = load_agent_config(self.agent_set, "brief")
        auto_advance = force_advance or (agent_cfg.trigger in ("auto",) if agent_cfg else True)
        stage_def = pipeline.get_stage(stage)
        if auto_advance and stage_def and stage_def.next:
            piece.advance_to(stage_def.next)
            logger.info("Research → advance to '%s'", stage_def.next)
        else:
            logger.info("Research complete (no auto-advance, trigger=%s)", agent_cfg.trigger if agent_cfg else "?")

        return AgentDecision(
            decision="advance", critique=critique,
            output=result.markdown[:500], stage=stage,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_feedback(self, critique: str) -> str:
        """Clean feedback text by stripping JSON code fences and formatting."""
        from .agent import _strip_json_block
        cleaned = _strip_json_block(critique)
        return cleaned if cleaned else critique


# Re-export for backward compatibility
from .run_manager import RunManager  # noqa: E402
