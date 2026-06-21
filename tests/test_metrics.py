"""Tests for metrics.py — text readability and style scoring."""

import pytest
from pathlib import Path

import yaml

from quill.metrics import (
    compute_metrics,
    count_syllables,
    split_sentences,
    count_passive_voice,
    metrics_path_for,
    needs_update,
    load_metrics,
    save_metrics,
    compute_and_save,
    maybe_recompute,
)


# ---------------------------------------------------------------------------
# Syllable counting
# ---------------------------------------------------------------------------


class TestSyllableCount:
    def test_simple_words(self):
        assert count_syllables("cat") == 1
        assert count_syllables("dog") == 1
        assert count_syllables("the") == 1

    def test_multisyllable(self):
        assert count_syllables("hello") == 2
        assert count_syllables("beautiful") == 3
        assert count_syllables("university") >= 4

    def test_silent_e(self):
        # "make" has 1 syllable (silent e)
        assert count_syllables("make") == 1
        # "the" has 1 syllable
        assert count_syllables("the") == 1

    def test_two_letter_words(self):
        assert count_syllables("is") == 1
        assert count_syllables("it") == 1

    def test_empty_string(self):
        assert count_syllables("") == 1  # minimum


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------


class TestSplitSentences:
    def test_simple_sentences(self):
        text = "Hello world. This is a test. Goodbye."
        sents = split_sentences(text)
        assert len(sents) == 3

    def test_exclamation_and_question(self):
        text = "Wow! Really? Yes."
        sents = split_sentences(text)
        assert len(sents) == 3

    def test_single_sentence(self):
        sents = split_sentences("Just one sentence here")
        assert len(sents) == 1

    def test_empty_text(self):
        assert split_sentences("") == []

    def test_very_short_fragments_filtered(self):
        """Fragments shorter than 3 chars are filtered."""
        sents = split_sentences("A. B. This is a real sentence.")
        # "A" and "B" are <= 2 chars, filtered
        assert len(sents) == 1


# ---------------------------------------------------------------------------
# Passive voice
# ---------------------------------------------------------------------------


class TestPassiveVoice:
    def test_detects_passive(self):
        sents = ["The book was written by the author."]
        assert count_passive_voice(sents) == 1

    def test_detects_active(self):
        sents = ["The author wrote the book."]
        assert count_passive_voice(sents) == 0

    def test_multiple_passive(self):
        sents = [
            "The cake was eaten.",
            "The letter was written by the secretary.",
            "She ran fast.",
        ]
        assert count_passive_voice(sents) == 2

    def test_various_be_verbs(self):
        for be in ["is", "are", "was", "were", "been", "being"]:
            sents = [f"The item {be} destroyed."]
            assert count_passive_voice(sents) == 1, f"'{be}' should trigger passive detection"


# ---------------------------------------------------------------------------
# Full metrics computation
# ---------------------------------------------------------------------------


class TestComputeMetrics:
    def test_empty_text(self):
        m = compute_metrics("")
        assert m["word_count"] == 0
        assert m["sentence_count"] == 0

    def test_simple_text(self):
        text = "The cat sat on the mat. The dog ran in the park. The bird flew over the tree."
        m = compute_metrics(text)
        assert m["word_count"] > 0
        assert m["sentence_count"] == 3
        assert m["flesch_ease"] > 0
        assert m["flesch_kincaid"] >= 0
        assert 0 < m["type_token_ratio"] <= 1
        assert 0 <= m["passive_voice_pct"] <= 100

    def test_complex_text_has_lower_flesch(self):
        simple = "The cat sat on the mat. The dog ran fast."
        complex_text = (
            "The implementation of the methodology was undertaken by the committee "
            "in order to facilitate the comprehensive evaluation of the organizational "
            "infrastructure and its subsequent operationalization within the framework."
        )
        simple_m = compute_metrics(simple)
        complex_m = compute_metrics(complex_text)
        # Simple text should be easier to read
        assert simple_m["flesch_ease"] > complex_m["flesch_ease"]

    def test_all_keys_present(self):
        m = compute_metrics("Some text here. Another sentence.")
        expected_keys = {
            "flesch_ease", "flesch_kincaid", "word_count", "sentence_count",
            "avg_sentence_length", "type_token_ratio", "passive_voice_pct",
        }
        assert set(m.keys()) == expected_keys

    def test_type_token_ratio_repetition(self):
        """Text with repeated words should have lower TTR."""
        varied = "The cat sat on a mat while dogs ran through parks and birds flew over trees."
        repeated = "the the the the cat cat cat sat sat on on on the the mat mat."
        varied_m = compute_metrics(varied)
        repeated_m = compute_metrics(repeated)
        assert varied_m["type_token_ratio"] > repeated_m["type_token_ratio"]


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


class TestMetricsFileOps:
    def test_metrics_path_for(self):
        assert metrics_path_for(Path("draft.md")) == Path("draft.metrics.yaml")
        assert metrics_path_for(Path("/foo/bar/review.md")) == Path("/foo/bar/review.metrics.yaml")

    def test_needs_update_no_metrics_file(self, tmp_path):
        stage = tmp_path / "draft.md"
        stage.write_text("content")
        assert needs_update(stage) is True

    def test_needs_update_metrics_older(self, tmp_path):
        stage = tmp_path / "draft.md"
        stage.write_text("content")
        metrics = tmp_path / "draft.metrics.yaml"
        metrics.write_text("word_count: 1")
        # Make stage file newer
        import time
        time.sleep(0.05)
        stage.write_text("updated content")
        assert needs_update(stage) is True

    def test_needs_update_metrics_current(self, tmp_path):
        stage = tmp_path / "draft.md"
        stage.write_text("content")
        metrics = tmp_path / "draft.metrics.yaml"
        metrics.write_text("word_count: 1")
        # Metrics file is newer or same age
        assert needs_update(stage) is False

    def test_save_and_load_metrics(self, tmp_path):
        stage = tmp_path / "draft.md"
        stage.write_text("test")
        metrics = {"flesch_ease": 75.0, "word_count": 100}
        save_metrics(stage, metrics)

        loaded = load_metrics(stage)
        assert loaded is not None
        assert loaded["flesch_ease"] == 75.0
        assert loaded["word_count"] == 100

    def test_load_metrics_missing(self, tmp_path):
        stage = tmp_path / "draft.md"
        stage.write_text("test")
        assert load_metrics(stage) is None

    def test_compute_and_save(self, tmp_path):
        stage = tmp_path / "draft.md"
        stage.write_text("---\nid: test\n---\n\nThe cat sat on the mat. The dog ran fast.")
        metrics = compute_and_save(stage)

        assert metrics["word_count"] > 0
        assert metrics["sentence_count"] == 2

        # Check file was saved
        mpath = tmp_path / "draft.metrics.yaml"
        assert mpath.exists()
        loaded = yaml.safe_load(mpath.read_text())
        assert loaded["word_count"] == metrics["word_count"]

    def test_maybe_recompute_computes_when_missing(self, tmp_path):
        stage = tmp_path / "draft.md"
        stage.write_text("---\nid: test\n---\n\nHello world. This is a test.")
        metrics = maybe_recompute(stage)
        assert metrics is not None
        assert metrics["word_count"] > 0

    def test_maybe_recompute_skips_when_current(self, tmp_path):
        stage = tmp_path / "draft.md"
        stage.write_text("content")
        save_metrics(stage, {"word_count": 42})
        # Should return cached value
        metrics = maybe_recompute(stage)
        assert metrics["word_count"] == 42

    def test_maybe_recompute_returns_none_for_missing_stage(self, tmp_path):
        stage = tmp_path / "nonexistent.md"
        assert maybe_recompute(stage) is None
