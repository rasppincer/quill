# Decision Stages and Version-Preserved Loopbacks

We are transitioning the Quill workflow engine to support a clean, automated loopback system Driven by **Approach 1 (Schema-driven Decision Stages)**. This decouples revision logic from internal loops, allows distinct review and post-review decision stages, and preserves all versions of files on the disk for diagnostics.

---

## User Review Required

> [!IMPORTANT]
> **Loop Versioning**: All loop runs (where `loop_count > 0`) will write versioned files (`.L1.md`, `.L2.md`, etc.) to the filesystem instead of overwriting the base file. The database records will store the latest loop version.
> **No Auto-Reset on Reverts**: Standard `supersede_from` (which purges subsequent stages) will **not** be called during automated loops. Work is fully preserved.

---

## Proposed Changes

### Core Workflow Definitions
#### [MODIFY] [default.yaml](file:///home/bob/projects/quill/workflows/default.yaml)
* Update stage order and transitions to add `review_decision` (between `review` and `revise`) and `validate_decision` (between `validate` and `polish`).
* Define `mode: decision` for the new stages.
* Map transitions under `next` as dictionary lookups for decisions:
  ```yaml
  - key: review_decision
    mode: decision
    next:
      advance: humanize
      reject: revise
  ```
* Route `revise` back to `review` and `polish` back to `validate`.

---

### Pipeline Engine
#### [MODIFY] [pipeline.py](file:///home/bob/projects/quill/src/quill/pipeline.py)
* Update [Pipeline.next_stage](file:///home/bob/projects/quill/src/quill/pipeline.py#L50) to accept an optional `decision` argument:
  ```python
  def next_stage(self, current: str, decision: str | None = None) -> str | None:
  ```
* Resolve string values directly, and lookup dictionary keys using the passed `decision`.

#### [MODIFY] [piece.py](file:///home/bob/projects/quill/src/quill/piece.py)
* Update `Piece.stage_file` to support suffixing versioned files:
  ```python
  suffix = f".L{loop_count}" if loop_count > 0 else ""
  ```
* Update transition logic so that automated loops update `current_stage` directly without invoking clearing/purging operations.

#### [MODIFY] [context_assembler.py](file:///home/bob/projects/quill/src/quill/context_assembler.py)
* Update `ContextAssembler.read_inputs` to dynamically check the loop index and map the correct file inputs for the loop stages:
  * `review`: load `draft.md` on loop 0, and `revise.LN.md` on loop `N > 0`.
  * `revise`: load `draft.md` + `review.md` on loop 1, and `revise.L{N-1}.md` + `review.L{N-1}.md` on loop `N > 1`.
  * Same dynamic mapping for `validate` and `polish` stages.

---

### Prompts and LLM Caller
#### [MODIFY] [prompt_builder.py](file:///home/bob/projects/quill/src/quill/prompt_builder.py)
* Update `PromptBuilder.system_prompt` signature to accept `use_structured` and generate dynamic formatting instructions for `call_type == "decision"` depending on structured output availability.

#### [MODIFY] [stage_runner.py](file:///home/bob/projects/quill/src/quill/stage_runner.py)
* Define Pydantic model `DecisionStageOutput` with `decision` (string) and `reason` (string) fields.
* Implement helper `extract_json(text: str) -> str` to strip markdown fences and outer wrappers from local LLM responses.
* Enforce schema parsing in `LLMCaller.run_stage` for the `decision` stage mode.

#### [NEW] [review_decision.prompt.md](file:///home/bob/projects/quill/agents/default/review_decision.prompt.md)
* Create generic review decision prompt instructing the model to evaluate critique satisfaction.

#### [NEW] [validate_decision.prompt.md](file:///home/bob/projects/quill/agents/default/validate_decision.prompt.md)
* Create generic validation decision prompt.

*(Similar templates will be generated under `agents/fiction/` and `agents/non-fiction/`.)*

---

### Runner and Orchestrator
#### [MODIFY] [runner.py](file:///home/bob/projects/quill/src/quill/runner.py)
* Update `auto_advance` evaluation to only trigger if the piece's overall setting is `auto`:
  ```python
  auto_advance = force_advance or piece.trigger == "auto"
  ```
* Handle execution of `"decision"` mode stages, checking loop count bounds before making LLM calls, and bypassing if loop counts exceed the limit.

#### [MODIFY] [chain_orchestrator.py](file:///home/bob/projects/quill/src/quill/chain_orchestrator.py)
* Integrate decision transitions: extract the returned decision from the runner output and query `pipeline.next_stage(current, decision)`.
* Track and increment loop counts for the current loop group on `reject` decisions.

---

## Verification Plan

### Automated Tests
* Run unit tests to verify:
  * Transition resolution for simple and decision-based next stages:
    `.venv/bin/pytest tests/test_pipeline.py`
  * Dynamic context input assembly with different loop counts:
    `.venv/bin/pytest tests/test_runner.py`
  * Decision-stage parsing and loop count boundaries:
    `.venv/bin/pytest tests/test_async.py`

### Manual Verification
* Start a non-fiction piece run in `auto` mode, and check `run-log.jsonl` and output files on disk to confirm that the loop is executed, loop counts increment, files are correctly suffixed (`.L1.md`, etc.), and execution proceeds to the end of the pipeline.
