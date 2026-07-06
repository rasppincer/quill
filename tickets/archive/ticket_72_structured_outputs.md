# Ticket 72: Transition to Pydantic Structured Outputs (Guaranteed JSON)

## Description
Leverage schema-guaranteed JSON outputs by integrating Pydantic schemas into agent evaluation/feedback stages.

## Background
Current JSON parsing is fragile, relying on `_strip_json_block` and regex parsing if the LLM fails to return clean JSON. Modern APIs support structured JSON outputs via schema validation, ensuring 100% valid JSON matching a Pydantic model.

## Tasks
- [x] Define Pydantic models for `AgentEvaluation` (contains `decision` as Enum of advance/loop_back, and `critique`).
- [x] Refactor `src/quill/agent.py` to pass the Pydantic schema in the LLM call using LiteLLM.
- [x] Remove `parse_agent_response` and heuristic regex fallbacks.
- [x] Update prompts to rely on structured outputs rather than instructional warning text.

## Success Criteria
- [x] All feedback and evaluate calls return guaranteed JSON matching the Pydantic schema.
- [x] JSON parsing errors are eliminated from the agent pipeline.

## Priority
High

---
**Next Expected Ticket Number**: 73
