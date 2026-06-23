"""Token budget checking for LLM calls.

Provides utilities to estimate token counts using a word-count heuristic
and check/truncate input content before LLM calls to stay within context
window limits.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Word-to-token heuristic: 1 word ≈ 1.3 tokens for English text.
_WORDS_TO_TOKENS = 1.3


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in *text* using a word-count heuristic.

    Uses the rule of thumb that 1 English word ≈ 1.3 tokens.
    """
    words = len(text.split())
    return max(1, int(words * _WORDS_TO_TOKENS))


def check_and_truncate(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    context_window: int = 32000,
    threshold: float = 0.8,
) -> tuple[str, bool]:
    """Check if *system_prompt* + *user_prompt* fit within the context budget.

    If ``estimated_input_tokens + max_tokens`` exceeds ``threshold * context_window``,
    the *user_prompt* is truncated to fit.  The system prompt is never truncated.

    Args:
        system_prompt: The system prompt (included in input estimation).
        user_prompt: The user prompt (may be truncated).
        max_tokens: The max_tokens setting for the LLM response.
        context_window: Total context window size (default 32000).
        threshold: Fraction of context_window usable for input + output (default 0.8).

    Returns:
        ``(possibly_truncated_user_prompt, was_truncated)``
    """
    budget = int(context_window * threshold)
    available_for_input = budget - max_tokens
    if available_for_input <= 0:
        logger.warning(
            "Token budget: max_tokens (%d) exceeds %d%% of context window (%d). "
            "No room for input.",
            max_tokens, int(threshold * 100), context_window,
        )
        return "", True

    input_text = system_prompt + "\n" + user_prompt
    estimated = estimate_tokens(input_text)

    if estimated <= available_for_input:
        return user_prompt, False

    # Need to truncate the user prompt.  Keep the system prompt intact.
    system_tokens = estimate_tokens(system_prompt)
    available_for_user = available_for_input - system_tokens
    if available_for_user <= 0:
        logger.warning(
            "Token budget: system prompt alone (%d est. tokens) exceeds available "
            "budget (%d tokens). Truncating user prompt entirely.",
            system_tokens, available_for_input,
        )
        return "", True

    # Convert available tokens back to approximate word count, then truncate.
    words_needed = int(available_for_user / _WORDS_TO_TOKENS)
    words = user_prompt.split()
    if words_needed >= len(words):
        return user_prompt, False

    truncated = " ".join(words[:words_needed])

    logger.warning(
        "Token budget exceeded: estimated %d input tokens + %d max_tokens > %d "
        "(%d%% of %d context window). Truncating user prompt from %d to ~%d words.",
        estimated, max_tokens, budget, int(threshold * 100), context_window,
        len(words), words_needed,
    )

    return truncated, True


def load_context_window(agent_set: str = "default") -> int:
    """Load the context_window setting from model.yaml.

    Returns the configured value or the default of 32000.
    """
    from .agent import load_model_config
    cfg = load_model_config()
    return cfg.get("context_window", 32000)
