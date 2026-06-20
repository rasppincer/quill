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
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .agent import AgentConfig, AgentDecision, load_agent_config, parse_agent_response
from .llm import LLMClient
from .piece import Piece, load_piece, _FRONTMATTER_RE

logger = logging.getLogger(__name__)


class StageRunner:
    """Executes a pipeline stage using an LLM agent."""

    def __init__(self, agent_set: str = "default"):
        self.agent_set = agent_set

    def get_loop_count(self, piece: Piece, stage: str) -> int:
        """Get the current loop count for a stage."""
        meta_path = piece.stage_dir() / "meta.yaml"
        if not meta_path.exists():
            return 0
        meta = yaml.safe_load(meta_path.read_text()) or {}
        return meta.get("loops", {}).get(stage, 0)

    def set_loop_count(self, piece: Piece, stage: str, count: int):
        """Update the loop count for a stage in meta.yaml."""
        meta_path = piece.stage_dir() / "meta.yaml"
        meta = yaml.safe_load(meta_path.read_text()) or {}
        if "loops" not in meta:
            meta["loops"] = {}
        meta["loops"][stage] = count
        meta_path.write_text(
            yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def run_stage(self, piece_id: str, stage: str, output_dir: Path | None = None) -> AgentDecision:
        """Execute a pipeline stage.

        Args:
            piece_id: The piece ID to process.
            stage: The stage to execute (e.g. "review", "revise").
            output_dir: Override output directory.

        Returns:
            AgentDecision with the result.
        """
        from .pipeline import load_pipeline
        pipeline = load_pipeline("default")
        stage_def = pipeline.get_stage(stage)

        # Load piece
        from .piece import DEFAULT_OUTPUT_DIR
        base = output_dir or DEFAULT_OUTPUT_DIR
        piece_dir = base / piece_id
        if not piece_dir.exists():
            return AgentDecision(
                decision="error",
                critique="",
                output="",
                error=f"Piece '{piece_id}' not found",
            )

        piece = load_piece(piece_dir)

        # Load agent config
        agent_cfg = load_agent_config(self.agent_set, stage)
        if not agent_cfg or not agent_cfg.prompt_template:
            return AgentDecision(
                decision="error",
                critique="",
                output="",
                error=f"No agent config for stage '{stage}' in set '{self.agent_set}'",
            )

        # Check loop limit
        loop_count = self.get_loop_count(piece, stage)
        if loop_count >= agent_cfg.max_loops:
            logger.info("Stage '%s' reached max loops (%d), forcing advance",
                       stage, agent_cfg.max_loops)
            return AgentDecision(
                decision="advance",
                critique=f"Max loops ({agent_cfg.max_loops}) reached. Forcing advance.",
                output="",
                loop_count=loop_count,
                stage=stage,
            )

        # Read input files
        input_content = self._read_inputs(piece, stage, pipeline)

        # Fill prompt template
        prompt = agent_cfg.prompt_template.replace("{{CONTENT}}", input_content)
        prompt = prompt.replace("{{STAGE}}", stage)
        prompt = prompt.replace("{{PIECE_ID}}", piece_id)
        prompt = prompt.replace("{{TITLE}}", piece.title)
        prompt = prompt.replace("{{GENRE}}", piece.genre)
        prompt = prompt.replace("{{LANGUAGE}}", piece.language)

        # Call LLM
        system_prompt = (
            f"You are a {stage} agent for a {piece.genre} {piece.type} "
            f"in {piece.language}. Be critical and precise. "
            f"Respond with a JSON block containing 'decision' and 'critique'."
        )

        client = LLMClient(
            api_base=agent_cfg.api_base,
            api_key=agent_cfg.api_key,
            model=agent_cfg.model,
            temperature=agent_cfg.temperature,
            max_tokens=agent_cfg.max_tokens,
        )

        try:
            response = client.chat(system_prompt, prompt)
        except ConnectionError as e:
            return AgentDecision(
                decision="error",
                critique="",
                output="",
                error=str(e),
                stage=stage,
            )

        # Parse response
        decision = parse_agent_response(response)
        decision.loop_count = loop_count
        decision.stage = stage

        # Execute decision
        if decision.decision == "loop_back":
            self.set_loop_count(piece, stage, loop_count + 1)
            # Write critique to stage file (so next pass can use it)
            self._write_critique(piece, stage, decision.critique)
            logger.info("Stage '%s' loop_back (loop %d/%d)",
                       stage, loop_count + 1, agent_cfg.max_loops)
        elif decision.decision == "advance":
            # Reset loop count for this stage
            self.set_loop_count(piece, stage, 0)
            # Write output to stage file
            self._write_output(piece, stage, decision.output)
            # Advance meta.yaml to next stage
            if stage_def and stage_def.next:
                self._advance_meta(piece, stage_def.next)
            logger.info("Stage '%s' → advance to '%s'", stage,
                       stage_def.next if stage_def else "?")
        else:
            logger.warning("Stage '%s' returned unknown decision: '%s'",
                          stage, decision.decision)

        return decision

    def run_chain(self, piece_id: str, from_stage: str | None = None,
                  output_dir: Path | None = None) -> list[AgentDecision]:
        """Run a chain of stages from the current stage to done.

        Args:
            piece_id: The piece ID to process.
            from_stage: Start from this stage (default: current stage).
            output_dir: Override output directory.

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
        results = []
        max_stages = 20  # safety limit

        while current and current != "done" and len(results) < max_stages:
            result = self.run_stage(piece_id, current, output_dir)
            results.append(result)

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

        return results

    def _read_inputs(self, piece: Piece, stage: str, pipeline) -> str:
        """Read input files for a stage.

        The input is typically the output of the previous stage,
        plus any critique from the current stage if looping.
        """
        stage_dir = piece.stage_dir()

        # Determine which files to read as input
        inputs = []

        # Read the previous stage's output
        stage_order = pipeline.stage_order
        if stage in stage_order:
            idx = stage_order.index(stage)
            if idx > 0:
                prev_stage = stage_order[idx - 1]
                prev_file = stage_dir / f"{prev_stage}.md"
                if prev_file.exists():
                    text = prev_file.read_text(encoding="utf-8")
                    m = _FRONTMATTER_RE.match(text)
                    inputs.append(f"=== {prev_stage}.md ===\n{text[m.end():] if m else text}")

        # If looping, also read the current stage's existing content (critique)
        current_file = stage_dir / f"{stage}.md"
        if current_file.exists():
            text = current_file.read_text(encoding="utf-8")
            m = _FRONTMATTER_RE.match(text)
            body = text[m.end():] if m else text
            if body.strip():
                inputs.append(f"=== {stage}.md (previous attempt) ===\n{body}")

        # For revise, also read review.md
        if stage == "revise":
            review_file = stage_dir / "review.md"
            if review_file.exists():
                text = review_file.read_text(encoding="utf-8")
                m = _FRONTMATTER_RE.match(text)
                inputs.append(f"=== review.md ===\n{text[m.end():] if m else text}")

        return "\n\n".join(inputs) if inputs else "(no input files found)"

    def _write_output(self, piece: Piece, stage: str, content: str):
        """Write agent output to a stage file."""
        output_file = piece.stage_dir() / f"{stage}.md"
        output_file.write_text(content, encoding="utf-8")
        logger.info("Wrote output to %s", output_file)

    def _write_critique(self, piece: Piece, stage: str, critique: str):
        """Write critique to a stage file (for loop context)."""
        output_file = piece.stage_dir() / f"{stage}.md"
        output_file.write_text(critique, encoding="utf-8")
        logger.info("Wrote critique to %s", output_file)

    def _advance_meta(self, piece: Piece, next_stage: str):
        """Update meta.yaml to point to the next stage."""
        meta_path = piece.stage_dir() / "meta.yaml"
        meta = yaml.safe_load(meta_path.read_text()) or {}
        meta["current_stage"] = next_stage
        meta["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        meta_path.write_text(
            yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        logger.info("Advanced meta.yaml to stage '%s'", next_stage)
