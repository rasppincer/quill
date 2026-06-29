"""NarrativeState — structured story state for orchestrator context.

Parsed from the state stage YAML output. Merged across chapters to build
cumulative context for the orchestrator's sliding window.

No LLM calls — pure data structure with parse/merge/serialize.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)


@dataclass
class NarrativeState:
    """Cumulative narrative state across chapters.

    Fields match the state stage YAML output format.
    Extra fields (like stakes for fiction) are preserved in `extra`.
    """

    characters: list[dict] = field(default_factory=list)
    plot_threads: list[dict] = field(default_factory=list)
    world_rules: list[str] = field(default_factory=list)
    tone: str = ""
    key_events: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    # Fields that belong to the base schema (not extras)
    _BASE_FIELDS = frozenset({
        "characters", "plot_threads", "world_rules", "tone", "key_events",
    })

    @classmethod
    def from_yaml(cls, raw: str | None) -> NarrativeState:
        """Parse state YAML into a NarrativeState.

        Tolerates missing fields, invalid YAML, and None input.
        Unknown fields are stored in `extra`.
        """
        if not raw or not raw.strip():
            return cls()

        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError:
            logger.warning("Failed to parse state YAML, returning empty state")
            return cls()

        if not isinstance(data, dict):
            return cls()

        extra = {k: v for k, v in data.items() if k not in cls._BASE_FIELDS}

        return cls(
            characters=data.get("characters") or [],
            plot_threads=data.get("plot_threads") or [],
            world_rules=data.get("world_rules") or [],
            tone=data.get("tone") or "",
            key_events=data.get("key_events") or [],
            extra=extra,
        )

    @classmethod
    def merge(cls, states: list[NarrativeState]) -> NarrativeState:
        """Merge multiple NarrativeState objects into a cumulative state.

        Rules:
        - characters: last write wins (matched by name)
        - plot_threads: deduplicated by description, last write wins
        - world_rules: deduplicated (order preserved)
        - tone: last non-empty wins
        - key_events: accumulated (all kept)
        - extra: lists concatenated, scalars last-write-wins
        """
        if not states:
            return cls()

        merged = cls()

        for ns in states:
            # Characters: merge by name (last write wins)
            for char in ns.characters:
                name = char.get("name", "")
                existing = next(
                    (i for i, c in enumerate(merged.characters) if c.get("name") == name),
                    None,
                )
                if existing is not None:
                    merged.characters[existing] = char
                else:
                    merged.characters.append(char)

            # Plot threads: merge by description (last write wins)
            for thread in ns.plot_threads:
                desc = thread.get("description", "")
                existing = next(
                    (i for i, t in enumerate(merged.plot_threads) if t.get("description") == desc),
                    None,
                )
                if existing is not None:
                    merged.plot_threads[existing] = thread
                else:
                    merged.plot_threads.append(thread)

            # World rules: deduplicated
            for rule in ns.world_rules:
                if rule not in merged.world_rules:
                    merged.world_rules.append(rule)

            # Tone: last non-empty wins
            if ns.tone:
                merged.tone = ns.tone

            # Key events: accumulate all
            merged.key_events.extend(ns.key_events)

            # Extra fields: merge
            for key, value in ns.extra.items():
                if key not in merged.extra:
                    merged.extra[key] = value
                elif isinstance(merged.extra[key], list) and isinstance(value, list):
                    merged.extra[key].extend(value)
                else:
                    merged.extra[key] = value  # last write wins

        return merged

    def to_yaml(self) -> str:
        """Serialize to YAML string.

        Output includes base fields first, then extras.
        """
        data = {
            "characters": self.characters,
            "plot_threads": self.plot_threads,
            "world_rules": self.world_rules,
            "tone": self.tone,
            "key_events": self.key_events,
        }
        data.update(self.extra)
        return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
