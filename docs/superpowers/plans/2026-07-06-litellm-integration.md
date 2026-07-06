# LiteLLM Integration & AgentLog Auditing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the urllib client with LiteLLM in LLMClient, handle retries automatically, audit token usage and costs, and log them to the AgentLog table in the database using an isolated session context.

**Architecture:** We will add `litellm` as a project dependency, refactor `LLMClient.chat` to call `litellm.completion`, wrap OpenAI/LiteLLM exceptions to preserve backward compatibility, resolve `project_id` and write log entries using a separate, short-lived database session connection context, and update stage runner callers to supply the stage context.

**Tech Stack:** Python, LiteLLM, SQLAlchemy, Pytest.

## Global Constraints
- Target python version: >=3.10
- All modified code must adhere to existing PEP8 coding styles and keep method signatures backward-compatible.
- No database session leakage or transaction contamination (Approach A).

---

### Task 1: Project Dependency Configuration

**Files:**
- Modify: [pyproject.toml](file:///home/bob/projects/quill/pyproject.toml)

**Interfaces:**
- Consumes: None
- Produces: `litellm` package available in python virtual environment.

- [ ] **Step 1: Add litellm dependency**

Edit the `dependencies` list in [pyproject.toml](file:///home/bob/projects/quill/pyproject.toml#L6-L13):
```toml
dependencies = [
    "flask>=3.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "SQLAlchemy>=2.0",
    "flask-sqlalchemy>=3.0",
    "flask-migrate>=4.0",
    "litellm>=1.0.0",
]
```

- [ ] **Step 2: Install dependencies**

Run the installation command in terminal to update the virtual environment:
Run: `.venv/bin/pip install -e .`
Expected: Output showing successful installation of `litellm` and its dependencies.

- [ ] **Step 3: Verify litellm installation**

Run: `.venv/bin/python -c "import litellm; print(litellm.__version__)"`
Expected: Outputs the installed version number of litellm (e.g., `1.x.x`).

- [ ] **Step 4: Commit changes**

Run:
```bash
git add pyproject.toml
git commit -m "chore: add litellm dependency"
```

---

### Task 2: Refactor LLMClient to use LiteLLM

**Files:**
- Modify: [src/quill/llm.py](file:///home/bob/projects/quill/src/quill/llm.py)
- Create: [tests/test_llm_client.py](file:///home/bob/projects/quill/tests/test_llm_client.py)

**Interfaces:**
- Consumes: `litellm` package.
- Produces:
  `LLMClient.chat(self, system: str, user: str, temperature: float | None = None, max_tokens: int | None = None, response_format: dict | None = None, piece_id: str | None = None, stage: str | None = None, call_type: str | None = None, trace_id: str | None = None) -> str`

- [ ] **Step 1: Write unit tests for litellm wrapping and retries**

Create the test file [tests/test_llm_client.py](file:///home/bob/projects/quill/tests/test_llm_client.py) with the following content to verify that LiteLLM errors are caught and raised as `ConnectionError`:
```python
import pytest
from unittest.mock import patch
from quill.llm import LLMClient

def test_chat_connection_error_on_litellm_failure():
    client = LLMClient(api_base="http://localhost:1234/v1", api_key="test", model="test-model")
    
    with patch("litellm.completion") as mock_completion:
        from litellm.exceptions import APIConnectionError
        mock_completion.side_effect = APIConnectionError(
            message="Connection failed",
            model="test-model",
            llm_provider="openai"
        )
        with pytest.raises(ConnectionError) as exc_info:
            client.chat(system="Sys", user="User")
        assert "LLM connection/API error" in str(exc_info.value)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_llm_client.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'litellm'` or `ImportError` because `src/quill/llm.py` doesn't import `litellm` yet.

- [ ] **Step 3: Implement litellm.completion in LLMClient**

Modify [src/quill/llm.py](file:///home/bob/projects/quill/src/quill/llm.py) to replace `urllib` calls with `litellm.completion` and add signature updates:
```python
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
            call_type: The type of execution call (e.g. generate, agent, evaluate).
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
        
        t0 = time.monotonic()
        try:
            response = litellm.completion(
                model=self.model,
                messages=messages,
                api_base=self.api_base,
                api_key=self.api_key or None,
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

            return content
        except Exception as e:
            raise ConnectionError(f"LLM connection/API error: {e}") from e
```

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `.venv/bin/pytest tests/test_llm_client.py`
Expected: PASS

- [ ] **Step 5: Commit changes**

Run:
```bash
git add src/quill/llm.py tests/test_llm_client.py
git commit -m "feat: refactor LLMClient to use litellm"
```

---

### Task 3: Implement Database Logging (AgentLog)

**Files:**
- Modify: [src/quill/llm.py](file:///home/bob/projects/quill/src/quill/llm.py)
- Modify: [tests/test_llm_client.py](file:///home/bob/projects/quill/tests/test_llm_client.py)

**Interfaces:**
- Consumes: SQLAlchemy engine configurations from `src/quill/db.py` and `src/quill/models.py`.
- Produces: Writes to the database `agent_logs` table upon successful completion of `chat()`.

- [ ] **Step 1: Write database logging unit test**

Add the database logging test to [tests/test_llm_client.py](file:///home/bob/projects/quill/tests/test_llm_client.py):
```python
def test_chat_writes_agent_log_to_db(db_session):
    from quill.models import Project, DocumentNode, AgentLog
    
    project = Project(id="p-1", title="Test Project")
    node = DocumentNode(id="n-1", project_id="p-1", title="Test Node")
    db_session.add_all([project, node])
    db_session.commit()
    
    client = LLMClient(api_base="http://localhost:1234/v1", api_key="test", model="test-model")
    
    class MockUsage:
        prompt_tokens = 50
        completion_tokens = 25

    class MockMessage:
        content = "Generated text"

    class MockChoice:
        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]
        usage = MockUsage()
    
    with patch("litellm.completion", return_value=MockResponse()), \
         patch("litellm.completion_cost", return_value=0.0015):
        
        response = client.chat(
            system="Sys prompt",
            user="User prompt",
            piece_id="n-1",
            stage="draft",
            call_type="generate",
            trace_id="tr-999"
        )
        
        assert response == "Generated text"
        
        # Retrieve written AgentLog
        logs = db_session.query(AgentLog).filter_by(trace_id="tr-999").all()
        assert len(logs) == 1
        log = logs[0]
        assert log.project_id == "p-1"
        assert log.document_node_id == "n-1"
        assert log.stage == "draft"
        assert log.call_type == "generate"
        assert log.system_prompt == "Sys prompt"
        assert log.user_prompt == "User prompt"
        assert log.prompt_tokens == 50
        assert log.completion_tokens == 25
        assert log.cost == 0.0015
        assert log.output == "Generated text"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_llm_client.py`
Expected: FAIL on `test_chat_writes_agent_log_to_db` (AssertionError: `len(logs) == 1` fails, actual `0`).

- [ ] **Step 3: Implement database auditing and logging in `LLMClient.chat`**

Edit [src/quill/llm.py](file:///home/bob/projects/quill/src/quill/llm.py) to add the logging implementation:
```python
        t0 = time.monotonic()
        try:
            response = litellm.completion(
                model=self.model,
                messages=messages,
                api_base=self.api_base,
                api_key=self.api_key or None,
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
                        system_chars=input_chars - len(user), # len(system)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_llm_client.py`
Expected: PASS

- [ ] **Step 5: Commit changes**

Run:
```bash
git add src/quill/llm.py tests/test_llm_client.py
git commit -m "feat: add AgentLog database auditing to LLMClient"
```

---

### Task 4: Forward Context Parameters from Stage Runner

**Files:**
- Modify: [src/quill/stage_runner.py](file:///home/bob/projects/quill/src/quill/stage_runner.py)

**Interfaces:**
- Consumes: Updated `LLMClient.chat()` signature.
- Produces: Updates calls to forward `stage`, `call_type`, and `trace_id`.

- [ ] **Step 1: Modify client.chat calls in stage_runner.py**

Modify the calls to `client.chat` in [src/quill/stage_runner.py](file:///home/bob/projects/quill/src/quill/stage_runner.py):

Around line 120 (Standard single-call generation):
```python
                generated = client.chat(
                    gen_system,
                    prompt_for_generate,
                    piece_id=piece.id,
                    stage=stage,
                    call_type="generate",
                    trace_id=trace_id,
                )
```

Around line 168 (run_feedback_stage):
```python
            response = client.chat(
                eval_system,
                prompt_for_feedback,
                response_format=response_format,
                piece_id=piece.id,
                stage=stage,
                call_type="agent",
                trace_id=trace_id,
            )
```

Around line 266 (evaluate_output):
```python
            eval_response = client.chat(
                eval_system,
                eval_prompt,
                response_format=response_format,
                piece_id=piece.id,
                stage=stage,
                call_type="evaluate",
                trace_id=trace_id,
            )
```

Around line 441 (_generate_chaptered):
```python
                chapter_text = client.chat(
                    gen_system,
                    chapter_prompt,
                    piece_id=piece.id,
                    stage=stage,
                    call_type=f"generate_ch{ch_num}",
                    trace_id=trace_id,
                )
```

- [ ] **Step 2: Run all runner and models tests to verify integration**

Run: `.venv/bin/pytest tests/test_runner.py tests/test_models.py`
Expected: PASS

- [ ] **Step 3: Commit changes**

Run:
```bash
git add src/quill/stage_runner.py
git commit -m "feat: forward context params to LLMClient from stage runner"
```
