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
import urllib.request
import urllib.error
from typing import Any

logger = logging.getLogger(__name__)


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
             max_tokens: int | None = None) -> str:
        """Send a chat completion request.

        Args:
            system: System prompt.
            user: User message.
            temperature: Override default temperature.
            max_tokens: Override default max_tokens.

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

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise ConnectionError(f"LLM API error {e.code}: {error_body}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(f"LLM connection error: {e.reason}") from e
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise ConnectionError(f"LLM response parse error: {e}") from e
