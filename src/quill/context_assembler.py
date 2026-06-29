"""ContextAssembler — prepares stage context for execution.

Loads pipeline, piece, agent config. Reads input files. Builds render
context. Renders prompt templates. Used by StageRunner and the debug
compose-prompt endpoint.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .agent import AgentDecision, load_agent_config
from .metrics_service import MetricsService
from .piece import Piece, load_piece, _FRONTMATTER_RE, _stage_filename
from .prompt_builder import PromptBuilder, render_prompt
from .timeit import timeit

logger = logging.getLogger(__name__)


class ContextAssembler:
    """Assembles all context needed to execute a pipeline stage."""

    def __init__(self, agent_set: str = "default"):
        self.agent_set = agent_set
        self.metrics_svc = MetricsService()
        self.prompt_builder = PromptBuilder()

    @timeit("ContextAssembler.prepare_stage")
    def prepare_stage(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
        extra: dict | None = None,
    ):
        """Load pipeline, piece, agent config, and render the prompt.

        Returns a StageContext namedtuple. Raises ValueError if the piece
        or agent config is not found.

        Args:
            extra: Additional template variables (e.g., orchestrator sliding context).
        """
        from .pipeline import load_pipeline
        from .runner import StageContext

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
        input_content = self.read_inputs(piece, stage, pipeline, loop_count)
        metrics_context = self.metrics_svc.build_context(
            piece, stage, pipeline,
            PromptBuilder.resolve_input_stages(stage, pipeline),
        )
        ctx = self.prompt_builder.build_context(
            piece, stage, input_content, metrics_context, loop_count, extra=extra,
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

    def read_inputs(self, piece: Piece, stage: str, pipeline, loop_count: int = 0) -> str:
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

    def build_render_context(
        self, piece: Piece, stage: str, input_content: str, metrics_context: str,
        loop_count: int | None = None, extra: dict | None = None,
    ) -> dict:
        """Build the full template variable context for prompt rendering."""
        if loop_count is None:
            loop_count = piece.get_loop_count(stage)
        return self.prompt_builder.build_context(
            piece, stage, input_content, metrics_context, loop_count, extra,
        )

    def compose_prompt(
        self, piece_id: str, stage: str, output_dir: Path | None = None,
    ) -> dict:
        """Assemble the full prompt for a stage without calling the LLM.

        Returns a dict with the system prompt, user prompt, and metadata
        so you can inspect exactly what would be sent.
        """
        try:
            sc = self.prepare_stage(piece_id, stage, output_dir)
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
