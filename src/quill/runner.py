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

    def compose_prompt(self, piece_id: str, stage: str, output_dir: Path | None = None) -> dict:
        """Assemble the full prompt for a stage without calling the LLM.

        Returns a dict with the system prompt, user prompt, and metadata
        so you can inspect exactly what would be sent.
        """
        from .pipeline import load_pipeline
        pipeline = load_pipeline("default")
        stage_def = pipeline.get_stage(stage)

        from .piece import DEFAULT_OUTPUT_DIR
        base = output_dir or DEFAULT_OUTPUT_DIR
        piece_dir = base / piece_id
        if not piece_dir.exists():
            return {"error": f"Piece '{piece_id}' not found"}

        piece = load_piece(piece_dir)

        agent_cfg = load_agent_config(self.agent_set, stage)
        if not agent_cfg or not agent_cfg.prompt_template:
            return {"error": f"No agent config for stage '{stage}' in set '{self.agent_set}'"}

        loop_count = self.get_loop_count(piece, stage)
        input_content = self._read_inputs(piece, stage, pipeline)

        prompt = agent_cfg.prompt_template.replace("{{CONTENT}}", input_content)
        prompt = prompt.replace("{{STAGE}}", stage)
        prompt = prompt.replace("{{PIECE_ID}}", piece_id)
        prompt = prompt.replace("{{TITLE}}", piece.title)
        prompt = prompt.replace("{{GENRE}}", piece.genre)
        prompt = prompt.replace("{{TYPE}}", piece.type)
        prompt = prompt.replace("{{LANGUAGE}}", piece.language)

        metrics_context = self._build_metrics_context(piece, stage, pipeline)
        prompt = prompt.replace("{{METRICS}}", metrics_context)

        content_stages = {"outline", "draft", "revise", "humanize", "polish"}
        is_content_stage = stage in content_stages

        if is_content_stage:
            gen_system = (
                f"You are a {stage} agent for a {piece.genre} {piece.type} "
                f"in {piece.language}. Produce high-quality content. "
                f"Do NOT include any JSON or decision blocks — just write the content."
            )
            # Build the evaluate prompt too (no LLM call)
            eval_prompt = (
                f"You are a quality evaluator for a {piece.genre} {piece.type}.\n\n"
                f"## Stage: {stage}\n\n"
                f"## Input given to the {stage} agent:\n{input_content[:2000]}\n\n"
                f"## Generated {stage} output:\n<not yet generated>\n\n"
                f"## Task\n"
                f"Evaluate the generated {stage} output. Is it high quality? "
                f"Does it meet the requirements?\n\n"
                f"Be strict but fair. Only loop_back if there are real, fixable problems."
            )
            eval_system = (
                f"You are a quality evaluator. Respond with ONLY a JSON block "
                f"containing 'decision' (advance or loop_back) and 'critique'."
            )
            return {
                "piece_id": piece_id,
                "stage": stage,
                "agent_set": self.agent_set,
                "loop_count": loop_count,
                "max_loops": agent_cfg.max_loops,
                "is_content_stage": True,
                "model": agent_cfg.model,
                "api_base": agent_cfg.api_base,
                "temperature": agent_cfg.temperature,
                "max_tokens": agent_cfg.max_tokens,
                "generate": {
                    "system": gen_system,
                    "user": prompt,
                    "char_count": len(prompt),
                },
                "evaluate": {
                    "system": eval_system,
                    "user": eval_prompt,
                    "char_count": len(eval_prompt),
                    "note": "The 'Generated output' section above shows '<not yet generated>' — the real evaluate prompt includes the actual generated text from the generate call.",
                },
                "input_content_char_count": len(input_content),
                "template_vars": {
                    "TITLE": piece.title,
                    "GENRE": piece.genre,
                    "TYPE": piece.type,
                    "LANGUAGE": piece.language,
                    "STAGE": stage,
                    "PIECE_ID": piece_id,
                    "METRICS": metrics_context,
                },
            }
        else:
            eval_system = (
                f"You are a {stage} agent for a {piece.genre} {piece.type} "
                f"in {piece.language}. Be critical and precise. "
                f"Respond with a JSON block containing 'decision' and 'critique'."
            )
            return {
                "piece_id": piece_id,
                "stage": stage,
                "agent_set": self.agent_set,
                "loop_count": loop_count,
                "max_loops": agent_cfg.max_loops,
                "is_content_stage": False,
                "model": agent_cfg.model,
                "api_base": agent_cfg.api_base,
                "temperature": agent_cfg.temperature,
                "max_tokens": agent_cfg.max_tokens,
                "single_call": {
                    "system": eval_system,
                    "user": prompt,
                    "char_count": len(prompt),
                },
                "input_content_char_count": len(input_content),
                "template_vars": {
                    "TITLE": piece.title,
                    "GENRE": piece.genre,
                    "TYPE": piece.type,
                    "LANGUAGE": piece.language,
                    "STAGE": stage,
                    "PIECE_ID": piece_id,
                    "METRICS": metrics_context,
                },
            }

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
        prompt = prompt.replace("{{TYPE}}", piece.type)
        prompt = prompt.replace("{{LANGUAGE}}", piece.language)

        # Inject text metrics from input stages
        from .metrics import load_metrics
        metrics_context = self._build_metrics_context(piece, stage, pipeline)
        prompt = prompt.replace("{{METRICS}}", metrics_context)

        client = LLMClient(
            api_base=agent_cfg.api_base,
            api_key=agent_cfg.api_key,
            model=agent_cfg.model,
            temperature=agent_cfg.temperature,
            max_tokens=agent_cfg.max_tokens,
        )

        content_stages = {"outline", "draft", "revise", "humanize", "polish"}
        is_content_stage = stage in content_stages

        if is_content_stage:
            # Two-call approach: generate first, then evaluate
            gen_system = (
                f"You are a {stage} agent for a {piece.genre} {piece.type} "
                f"in {piece.language}. Produce high-quality content. "
                f"Do NOT include any JSON or decision blocks — just write the content."
            )
            try:
                generated = client.chat(gen_system, prompt)
            except ConnectionError as e:
                return AgentDecision(
                    decision="error", critique="", output="",
                    error=str(e), stage=stage,
                )

            # Persist generated content immediately (survives loop_back)
            self._write_output(piece, stage, generated)

            # Second call: evaluate the generated content
            decision = self._evaluate_output(
                client, stage, piece, generated, pipeline, input_content
            )
            decision.body = generated
            decision.output = generated

            # Persist evaluation result to separate file
            self._write_decision(piece, stage, decision)
        else:
            # Feedback stages: single call with JSON decision expected
            eval_system = (
                f"You are a {stage} agent for a {piece.genre} {piece.type} "
                f"in {piece.language}. Be critical and precise. "
                f"Respond with a JSON block containing 'decision' and 'critique'."
            )
            try:
                response = client.chat(eval_system, prompt)
            except ConnectionError as e:
                return AgentDecision(
                    decision="error", critique="", output="",
                    error=str(e), stage=stage,
                )
            decision = parse_agent_response(response)
            decision.output = response

        decision.loop_count = loop_count
        decision.stage = stage

        # Execute decision
        if decision.decision == "loop_back":
            self.set_loop_count(piece, stage, loop_count + 1)
            # For feedback stages, write critique to decision file
            if not is_content_stage:
                self._write_decision(piece, stage, decision)
            # Content stages already wrote both output and decision above
            logger.info("Stage '%s' loop_back (loop %d/%d)",
                       stage, loop_count + 1, agent_cfg.max_loops)
        elif decision.decision == "advance":
            # Reset loop count for this stage
            self.set_loop_count(piece, stage, 0)
            # Content stages: output already written above, just clean up decision file
            # Feedback stages: write critique as the stage output
            if not is_content_stage:
                self._write_output(piece, stage, self._format_feedback(decision.critique))
            # Compute text metrics for content stages
            if is_content_stage:
                self._compute_metrics(piece, stage)
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
        skipped_stages = []

        while current and current != "done" and len(results) < max_stages:
            # Check if agent set has a prompt for this stage
            agent_cfg = load_agent_config(self.agent_set, current)
            if not agent_cfg or not agent_cfg.prompt_template:
                logger.warning(
                    "Skipping stage '%s' — no agent prompt in set '%s'",
                    current, self.agent_set,
                )
                skipped_stages.append(current)
                # Advance to next stage via pipeline
                stage_def = pipeline.get_stage(current)
                if stage_def and stage_def.next:
                    current = stage_def.next
                    continue
                else:
                    break

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

        # If no stages ran and we only skipped, return an error
        if not results and skipped_stages:
            return [AgentDecision(
                decision="error", critique="", output="",
                error=(
                    f"No agent prompts found for any stage starting from "
                    f"'{from_stage or piece.current_stage}' in set '{self.agent_set}'. "
                    f"Skipped: {', '.join(skipped_stages)}"
                ),
            )]

        return results

    # Stage-specific input requirements (override default "previous stage" logic)
    # Maps stage → list of files to read as input
    # Content stages read from the PREVIOUS CONTENT stage, not the feedback stage before them
    _STAGE_INPUTS = {
        "outline": ["brief.md"],                       # needs brief
        "draft": ["outline.md", "brief.md"],           # needs outline + brief
        "revise": ["draft.md", "review.md"],       # needs draft + critique
        "humanize": ["revise.md"],                  # needs revised text
        "polish": ["humanize.md", "validate.md"],   # needs humanized text + validation feedback
    }

    def _read_inputs(self, piece: Piece, stage: str, pipeline) -> str:
        """Read input files for a stage.

        Uses stage-specific input mapping when defined,
        otherwise falls back to reading the previous stage's output.
        """
        stage_dir = piece.stage_dir()
        inputs = []

        # Stage-specific inputs
        if stage in self._STAGE_INPUTS:
            for fname in self._STAGE_INPUTS[stage]:
                fpath = stage_dir / fname
                if fpath.exists():
                    text = fpath.read_text(encoding="utf-8")
                    m = _FRONTMATTER_RE.match(text)
                    inputs.append(f"=== {fname} ===\n{text[m.end():] if m else text}")
        else:
            # Default: read previous stage's output
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

        # If looping, also read the current stage's existing content and decision
        current_file = stage_dir / f"{stage}.md"
        if current_file.exists():
            text = current_file.read_text(encoding="utf-8")
            m = _FRONTMATTER_RE.match(text)
            body = text[m.end():] if m else text
            if body.strip():
                inputs.append(f"=== {stage}.md (previous attempt) ===\n{body}")

        decision_file = stage_dir / f"{stage}.decision.md"
        if decision_file.exists():
            text = decision_file.read_text(encoding="utf-8")
            inputs.append(f"=== {stage}.decision.md (evaluation feedback) ===\n{text}")

        return "\n\n".join(inputs) if inputs else "(no input files found)"

    def _format_feedback(self, critique: str) -> str:
        """Clean feedback text by stripping JSON code fences and formatting."""
        from .agent import _strip_json_block
        cleaned = _strip_json_block(critique)
        return cleaned if cleaned else critique

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

    def _write_decision(self, piece: Piece, stage: str, decision: "AgentDecision"):
        """Write evaluation decision to a separate .decision.md file."""
        decision_file = piece.stage_dir() / f"{stage}.decision.md"
        content = (
            f"## Decision: {decision.decision}\n\n"
            f"## Critique\n{decision.critique}\n"
        )
        decision_file.write_text(content, encoding="utf-8")
        logger.info("Wrote decision to %s", decision_file)

    def _compute_metrics(self, piece: Piece, stage: str):
        """Compute and save text metrics for a stage's output file."""
        from .metrics import compute_and_save
        stage_file = piece.stage_dir() / f"{stage}.md"
        if stage_file.exists():
            try:
                metrics = compute_and_save(stage_file)
                logger.info("Metrics for %s/%s: flesch=%.1f, words=%d",
                           piece.id, stage, metrics["flesch_ease"], metrics["word_count"])
            except Exception as e:
                logger.warning("Failed to compute metrics for %s/%s: %s",
                              piece.id, stage, e)

    def _build_metrics_context(self, piece: Piece, stage: str, pipeline) -> str:
        """Build a metrics context string for the agent prompt.

        Loads metrics from the input stages and formats them as a readable block.
        """
        from .metrics import load_metrics

        stage_dir = piece.stage_dir()
        lines = []

        # Get input stage names
        if stage in self._STAGE_INPUTS:
            input_stages = [f.replace(".md", "") for f in self._STAGE_INPUTS[stage]]
        else:
            stage_order = pipeline.stage_order
            if stage in stage_order:
                idx = stage_order.index(stage)
                input_stages = [stage_order[idx - 1]] if idx > 0 else []
            else:
                input_stages = []

        for input_stage in input_stages:
            mfile = stage_dir / f"{input_stage}.metrics.yaml"
            m = load_metrics(mfile) if mfile.exists() else None
            if m:
                lines.append(f"--- {input_stage} metrics ---")
                lines.append(f"  Flesch Reading Ease: {m.get('flesch_ease', 'n/a')}")
                lines.append(f"  Flesch-Kincaid Grade: {m.get('flesch_kincaid', 'n/a')}")
                lines.append(f"  Word count: {m.get('word_count', 'n/a')}")
                lines.append(f"  Avg sentence length: {m.get('avg_sentence_length', 'n/a')} words")
                lines.append(f"  Vocabulary diversity: {round(m.get('type_token_ratio', 0) * 100, 1)}%")
                lines.append(f"  Passive voice: {m.get('passive_voice_pct', 'n/a')}%")

        # Also include current stage metrics if looping
        current_file = stage_dir / f"{stage}.metrics.yaml"
        if current_file.exists():
            m = load_metrics(current_file)
            if m:
                lines.append(f"--- {stage} metrics (current) ---")
                lines.append(f"  Flesch Reading Ease: {m.get('flesch_ease', 'n/a')}")
                lines.append(f"  Word count: {m.get('word_count', 'n/a')}")
                lines.append(f"  Vocabulary diversity: {round(m.get('type_token_ratio', 0) * 100, 1)}%")

        return "\n".join(lines) if lines else "(no metrics available)"

    def _evaluate_output(
        self, client: "LLMClient", stage: str, piece: "Piece",
        generated: str, pipeline, input_content: str,
    ) -> AgentDecision:
        """Second call: evaluate generated content and return a JSON decision."""
        eval_prompt = (
            f"You are a quality evaluator for a {piece.genre} {piece.type}.\n\n"
            f"## Stage: {stage}\n\n"
            f"## Input given to the {stage} agent:\n{input_content[:2000]}\n\n"
            f"## Generated {stage} output:\n{generated[:4000]}\n\n"
            f"## Task\n"
            f"Evaluate the generated {stage} output. Is it high quality? "
            f"Does it meet the requirements? Respond with ONLY a JSON block:\n\n"
            f'{{"decision": "advance", "critique": "brief feedback"}}\n'
            f'or\n'
            f'{{"decision": "loop_back", "critique": "specific issues to fix"}}\n\n'
            f"Be strict but fair. Only loop_back if there are real, fixable problems."
        )
        eval_system = (
            f"You are a quality evaluator. Respond with ONLY a JSON block "
            f"containing 'decision' (advance or loop_back) and 'critique'."
        )
        try:
            eval_response = client.chat(eval_system, eval_prompt)
        except ConnectionError:
            # If evaluation fails, default to advance (trust the generation)
            return AgentDecision(decision="advance", critique="Evaluation call failed, advancing by default.", output="")

        return parse_agent_response(eval_response)

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
