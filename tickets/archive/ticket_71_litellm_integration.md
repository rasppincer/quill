# Ticket 71: Integrate LiteLLM/Universal Gateway Client

## Description
Replace the custom `urllib` client in `src/quill/llm.py` with LiteLLM to provide advanced provider routing, error handling, retries, and token auditing.

## Background
The current LLM client is built on standard `urllib` to eliminate external dependencies. However, this limits us when managing rate limits, fallback models, and token cost tracking.

## Tasks
- [ ] Add `litellm` dependency to `pyproject.toml`.
- [ ] Refactor `src/quill/llm.py` to use `litellm.completion`.
- [ ] Configure standard retry backoffs for API rate limits and network timeouts.
- [ ] Update LLMClient to audit token usage (input/output/cost) and log it into the `AgentLog` table.

## Success Criteria
- [ ] OpenAI-compatible models, local llama.cpp, and other providers route correctly via LiteLLM.
- [ ] Unit and integration tests verify that network/rate-limiting errors trigger automatic backoff retries.

## Priority
Medium

---
**Next Expected Ticket Number**: 72
