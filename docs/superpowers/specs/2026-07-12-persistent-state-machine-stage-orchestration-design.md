# Design Spec: Persistent State-Based Stage Orchestration

Transition the stage orchestration from procedural blocking loops to a robust, database-backed persistent state machine. This enables sequential chapter execution with sliding context, reliable recovery from worker crashes, and clean human-in-the-loop pausing.

## Proposed Changes

### [models.py](file:///home/bob/projects/quill/src/quill/models.py)

Modify `StageState` to act as a historical and generic record of stage executions:
* Replace `body`, `decision`, and `critique` fields with a single generic `output_text` field.
* Add generic input fields: `prompt_template_path` (reference to prompt source), `system_prompt` (final compiled system prompt), and `user_prompt` (final compiled user prompt with all variable substitutions).
* Simplify the `status` enum to: `new`, `processing`, `completed`, `failed`.
* Remove the `superseded` state value from status. Instead, add a boolean `is_active` flag (set to `False` when a stage is rolled back or re-run) and an `iteration` counter.

### [engine.py](file:///home/bob/projects/quill/src/quill/engine.py) [NEW]

Create a stateless workflow manager class `WorkflowEngine`:
* Expose `evaluate_and_dispatch(session, node_id, completed_stage)` to determine the next step in the pipeline.
* Implement sequential step evaluation for parent-child node relationships (capping the hierarchy at 3 levels max: Project -> Chapter -> Scene).
* Implement sliding context assembly by fetching previous chapter outputs ($N-1$), NarrativeState summaries ($1 \dots N-2$), outline sketches ($N+1, N+2$), and parent briefs from the database.
* Delegate execution by enqueuing a Celery task with a coordinator callback URL argument.

### [blueprints/runs.py](file:///home/bob/projects/quill/src/quill/blueprints/runs.py)

Add a centralized coordination API endpoint:
* Add a `POST /api/workflow/callback` endpoint that workers hit on task completion/failure.
* This endpoint retrieves the request-scoped database session and delegates execution to the stateless singleton `workflow_engine.evaluate_and_dispatch(session, node_id, stage)`.

### [tasks.py](file:///home/bob/projects/quill/src/quill/tasks.py) (or [celery_app.py](file:///home/bob/projects/quill/src/quill/celery_app.py))

Refactor Celery task executions:
* Decouple tasks from the orchestration logic entirely.
* Tasks accept `piece_id`, `stage`, and a `callback_url`.
* Upon completion (or failure), the worker saves inputs/outputs to the database, commits the transaction, and sends a POST request to `callback_url` with the status.

---

## Verification Plan

### Automated Tests
* Create unit tests to verify stateless transition evaluations:
  * When a child node (Chapter 1) completes stage `S`, verify it enqueues a task for Chapter 2 with correct sliding context.
  * When the final child node (Chapter $N$) completes stage `S`, verify it triggers parent stage completion, concatenates outputs, and transitions parent state.
  * Verify that a failed stage execution can be resumed, restarting exactly from the failed chapter.
  * Verify that setting `is_active=False` preserves previous iteration history in the database.

### Manual Verification
* Run a multi-chapter test piece through the entire pipeline and verify execution progresses sequentially and logs database updates.
