# TICK-003: Decision Stage Prompting & LLM Interface

## Goal
Create the prompts and infrastructure required to parse structured decisions from the LLM.

## Tasks
- [ ] **Prompt Creation**: 
    - Create `agents/default/review_decision.prompt.md` (evaluate critique satisfaction).
    - Create `agents/default/validate_decision.prompt.md` (evaluate validation satisfaction).
    - Generate equivalent templates under `agents/fiction/` and `agents/non-fiction/`.

- [ ] **Modify `src/quill/prompt_builder.py`**: 
    - Update `PromptBuilder.system_prompt` to accept `use_structured` and generate dynamic formatting instructions for `call_type == "decision"`.

- [ ] **Modify `src/quill/stage_runner.py`**: 
    - Define Pydantic model `DecisionStageOutput` with `decision` (string) and `reason` (string) fields.
    - Implement helper `extract_json(text: str)` to strip markdown fences and outer wrappers from LLM responses.
    - Enforce schema parsing in `LLMCaller.run_stage` for the `decision` stage mode.

## Acceptance Criteria
- Decision stages produce structured output (JSON) containing a decision and a reason.
- Prompt templates are present for all supported agent types.
