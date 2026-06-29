"""Tests for narrative_state.py — parse, merge, serialize."""

import pytest
import yaml

from quill.narrative_state import NarrativeState


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParseNarrativeState:
    """Test parsing state YAML into NarrativeState."""

    def test_parse_basic(self):
        raw = yaml.dump({
            "characters": [
                {"name": "Dr. Aris", "state": "suspicious", "location": "lab"},
            ],
            "plot_threads": [
                {"description": "Anomaly growth", "status": "open", "tension": "high"},
            ],
            "world_rules": ["Gold reserves depleted"],
            "tone": "tense",
            "key_events": ["Aris found the pattern"],
        })
        ns = NarrativeState.from_yaml(raw)
        assert len(ns.characters) == 1
        assert ns.characters[0]["name"] == "Dr. Aris"
        assert len(ns.plot_threads) == 1
        assert ns.world_rules == ["Gold reserves depleted"]
        assert ns.tone == "tense"
        assert ns.key_events == ["Aris found the pattern"]

    def test_parse_empty(self):
        ns = NarrativeState.from_yaml("")
        assert ns.characters == []
        assert ns.plot_threads == []
        assert ns.world_rules == []
        assert ns.tone == ""
        assert ns.key_events == []

    def test_parse_none(self):
        ns = NarrativeState.from_yaml(None)
        assert ns.characters == []

    def test_parse_invalid_yaml(self):
        ns = NarrativeState.from_yaml("not: valid: yaml: [[[")
        assert ns.characters == []

    def test_parse_missing_fields(self):
        """Missing fields default to empty."""
        raw = yaml.dump({"characters": [{"name": "Aris"}]})
        ns = NarrativeState.from_yaml(raw)
        assert len(ns.characters) == 1
        assert ns.plot_threads == []
        assert ns.tone == ""

    def test_parse_fiction_extras(self):
        """Fiction flavor has stakes, relationships, foreshadowing."""
        raw = yaml.dump({
            "characters": [
                {"name": "Aris", "state": "worried", "relationships": "estranged from Elena"},
            ],
            "plot_threads": [
                {"description": "Missing gold", "status": "open", "foreshadowing": "Aris dream in ch1"},
            ],
            "stakes": [
                {"character": "Aris", "stands_to": "lose everything if gold runs out"},
            ],
        })
        ns = NarrativeState.from_yaml(raw)
        assert ns.characters[0]["relationships"] == "estranged from Elena"
        assert ns.plot_threads[0]["foreshadowing"] == "Aris dream in ch1"
        assert len(ns.extra.get("stakes", [])) == 1


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


class TestMergeNarrativeState:
    """Test merging multiple NarrativeState objects."""

    def test_merge_two(self):
        ns1 = NarrativeState(
            characters=[{"name": "Aris", "state": "curious"}],
            plot_threads=[{"description": "Anomaly", "status": "open"}],
            world_rules=["Gold depleted"],
            tone="tense",
            key_events=["Discovery"],
        )
        ns2 = NarrativeState(
            characters=[{"name": "Aris", "state": "suspicious"}, {"name": "Elena", "state": "missing"}],
            plot_threads=[
                {"description": "Anomaly", "status": "open", "tension": "high"},
                {"description": "Elena disappearance", "status": "open"},
            ],
            world_rules=["Gold depleted", "Time travel needs 3.2s"],
            tone="tense, paranoid",
            key_events=["Aris found pattern", "Elena vanished"],
        )
        merged = NarrativeState.merge([ns1, ns2])
        # Characters: last write wins for same name
        assert len(merged.characters) == 2
        aris = next(c for c in merged.characters if c["name"] == "Aris")
        assert aris["state"] == "suspicious"  # ns2 overwrites ns1
        # Plot threads: deduplicated by description
        assert len(merged.plot_threads) == 2
        # World rules: deduplicated
        assert len(merged.world_rules) == 2
        # Key events: accumulated
        assert len(merged.key_events) == 3
        # Tone: last wins
        assert merged.tone == "tense, paranoid"

    def test_merge_empty_list(self):
        merged = NarrativeState.merge([])
        assert merged.characters == []

    def test_merge_single(self):
        ns = NarrativeState(characters=[{"name": "Aris"}], tone="tense")
        merged = NarrativeState.merge([ns])
        assert merged.characters == ns.characters
        assert merged.tone == "tense"

    def test_merge_preserves_extra(self):
        """Extra fields (like stakes) are merged too."""
        ns1 = NarrativeState(extra={"stakes": [{"character": "Aris", "stands_to": "lose lab"}]})
        ns2 = NarrativeState(extra={"stakes": [{"character": "Elena", "stands_to": "lose freedom"}]})
        merged = NarrativeState.merge([ns1, ns2])
        assert len(merged.extra["stakes"]) == 2


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerializeNarrativeState:
    """Test converting NarrativeState back to YAML."""

    def test_to_yaml(self):
        ns = NarrativeState(
            characters=[{"name": "Aris", "state": "suspicious"}],
            plot_threads=[{"description": "Anomaly", "status": "open"}],
            world_rules=["Gold depleted"],
            tone="tense",
            key_events=["Discovery"],
        )
        output = ns.to_yaml()
        parsed = yaml.safe_load(output)
        assert parsed["characters"][0]["name"] == "Aris"
        assert parsed["tone"] == "tense"

    def test_roundtrip(self):
        """Parse → serialize → parse produces same data."""
        original = {
            "characters": [{"name": "Aris", "state": "curious", "location": "lab"}],
            "plot_threads": [{"description": "Anomaly", "status": "open", "tension": "high"}],
            "world_rules": ["Gold depleted"],
            "tone": "tense",
            "key_events": ["Discovery"],
        }
        ns1 = NarrativeState.from_yaml(yaml.dump(original))
        output = ns1.to_yaml()
        ns2 = NarrativeState.from_yaml(output)
        assert ns1.characters == ns2.characters
        assert ns1.plot_threads == ns2.plot_threads
        assert ns1.world_rules == ns2.world_rules
        assert ns1.tone == ns2.tone

    def test_to_yaml_empty(self):
        ns = NarrativeState()
        output = ns.to_yaml()
        parsed = yaml.safe_load(output)
        assert parsed["characters"] == []
        assert parsed["tone"] == ""
