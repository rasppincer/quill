"""Prompt building — template rendering, context assembly, system prompt decoration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2

from .piece import _stage_filename

if TYPE_CHECKING:
    from .piece import Piece


def render_prompt(template: str, context: dict) -> str:
    """Render a prompt template with Jinja2, falling back to .replace().

    Jinja2 enables conditionals ({% if %}), loops, and filters.
    Falls back to simple string replacement if the template contains
    syntax that breaks Jinja2 (e.g., code examples with { }).
    """
    try:
        t = jinja2.Environment(
            undefined=jinja2.Undefined  # silently ignore undefined vars
        ).from_string(template)
        return t.render(**context)
    except jinja2.TemplateSyntaxError:
        result = template
        for key, value in context.items():
            result = result.replace("{{" + key + "}}", str(value))
        return result


class PromptBuilder:
    """Assembles template contexts and renders prompts."""

    def build_context(
        self,
        piece: "Piece",
        stage: str,
        input_content: str,
        metrics_context: str,
        loop_count: int = 0,
        extra: dict | None = None,
    ) -> dict:
        """Build the full template variable context for prompt rendering."""
        ctx = {
            "TITLE": piece.title,
            "GENRE": piece.genre,
            "TYPE": piece.type,
            "LANGUAGE": piece.language,
            "STAGE": stage,
            "PIECE_ID": piece.id,
            "CONTENT": input_content,
            "METRICS": metrics_context,
            "loop_count": loop_count,
            "is_looping": loop_count > 0,
        }
        # Structure stage: inject segment calculation variables
        if stage == "structure":
            from .structure import calculate_segments, parse_target_length
            target = parse_target_length(getattr(piece, "target_length", ""))
            seg = calculate_segments(target)
            ctx.update({
                "SEGMENT_COUNT": seg["count"],
                "SEGMENT_STYLE": seg["style"],
                "SEGMENT_NAME": seg["name"],
                "SEGMENT_TARGET": seg["target"],
            })
        if extra:
            ctx.update(extra)
        return ctx

    @staticmethod
    def date_context() -> str:
        """Return a date context string to inject into system prompts."""
        now = datetime.now()
        return (
            f"IMPORTANT: Today is {now.strftime('%d %B %Y')}. "
            f"Your training data may be older. "
            f"Execute all tasks knowing the current date is {now.strftime('%d %B %Y')}."
        )

    @classmethod
    def with_date(cls, system_prompt: str) -> str:
        """Prepend date context to a system prompt."""
        return f"{system_prompt}\n\n{cls.date_context()}"

    @classmethod
    def system_prompt(cls, stage: str, piece: "Piece", call_type: str) -> str:
        """Build a system prompt for a stage.

        Args:
            stage: Stage name (e.g. "review", "revise").
            piece: The piece being processed.
            call_type: One of "generate", "evaluate", or "feedback".
        """
        if call_type == "generate":
            text = (
                f"You are a {stage} agent for a {piece.genre} {piece.type} "
                f"in {piece.language}. Produce high-quality content. "
                f"Do NOT include any JSON or decision blocks — just write the content."
            )
        elif call_type == "evaluate":
            text = (
                "You are a quality evaluator. Respond with ONLY a JSON block "
                "containing 'decision' (advance or loop_back) and 'critique'."
            )
        elif call_type == "feedback":
            text = (
                f"You are a {stage} agent for a {piece.genre} {piece.type} "
                f"in {piece.language}. Be critical and precise. "
                f"Respond with a JSON block containing 'decision' and 'critique'."
            )
        else:
            raise ValueError(f"Unknown call_type: {call_type}")
        return cls.with_date(text)

    @staticmethod
    def load_evaluate_template(agent_set: str) -> str | None:
        """Load evaluate.prompt.md from an agent set directory."""
        from .agent import AGENTS_DIR
        template_file = AGENTS_DIR / agent_set / "evaluate.prompt.md"
        if template_file.exists():
            return template_file.read_text(encoding="utf-8")
        return None

    @staticmethod
    def resolve_input_stages(stage: str, pipeline) -> list[str]:
        """Resolve input stage names for a given stage."""
        stage_inputs = pipeline.stage_inputs if pipeline else {}
        if stage in stage_inputs:
            return [f.replace(".md", "") for f in stage_inputs[stage]]
        stage_order = pipeline.stage_order
        if stage in stage_order:
            idx = stage_order.index(stage)
            return [stage_order[idx - 1]] if idx > 0 else []
        return []

    @staticmethod
    def get_structured_output_format() -> dict | None:
        """Return response_format dict if structured_output is enabled."""
        from .agent import load_model_config
        cfg = load_model_config()
        if cfg.get("structured_output"):
            return {"type": "json_object"}
        return None
