"""Text metrics — mechanical readability and style scores.

Computes per-stage metrics with no LLM calls. Results stored as
{stage}.metrics.yaml alongside each stage file.

Metrics:
    flesch_ease: Flesch Reading Ease (0-100, higher = easier)
    flesch_kincaid: Flesch-Kincaid Grade (US school grade level)
    word_count: Total words
    sentence_count: Total sentences
    avg_sentence_length: Words per sentence (avg)
    type_token_ratio: Unique words / total words (vocabulary diversity, 0-1)
    passive_voice_pct: Percentage of sentences with passive voice (0-100)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Passive voice pattern: be-verb + past participle
_PASSIVE_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|am)\s+\w+(?:ed|en)\b",
    re.IGNORECASE,
)

# Sentence splitting — on sentence-ending punctuation
_SENTENCE_RE = re.compile(r"[.!?]+(?:\s|$)")

# Word tokenization
_WORD_RE = re.compile(r"[a-zA-Z\u00C0-\u024F\u0400-\u04FF''\-]+")

# Vowel groups for syllable counting
_VOWEL_RE = re.compile(r"[aeiouy\u00E0-\u00F6\u00F8-\u00FE]+", re.IGNORECASE)


def count_syllables(word: str) -> int:
    """Estimate syllable count for a word."""
    word = word.lower().strip()
    if len(word) <= 2:
        return 1

    # Count vowel groups
    count = len(_VOWEL_RE.findall(word))

    # Silent e at end
    if word.endswith("e") and not word.endswith("le") and count > 1:
        count -= 1

    # Minimum 1 syllable
    return max(count, 1)


def split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    # Split on sentence-ending punctuation
    parts = _SENTENCE_RE.split(text)
    # Filter empty and very short fragments
    return [s.strip() for s in parts if len(s.strip()) > 2]


def count_passive_voice(sentences: list[str]) -> int:
    """Count sentences containing passive voice patterns."""
    return sum(1 for s in sentences if _PASSIVE_RE.search(s))


def compute_metrics(text: str) -> dict:
    """Compute all text metrics for a given text.

    Args:
        text: The full text content (no frontmatter).

    Returns:
        dict with all metric values.
    """
    if not text or not text.strip():
        return {
            "flesch_ease": 0,
            "flesch_kincaid": 0,
            "word_count": 0,
            "sentence_count": 0,
            "avg_sentence_length": 0.0,
            "type_token_ratio": 0.0,
            "passive_voice_pct": 0.0,
        }

    # Tokenize
    words = [w for w in _WORD_RE.findall(text) if len(w) > 0]
    word_count = len(words)

    # Sentences
    sentences = split_sentences(text)
    sentence_count = max(len(sentences), 1)

    # Syllables
    total_syllables = sum(count_syllables(w) for w in words)

    # Average sentence length
    avg_sentence_length = round(word_count / sentence_count, 1)

    # Type-token ratio (vocabulary diversity)
    unique_words = set(w.lower() for w in words)
    type_token_ratio = round(len(unique_words) / max(word_count, 1), 3)

    # Passive voice
    passive_count = count_passive_voice(sentences)
    passive_voice_pct = round((passive_count / sentence_count) * 100, 1)

    # Flesch Reading Ease: 206.835 - 1.015*(words/sentences) - 84.6*(syllables/words)
    flesch_ease = round(
        206.835 - 1.015 * (word_count / sentence_count) - 84.6 * (total_syllables / max(word_count, 1)),
        1,
    )
    # Clamp to reasonable range
    flesch_ease = max(0, min(100, flesch_ease))

    # Flesch-Kincaid Grade: 0.39*(words/sentences) + 11.8*(syllables/words) - 15.59
    flesch_kincaid = round(
        0.39 * (word_count / sentence_count) + 11.8 * (total_syllables / max(word_count, 1)) - 15.59,
        1,
    )
    flesch_kincaid = max(0, flesch_kincaid)

    return {
        "flesch_ease": flesch_ease,
        "flesch_kincaid": flesch_kincaid,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "avg_sentence_length": avg_sentence_length,
        "type_token_ratio": type_token_ratio,
        "passive_voice_pct": passive_voice_pct,
    }


def metrics_path_for(stage_path: Path) -> Path:
    """Get the metrics file path for a stage file.

    draft.md → draft.metrics.yaml
    """
    return stage_path.with_suffix(".metrics.yaml")


def needs_update(stage_path: Path) -> bool:
    """Check if metrics need recomputation.

    Returns True if:
    - metrics file doesn't exist, OR
    - stage file is newer than metrics file
    """
    mpath = metrics_path_for(stage_path)
    if not mpath.exists():
        return True
    return stage_path.stat().st_mtime > mpath.stat().st_mtime


def load_metrics(stage_path: Path) -> dict | None:
    """Load metrics for a stage file, or None if not computed yet."""
    mpath = metrics_path_for(stage_path)
    if not mpath.exists():
        return None
    try:
        return yaml.safe_load(mpath.read_text(encoding="utf-8")) or None
    except Exception:
        return None


def save_metrics(stage_path: Path, metrics: dict):
    """Save metrics alongside a stage file."""
    mpath = metrics_path_for(stage_path)
    mpath.write_text(
        yaml.dump(metrics, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    logger.info("Saved metrics to %s", mpath)


def compute_and_save(stage_path: Path) -> dict:
    """Compute metrics for a stage file and save them.

    Args:
        stage_path: Path to the stage .md file.

    Returns:
        The computed metrics dict.
    """
    from .piece import _FRONTMATTER_RE

    text = stage_path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text

    metrics = compute_metrics(body)
    save_metrics(stage_path, metrics)
    return metrics


def maybe_recompute(stage_path: Path) -> dict | None:
    """Recompute metrics only if the stage file has changed.

    Returns:
        Metrics dict (freshly computed or loaded from cache), or None if stage doesn't exist.
    """
    if not stage_path.exists():
        return None

    if needs_update(stage_path):
        return compute_and_save(stage_path)

    return load_metrics(stage_path)
