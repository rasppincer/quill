"""LLM Client — OpenAI-compatible API client for agent calls.

Works with any provider that exposes an OpenAI-compatible endpoint:
- OpenAI (api.openai.com)
- Anthropic (via proxy or compatible endpoint)
- Local (ollama, vLLM, llama.cpp server)
- Custom endpoints
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error
from typing import Any

from .timeit import log_timing
from .logging_config import get_logger

logger = logging.getLogger(__name__)
_common_log = get_logger("llm")


class LLMClient:
    """Simple OpenAI-compatible chat completion client."""

    def __init__(self, api_base: str, api_key: str, model: str,
                 temperature: float = 0.7, max_tokens: int = 4096):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(self, system: str, user: str, temperature: float | None = None,
             max_tokens: int | None = None, response_format: dict | None = None,
             piece_id: str | None = None) -> str:
        """Send a chat completion request.

        Args:
            system: System prompt.
            user: User message.
            temperature: Override default temperature.
            max_tokens: Override default max_tokens.
            response_format: OpenAI-compatible response format, e.g.
                {"type": "json_object"} for guaranteed JSON output.

        Returns:
            The assistant's response text.

        Raises:
            ConnectionError: If the API call fails.
        """
        url = f"{self.api_base}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        input_chars = len(system) + len(user)
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                elapsed = time.monotonic() - t0
                content = body["choices"][0]["message"]["content"]
                log_timing(f"llm.chat ({self.model}, {input_chars} chars in, {len(content)} chars out)", elapsed)

                # Log to appropriate logger
                log_msg = f"LLM call: model={self.model}, in={input_chars} chars, out={len(content)} chars, elapsed={elapsed:.1f}s"
                if piece_id:
                    from .logging_config import get_piece_logger
                    get_piece_logger("llm", piece_id).info(log_msg)
                else:
                    _common_log.info(log_msg)

                return content
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise ConnectionError(f"LLM API error {e.code}: {error_body}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(f"LLM connection error: {e.reason}") from e
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise ConnectionError(f"LLM response parse error: {e}") from e
