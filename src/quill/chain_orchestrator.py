"""ChainOrchestrator — sequential stage execution with retry logic.

Runs a chain of stages from a starting point to 'done'. Handles retry
on transient LLM failures, skip logic for missing prompts, and research
stage routing.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from .agent import AgentDecision, load_agent_config
from .piece import load_piece, _stage_filename
from .stage_runner import LLMCaller, _emit
from .timeit import timeit

logger = logging.getLogger(__name__)


class ChainOrchestrator:
    """Run a chain of stages sequentially with retry logic."""

    def __init__(self, agent_set: str = "default"):
        self.agent_set = agent_set

    def _load_chain_retry(self) -> int:
        """Load chain_retry setting from the agent set's config.yaml."""
        from .agent import AGENTS_DIR
        import yaml
        config_file = AGENTS_DIR / self.agent_set / "config.yaml"
        if not config_file.exists():
            return 0
        cfg = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        return cfg.get("chain_retry", 0)

    @timeit("ChainOrchestrator.run")
    def run(
        self,
        piece_id: str,
        stage_runner: LLMCaller,
        run_stage_fn,
        from_stage: str | None = None,
        output_dir: Path | None = None,
        event_queue=None,
    ) -> list[AgentDecision]:
        """Run a chain of stages from the current stage to done.

        Args:
            piece_id: The piece ID to process.
            stage_runner: LLMCaller instance (for research delegation).
            run_stage_fn: Callable(piece_id, stage, output_dir, event_queue, trace_id, force_advance)
                          — the Runner.run_stage method.
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
        max_stages = 20
        skipped_stages: list[str] = []
        trace_id = str(uuid.uuid4())

        _emit(event_queue, "chain_start", {
            "piece_id": piece_id, "from_stage": current,
            "agent_set": self.agent_set,
        })

        while current and current != "done" and len(results) < max_stages:
            chain_retry = self._load_chain_retry()

            # Research stage routing
            if current == "research":
                from .agent import load_research_config
                research_cfg = load_research_config(self.agent_set)
                if not research_cfg.get("enabled"):
                    logger.info("Research disabled for agent set '%s', skipping", self.agent_set)
                    skipped_stages.append(current)
                    stage_def = pipeline.get_stage(current)
                    current = stage_def.next if stage_def else None
                    continue
                result = run_stage_fn(piece_id, current, output_dir, event_queue=event_queue, trace_id=trace_id, force_advance=True)
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

            # Run with retry
            result = None
            for attempt in range(chain_retry + 1):
                try:
                    result = run_stage_fn(piece_id, current, output_dir, event_queue=event_queue, trace_id=trace_id, force_advance=True)
                except (ConnectionError, TimeoutError, OSError) as exc:
                    if attempt < chain_retry:
                        backoff = 2 ** attempt
                        logger.warning(
                            "Stage '%s' transient failure (attempt %d/%d), "
                            "retrying in %ds: %s",
                            current, attempt + 1, chain_retry + 1, backoff, exc,
                        )
                        _emit(event_queue, "chain_retry", {
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
                    result = AgentDecision(
                        decision="error", critique="", output="",
                        error=str(exc),
                    )
                break

            if result is None:
                result = AgentDecision(
                    decision="error", critique="", output="",
                    error="Unexpected empty result",
                )

            results.append(result)

            _emit(event_queue, "chain_stage_complete", {
                "stage": result.stage, "decision": result.decision,
                "completed": len(results), "error": result.error,
            })

            if result.error:
                break
            if result.decision == "advance":
                piece = load_piece(piece_dir)
                current = piece.current_stage
            elif result.decision == "loop_back":
                pass
            else:
                break

        if not results and skipped_stages:
            _emit(event_queue, "chain_complete", {
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

        _emit(event_queue, "chain_complete", {
            "total_stages": len(results), "skipped": skipped_stages,
            "last_decision": results[-1].decision if results else None,
        })
        return results
