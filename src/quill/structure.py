"""Structure stage — segment calculation for automated content segmentation.

Calculates segment count and style based on target_length.
Used by the structure stage prompt templates to generate segment titles.
"""

from __future__ import annotations

import math
import re


def parse_target_length(target_length: str | None) -> int | None:
    """Parse target_length string into a word count integer.

    Handles formats like:
    - "5000" → 5000
    - "5000-8000 words" → 6500 (midpoint)
    - "5000 words" → 5000
    - "" or None → None
    """
    if not target_length:
        return None
    # Extract all numbers from the string
    numbers = re.findall(r"\d+", str(target_length))
    if not numbers:
        return None
    if len(numbers) >= 2:
        # Range like "5000-8000" → midpoint
        return (int(numbers[0]) + int(numbers[1])) // 2
    return int(numbers[0])


def calculate_segments(target_length: int | None) -> dict:
    """Calculate segment parameters from target word count.

    Args:
        target_length: Target word count for the piece. None/0 defaults to 2000.

    Returns:
        dict with keys: count, style, name, target
        - count: number of segments
        - style: "chapters" or "paragraphs"
        - name: human-readable segment name (same as style)
        - target: target words per segment
    """
    length = target_length if target_length and target_length > 0 else 2000

    if length >= 2000:
        style = "chapters"
        segment_target = 2000
    else:
        style = "paragraphs"
        segment_target = 300

    count = max(1, math.ceil(length / segment_target))

    return {
        "count": count,
        "style": style,
        "name": style,
        "target": segment_target,
    }
