"""LLM Client — OpenAI-compatible API client for agent calls.

Works with any provider that exposes an OpenAI-compatible endpoint:
- OpenAI (api.openai.com)
- Anthropic (via proxy or compatible endpoint)
- Local (ollama, vLLM, llama.cpp server)
- Custom endpoints
"""

from __future__ import annotations

import logging
import time
import litellm
from typing import Any

from .timeit import log_timing
from .logging_config import get_logger

logger = logging.getLogger(__name__)
_common_log = get_logger("llm")


class LLMClient:
    """Simple OpenAI-compatible chat completion client using LiteLLM."""

    def __init__(self, api_base: str, api_key: str, model: str,
                 temperature: float = 0.7, max_tokens: int = 4096):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(self, system: str, user: str, temperature: float | None = None,
             max_tokens: int | None = None, response_format: dict | None = None,
             piece_id: str | None = None, stage: str | None = None,
             call_type: str | None = None, trace_id: str | None = None) -> str:
        """Send a chat completion request.

        Args:
            system: System prompt.
            user: User message.
            temperature: Override default temperature.
            max_tokens: Override default max_tokens.
            response_format: OpenAI-compatible response format.
            piece_id: The document node ID.
            stage: The pipeline stage calling this LLM.
            call_type: The type of execution call.
            trace_id: ID tracing the current execution run.

        Returns:
            The assistant's response text.

        Raises:
            ConnectionError: If the API call fails.
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        
        # If the model provider is unknown to LiteLLM, default to openai/ prefix
        # so it routes to the custom OpenAI-compatible api_base endpoint.
        model_name = self.model
        try:
            litellm.get_llm_provider(model_name)
        except Exception:
            if self.api_base:
                model_name = f"openai/{model_name}"

        t0 = time.monotonic()
        try:
            response = litellm.completion(
                model=model_name,
                messages=messages,
                api_base=self.api_base,
                api_key=self.api_key or "dummy",
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                response_format=response_format,
                num_retries=3,
            )
            elapsed = time.monotonic() - t0
            content = response.choices[0].message.content or ""
            
            input_chars = len(system) + len(user)
            log_timing(f"llm.chat ({self.model}, {input_chars} chars in, {len(content)} chars out)", elapsed)

            # Log to appropriate logger
            log_msg = f"LLM call: model={self.model}, in={input_chars} chars, out={len(content)} chars, elapsed={elapsed:.1f}s"
            if piece_id:
                from .logging_config import get_piece_logger
                get_piece_logger("llm", piece_id).info(log_msg)
            else:
                _common_log.info(log_msg)

            # Audit tokens and cost, then log to Database AgentLog
            try:
                from .db import SessionLocal
                from .models import DocumentNode, AgentLog
                
                project_id = None
                if piece_id:
                    with SessionLocal() as db:
                        node = db.query(DocumentNode).filter_by(id=piece_id).first()
                        if node:
                            project_id = node.project_id

                prompt_tokens = 0
                completion_tokens = 0
                cost = 0.0
                usage = getattr(response, "usage", None)
                if usage:
                    prompt_tokens = getattr(usage, "prompt_tokens", 0)
                    completion_tokens = getattr(usage, "completion_tokens", 0)
                cost = litellm.completion_cost(completion_response=response) or 0.0

                with SessionLocal() as db:
                    agent_log = AgentLog(
                        project_id=project_id,
                        document_node_id=piece_id,
                        stage=stage or "unknown",
                        call_type=call_type or "generate",
                        model=self.model,
                        system_prompt=system,
                        user_prompt=user,
                        system_chars=len(system),
                        user_chars=len(user),
                        trace_id=trace_id,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cost=cost,
                        output=content,
                    )
                    db.add(agent_log)
                    db.commit()
            except Exception as db_err:
                logger.error("Failed to write database AgentLog: %s", db_err, exc_info=True)

            return content
        except Exception as e:
            raise ConnectionError(f"LLM connection/API error: {e}") from e
