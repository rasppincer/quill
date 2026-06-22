"""Pipeline — workflow stage definitions and transition logic.

Loads stage definitions from workflow YAML files and enforces
valid transitions between stages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "workflows"


@dataclass
class Stage:
    """A single stage in the writing pipeline."""

    key: str
    name: str
    description: str = ""
    next: str | None = None
    can_reject_to: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    checklist: str = ""


@dataclass
class Pipeline:
    """A configured writing pipeline with ordered stages."""

    name: str
    description: str = ""
    stages: dict[str, Stage] = field(default_factory=dict)
    stage_order: list[str] = field(default_factory=list)
    stage_inputs: dict[str, list[str]] = field(default_factory=dict)

    def get_stage(self, key: str) -> Stage | None:
        """Get a stage by key."""
        return self.stages.get(key)

    def next_stage(self, current: str) -> str | None:
        """Get the next stage after current. Returns None if at 'done'."""
        stage = self.stages.get(current)
        if stage and stage.next:
            return stage.next
        return None

    def can_advance(self, current: str) -> bool:
        """Check if current stage can advance to the next."""
        return self.next_stage(current) is not None

    def valid_reject_targets(self, current: str) -> list[str]:
        """Get list of stages this stage can reject/revert to."""
        stage = self.stages.get(current)
        if stage:
            return stage.can_reject_to
        return []

    def can_reject_to(self, current: str, target: str) -> bool:
        """Check if current stage can reject/revert to target."""
        return target in self.valid_reject_targets(current)

    def validate_transition(self, current: str, target: str) -> tuple[bool, str]:
        """Validate a stage transition.

        Returns (is_valid, message). Transition is valid if:
        - target is the next stage (advance)
        - target is in can_reject_to (revert)
        """
        if current == target:
            return False, f"Already at stage '{current}'"

        if target not in self.stages:
            return False, f"Unknown stage '{target}'"

        # Advance to next
        if self.next_stage(current) == target:
            return True, f"Advancing: {current} → {target}"

        # Revert to allowed target
        if self.can_reject_to(current, target):
            return True, f"Reverting: {current} → {target}"

        return False, f"Cannot transition from '{current}' to '{target}'"

    def progress(self, current: str) -> dict:
        """Get progress info for a piece at the current stage."""
        idx = self.stage_order.index(current) if current in self.stage_order else -1
        total = len(self.stage_order)
        targets = self.valid_reject_targets(current)
        if isinstance(targets, str):
            targets = [targets] if targets else []
        return {
            "current": current,
            "current_index": idx,
            "total_stages": total,
            "percent": round((idx / max(total - 1, 1)) * 100) if idx >= 0 else 0,
            "next": self.next_stage(current),
            "can_reject_to": targets,
        }


def load_pipeline(name: str = "default") -> Pipeline:
    """Load a pipeline definition from a workflow YAML file.

    Args:
        name: Workflow name (filename without .yaml extension).

    Returns:
        Pipeline instance with stages loaded.

    Raises:
        FileNotFoundError: If workflow file doesn't exist.
        ValueError: If workflow YAML is invalid.
    """
    path = WORKFLOWS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Workflow not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    stage_inputs = data.get("stage_inputs", {})
    stages = {}
    stage_order = []

    for stage_def in data.get("stages", []):
        key = stage_def["key"]
        stage = Stage(
            key=key,
            name=stage_def.get("name", key),
            description=stage_def.get("description", ""),
            next=stage_def.get("next"),
            can_reject_to=stage_def.get("can_reject_to", []),
            required_fields=stage_def.get("required_fields", []),
            required_artifacts=stage_def.get("required_artifacts", []),
            rules=stage_def.get("rules", []),
            checklist=stage_def.get("checklist", ""),
        )
        stages[key] = stage
        stage_order.append(key)

    pipeline = Pipeline(
        name=data.get("name", name),
        description=data.get("description", ""),
        stages=stages,
        stage_order=stage_order,
        stage_inputs=stage_inputs,
    )

    logger.info("Loaded pipeline '%s' with %d stages", pipeline.name, len(stages))
    return pipeline
