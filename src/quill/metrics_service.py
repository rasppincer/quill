"""Metrics service — compute, load, format, and guardrail comparison."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import yaml

from .piece import _stage_filename

if TYPE_CHECKING:
    from .piece import Piece

logger = logging.getLogger(__name__)


class MetricsService:
    """Handles text metrics computation, formatting, and loop guardrails."""

    # Guardrail thresholds
    WORD_COUNT_DROP = 0.30
    FLESCH_SHIFT = 15
    TTR_DROP = 0.10
    PASSIVE_VOICE_INCREASE = 10

    def compute(self, piece: Piece, stage: str):
        """Compute and save text metrics for a stage's output file."""
        from .metrics import compute_and_save
        stage_file = piece.stage_dir() / _stage_filename(stage)
        if stage_file.exists():
            try:
                metrics = compute_and_save(stage_file)
                logger.info("Metrics for %s/%s: flesch=%.1f, words=%d",
                            piece.id, stage, metrics["flesch_ease"], metrics["word_count"])
            except Exception as e:
                logger.warning("Failed to compute metrics for %s/%s: %s",
                               piece.id, stage, e)

    def build_context(self, piece: Piece, stage: str, pipeline,
                      input_stages: list[str] | None = None) -> str:
        """Build a metrics context string for the agent prompt.

        Args:
            piece: The piece being processed.
            stage: Current stage name.
            pipeline: Pipeline object with stage_order.
            input_stages: Pre-resolved list of input stage names.
                If None, falls back to pipeline.stage_order lookup.
        """
        from .metrics import load_metrics

        stage_dir = piece.stage_dir()
        lines = []

        if input_stages is None:
            stage_order = pipeline.stage_order
            if stage in stage_order:
                idx = stage_order.index(stage)
                input_stages = [stage_order[idx - 1]] if idx > 0 else []
            else:
                input_stages = []

        for input_stage in input_stages:
            stage_file = stage_dir / _stage_filename(input_stage)
            m = load_metrics(stage_file) if stage_file.exists() else None
            if m:
                lines.append(f"--- {input_stage} metrics ---")
                lines.append(f"  Flesch Reading Ease: {m.get('flesch_ease', 'n/a')}")
                lines.append(f"  Flesch-Kincaid Grade: {m.get('flesch_kincaid', 'n/a')}")
                lines.append(f"  Word count: {m.get('word_count', 'n/a')}")
                lines.append(f"  Avg sentence length: {m.get('avg_sentence_length', 'n/a')} words")
                lines.append(f"  Vocabulary diversity: {round(m.get('type_token_ratio', 0) * 100, 1)}%")
                lines.append(f"  Passive voice: {m.get('passive_voice_pct', 'n/a')}%")

        # Also include current stage metrics if looping
        current_stage_file = stage_dir / _stage_filename(stage)
        if current_stage_file.exists():
            m = load_metrics(current_stage_file)
            if m:
                lines.append(f"--- {stage} metrics (current) ---")
                lines.append(f"  Flesch Reading Ease: {m.get('flesch_ease', 'n/a')}")
                lines.append(f"  Word count: {m.get('word_count', 'n/a')}")
                lines.append(f"  Vocabulary diversity: {round(m.get('type_token_ratio', 0) * 100, 1)}%")

        return "\n".join(lines) if lines else "(no metrics available)"

    def check_guardrail(self, piece: Piece, stage: str, loop_count: int) -> str:
        """Check if metrics are degrading across loop iterations.

        Returns a description of the degradation if guardrail triggers,
        or empty string if metrics are stable/improving.
        """
        from .metrics import load_metrics
        stage_dir = piece.stage_dir()
        stage_file = stage_dir / _stage_filename(stage)

        current = load_metrics(stage_file)
        if not current:
            return ""

        baseline_file = stage_dir / _stage_filename(stage, ".guardrail-metrics.yaml")
        if not baseline_file.exists():
            return ""
        baseline = yaml.safe_load(baseline_file.read_text()) or {}
        if not baseline:
            return ""

        issues = []

        curr_wc = current.get("word_count", 0)
        base_wc = baseline.get("word_count", 0)
        if base_wc > 0 and curr_wc > 0:
            drop = (base_wc - curr_wc) / base_wc
            if drop > self.WORD_COUNT_DROP:
                issues.append(f"word count dropped {drop:.0%} ({base_wc} → {curr_wc})")

        curr_flesch = current.get("flesch_ease", 50)
        base_flesch = baseline.get("flesch_ease", 50)
        shift = abs(curr_flesch - base_flesch)
        if shift > self.FLESCH_SHIFT:
            direction = "harder" if curr_flesch < base_flesch else "easier"
            issues.append(f"readability shifted {shift:.0f} pts ({direction})")

        curr_ttr = current.get("type_token_ratio", 0.5)
        base_ttr = baseline.get("type_token_ratio", 0.5)
        if base_ttr > 0 and curr_ttr > 0:
            ttr_drop = (base_ttr - curr_ttr) / base_ttr
            if ttr_drop > self.TTR_DROP:
                issues.append(f"vocabulary diversity dropped {ttr_drop:.0%}")

        curr_pv = current.get("passive_voice_pct", 0)
        base_pv = baseline.get("passive_voice_pct", 0)
        if curr_pv - base_pv > self.PASSIVE_VOICE_INCREASE:
            issues.append(f"passive voice increased {curr_pv - base_pv:.0f}pp")

        return "; ".join(issues)

    def save_guardrail_snapshot(self, piece: Piece, stage: str):
        """Save current metrics as baseline for loop guardrail comparison."""
        from .metrics import load_metrics
        stage_dir = piece.stage_dir()
        stage_file = stage_dir / _stage_filename(stage)
        current = load_metrics(stage_file)
        if current:
            snapshot_file = stage_dir / _stage_filename(stage, ".guardrail-metrics.yaml")
            snapshot_file.write_text(
                yaml.dump(current, default_flow_style=False),
                encoding="utf-8",
            )
            logger.info("Saved guardrail snapshot for %s", stage)

    def cleanup_guardrail_snapshot(self, piece: Piece, stage: str):
        """Remove guardrail snapshot after successful advance."""
        stage_dir = piece.stage_dir()
        snapshot_file = stage_dir / _stage_filename(stage, ".guardrail-metrics.yaml")
        if snapshot_file.exists():
            snapshot_file.unlink()
            logger.info("Cleaned up guardrail snapshot for %s", stage)
