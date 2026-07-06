# Spec: LiteLLM Integration and Token Auditing

## Goal
Replace the custom `urllib` client in `src/quill/llm.py` with `litellm` to gain advanced provider routing, built-in retry backoffs, and token usage/cost auditing, then log these details to the `AgentLog` database table.

## Architecture & Integration

### 1. Dependency Management
- Add `litellm>=1.0.0` dependency to `pyproject.toml` under `dependencies`.

### 2. Refactoring LLMClient (`src/quill/llm.py`)
- Import `litellm`.
- Modify `LLMClient.chat()` signature to include optional logging metadata:
  ```python
  def chat(
      self,
      system: str,
      user: str,
      temperature: float | None = None,
      max_tokens: int | None = None,
      response_format: dict | None = None,
      piece_id: str | None = None,
      stage: str | None = None,
      call_type: str | None = None,
      trace_id: str | None = None,
  ) -> str:
  ```
- Use `litellm.completion` to invoke the LLM.
- Forward arguments: `model`, `messages`, `api_base`, `api_key`, `temperature`, `max_tokens`, `response_format`.
- Configure `num_retries=3` on `litellm.completion` to automatically handle rate limits and transient connection issues with backoff.
- Wrap LiteLLM/OpenAI exception classes (e.g., `RateLimitError`, `APIConnectionError`, `APIError`) and raise them as `ConnectionError` to maintain backward compatibility with callers.
- Resolve the parent `project_id` using the database if `piece_id` is provided (since `piece_id` is the `DocumentNode.id`).
- Extract prompt and completion token counts from the response object, and calculate total model completion cost using `litellm.completion_cost()`.
- Use a dedicated, short-lived database session context (using `SessionLocal()` from `src/quill/db.py`) to create and commit an `AgentLog` record, avoiding premature commits or database session contamination.

### 3. Updating Stage Runner (`src/quill/stage_runner.py`)
Update all `client.chat` invocations to supply extra context:
- Single-call generation:
  `stage=stage`, `call_type="generate"`, `trace_id=trace_id`
- Feedback execution:
  `stage=stage`, `call_type="agent"`, `trace_id=trace_id`
- Output evaluation:
  `stage=stage`, `call_type="evaluate"`, `trace_id=trace_id`
- Multi-chapter generation:
  `stage=stage`, `call_type="generate"`, `trace_id=trace_id`

## Verification Plan
- Verify that `litellm` works with mock API responses and raises wrapped connection exceptions.
- Add unit tests for `LLMClient` to ensure `AgentLog` entries are correctly created in the database and contain correct tokens, costs, and content lengths.
- Verify rate limiting and timeout retries trigger backoffs appropriately.
