"""Tests for structure stage — segment calculation and pipeline routing."""

import pytest
from pathlib import Path

from quill.pipeline import load_pipeline


# ---------------------------------------------------------------------------
# Segment calculation
# ---------------------------------------------------------------------------


class TestParseTargetLength:
    """Test target_length string parsing."""

    def test_plain_number(self):
        from quill.structure import parse_target_length
        assert parse_target_length("5000") == 5000

    def test_range_format(self):
        from quill.structure import parse_target_length
        assert parse_target_length("5000-8000 words") == 6500

    def test_number_with_words(self):
        from quill.structure import parse_target_length
        assert parse_target_length("3000 words") == 3000

    def test_empty_string(self):
        from quill.structure import parse_target_length
        assert parse_target_length("") is None

    def test_none(self):
        from quill.structure import parse_target_length
        assert parse_target_length(None) is None

    def test_no_numbers(self):
        from quill.structure import parse_target_length
        assert parse_target_length("long") is None

    def test_bulgarian_format(self):
        from quill.structure import parse_target_length
        assert parse_target_length("5000-8000 думи") == 6500


class TestCalculateSegments:
    """Test the segment calculation logic."""

    def test_short_content_paragraphs(self):
        """Under 2000 words → paragraphs style, ~300 words each."""
        from quill.structure import calculate_segments
        result = calculate_segments(1500)
        assert result["style"] == "paragraphs"
        assert result["name"] == "paragraphs"
        assert result["count"] == 5  # ceil(1500/300)
        assert result["target"] == 300

    def test_long_content_chapters(self):
        """Over 2000 words → chapters style, ~2000 words each."""
        from quill.structure import calculate_segments
        result = calculate_segments(8000)
        assert result["style"] == "chapters"
        assert result["name"] == "chapters"
        assert result["count"] == 4  # ceil(8000/2000)
        assert result["target"] == 2000

    def test_boundary_2000_words(self):
        """Exactly 2000 words → chapters."""
        from quill.structure import calculate_segments
        result = calculate_segments(2000)
        assert result["style"] == "chapters"
        assert result["count"] == 1

    def test_boundary_1999_words(self):
        """1999 words → paragraphs."""
        from quill.structure import calculate_segments
        result = calculate_segments(1999)
        assert result["style"] == "paragraphs"

    def test_very_short_content(self):
        """Very short content still gets at least 1 segment."""
        from quill.structure import calculate_segments
        result = calculate_segments(100)
        assert result["count"] == 1
        assert result["style"] == "paragraphs"

    def test_10k_novel(self):
        """10k word novel → 5 chapters."""
        from quill.structure import calculate_segments
        result = calculate_segments(10000)
        assert result["style"] == "chapters"
        assert result["count"] == 5
        assert result["target"] == 2000

    def test_missing_target_length(self):
        """Missing target_length defaults to 2000."""
        from quill.structure import calculate_segments
        result = calculate_segments(None)
        assert result["style"] == "chapters"
        assert result["count"] == 1

    def test_zero_target_length(self):
        """Zero target_length defaults to 2000."""
        from quill.structure import calculate_segments
        result = calculate_segments(0)
        assert result["style"] == "chapters"
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# Pipeline routing
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline():
    return load_pipeline("default")


class TestStructurePipeline:
    """Test structure stage in the pipeline."""

    def test_structure_stage_exists(self, pipeline):
        stage = pipeline.get_stage("structure")
        assert stage is not None
        assert stage.name == "Structure"

    def test_structure_is_content_stage(self, pipeline):
        assert pipeline.is_content_stage("structure") is True

    def test_brief_next_is_structure(self, pipeline):
        assert pipeline.next_stage("brief") == "structure"

    def test_structure_next_is_outline(self, pipeline):
        assert pipeline.next_stage("structure") == "outline"

    def test_structure_can_reject_to_brief(self, pipeline):
        assert pipeline.can_reject_to("structure", "brief") is True

    def test_outline_can_reject_to_structure(self, pipeline):
        """Outline should be able to reject back to structure."""
        assert pipeline.can_reject_to("outline", "structure") is True

    def test_stage_order_with_structure(self, pipeline):
        expected = ["brief", "structure", "outline", "research", "draft",
                     "review", "revise", "humanize", "validate", "polish",
                     "state", "done"]
        assert pipeline.stage_order == expected

    def test_stage_count_with_structure(self, pipeline):
        assert len(pipeline.stages) == 12

    def test_structure_stage_inputs(self, pipeline):
        assert "structure" in pipeline.stage_inputs
        assert "brief.md" in pipeline.stage_inputs["structure"]
