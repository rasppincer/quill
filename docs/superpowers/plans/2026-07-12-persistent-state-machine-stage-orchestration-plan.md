# Persistent State-Based Stage Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert stage orchestration into a database-backed, persistent workflow engine that processes chapters sequentially with sliding context, handles configurable revision loops, and uses callback endpoints for Celery task progression.

**Architecture:** We will replace procedural sequential loops in the worker and Flask blueprint with a stateless `WorkflowEngine` service. Celery tasks act as stateless execution units that write outputs to a modified `StageState` model and trigger transitions by pinging a callback endpoint.

**Tech Stack:** Python, Flask, Celery, SQLAlchemy, Alembic, pytest

## Global Constraints
* Keep the document nesting cap at 2 levels max: Project -> Chapter.
* Do not introduce new library dependencies for state machine graphs; use clean custom SQLAlchemy transition mapping.
* Maintain complete backward compatibility with existing tests by ensuring the SQLite test database creates the correct schema.

---

### Task 1: Update Database Model and Generate Alembic Migration

**Files:**
* Modify: `src/quill/models.py`
* Test: `tests/test_models.py`

**Interfaces:**
* Consumes: Existing DB models configuration.
* Produces: Updated database schema for `StageState` supporting inputs, generic outputs, iteration counters, and `is_active` flags.

- [ ] **Step 1: Write the failing test for the new StageState fields**
  Add the following test in `tests/test_models.py`:
  ```python
  def test_stage_state_persistent_fields(db_session):
      from quill.models import StageState
      state = StageState(
          document_node_id="test-project",
          stage="draft",
          iteration=2,
          is_active=True,
          status="processing",
          prompt_template_path="default/draft.prompt.md",
          system_prompt="system",
          user_prompt="user",
          output_text="output"
      )
      db_session.add(state)
      db_session.commit()
      
      saved = db_session.query(StageState).filter_by(document_node_id="test-project").first()
      assert saved.iteration == 2
      assert saved.is_active is True
      assert saved.status == "processing"
      assert saved.prompt_template_path == "default/draft.prompt.md"
      assert saved.system_prompt == "system"
      assert saved.user_prompt == "user"
      assert saved.output_text == "output"
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `.venv/bin/pytest tests/test_models.py -k test_stage_state_persistent_fields`
  Expected: Failure due to missing attributes/columns on `StageState`.

- [ ] **Step 3: Modify StageState schema in `src/quill/models.py`**
  Update the `StageState` class definition:
  ```python
  class StageState(Base):
      __tablename__ = "stage_states"

      id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
      document_node_id: Mapped[str] = mapped_column(
          String, ForeignKey("document_nodes.id", ondelete="CASCADE"), nullable=False
      )
      stage: Mapped[str] = mapped_column(String, nullable=False)
      iteration: Mapped[int] = mapped_column(Integer, default=1)
      is_active: Mapped[bool] = mapped_column(Boolean, default=True)
      status: Mapped[str] = mapped_column(String, default="new")  # new | processing | completed | failed
      prompt_template_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
      system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
      user_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
      output_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
      updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

      document_node = relationship("DocumentNode", back_populates="stage_states")
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `.venv/bin/pytest tests/test_models.py -k test_stage_state_persistent_fields`
  Expected: PASS

- [ ] **Step 5: Generate and run the Alembic database migration**
  Run:
  ```bash
  .venv/bin/alembic -c migrations/alembic.ini revision --autogenerate -m "add_persistent_stage_fields"
  .venv/bin/alembic -c migrations/alembic.ini upgrade head
  ```

- [ ] **Step 6: Commit changes**
  ```bash
  git add src/quill/models.py tests/test_models.py migrations/versions/
  git commit -m "feat: update StageState models and apply migration"
  ```

---

### Task 2: Adapt Runner & Piece Mappings to the New Schema

**Files:**
* Modify: `src/quill/piece.py`
* Modify: `src/quill/runner.py`
* Test: `tests/test_piece.py`
* Test: `tests/test_runner.py`

**Interfaces:**
* Consumes: Modifies internal state reads/writes on `Piece` and `StageRunner` to use the updated `StageState` attributes.

- [ ] **Step 1: Write tests verifying Piece stage state translation mapping**
  Verify that python-level status mappings translate correctly:
  ```python
  def test_piece_stage_status_translation(db_session):
      from quill.piece import Piece
      from quill.models import StageState
      # Create piece and verify that "completed" Maps to DB StageState.status == "completed"
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `.venv/bin/pytest tests/test_piece.py`
  Expected: Failures or warnings due to obsolete state columns (`body`, `superseded`).

- [ ] **Step 3: Modify `get_stage_state`, `set_stage_state`, and `supersede_from` in `src/quill/piece.py`**
  Redirect calls from `.body`, `.decision`, `.critique` to `.output_text` and map status states accordingly. Remove deletion logic for `superseded` files and replace with state machine logic.

- [ ] **Step 4: Run tests to verify all pass**
  Run: `.venv/bin/pytest tests/test_piece.py` and `.venv/bin/pytest tests/test_runner.py`
  Expected: PASS

- [ ] **Step 5: Commit changes**
  ```bash
  git add src/quill/piece.py src/quill/runner.py tests/test_piece.py tests/test_runner.py
  git commit -m "refactor: adapt piece and runner to new stage state schema"
  ```

---

### Task 3: Create the Stateless WorkflowEngine

**Files:**
* Create: `src/quill/engine.py`
* Create: `tests/test_engine.py`

**Interfaces:**
* Consumes: SQLAlchemy session, DB models, and pipeline configurations.
* Produces: `WorkflowEngine` class and `workflow_engine` singleton instance mapping transition logic and enqueuing tasks.

- [ ] **Step 1: Write unit tests for WorkflowEngine in `tests/test_engine.py`**
  Cover tests for sequential chapter progression, sliding context build, and the three revision strategy options (`full`, `surgical`, `cascade`):
  ```python
  def test_engine_cascade_revision_strategy(db_session, monkeypatch):
      # Set revision strategy config to cascade, flag Chapter 2, verify Chapter 2 & 3 are run, 1 is skipped
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `.venv/bin/pytest tests/test_engine.py`
  Expected: ModuleNotFoundError or test failures.

- [ ] **Step 3: Implement WorkflowEngine in `src/quill/engine.py`**
  Implement the stateless singleton service class, matching the approved sequential traversal design with sliding context assembly and configurable `revision_strategy` (`full`, `surgical`, `cascade`).

- [ ] **Step 4: Run engine tests to verify they pass**
  Run: `.venv/bin/pytest tests/test_engine.py`
  Expected: PASS

- [ ] **Step 5: Commit changes**
  ```bash
  git add src/quill/engine.py tests/test_engine.py
  git commit -m "feat: implement stateless WorkflowEngine"
  ```

---

### Task 4: Implement HTTP Coordinator Callback Endpoint

**Files:**
* Modify: `src/quill/blueprints/runs.py`
* Test: `tests/test_navigation.py`

**Interfaces:**
* Consumes: REST endpoint callback request body `{"node_id": str, "stage": str, "status": str}`.
* Produces: Triggers `workflow_engine.evaluate_and_dispatch(session, node_id, stage)`.

- [ ] **Step 1: Write test for workflow callback endpoint**
  ```python
  def test_workflow_callback_endpoint(client, db_session):
      response = client.post("/api/workflow/callback", json={
          "node_id": "test-chapter", "stage": "draft", "status": "completed"
      })
      assert response.status_code == 200
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `.venv/bin/pytest tests/test_navigation.py`
  Expected: 404 Not Found.

- [ ] **Step 3: Implement endpoint in `src/quill/blueprints/runs.py`**
  Add the `/api/workflow/callback` route, invoke `workflow_engine`, and commit/rollback database session appropriately.

- [ ] **Step 4: Run tests to verify they pass**
  Run: `.venv/bin/pytest tests/test_navigation.py`
  Expected: PASS

- [ ] **Step 5: Commit changes**
  ```bash
  git add src/quill/blueprints/runs.py tests/test_navigation.py
  git commit -m "feat: add workflow callback API endpoint"
  ```

---

### Task 5: Adapt Celery Tasks to Stateless Worker Execution

**Files:**
* Modify: `src/quill/celery_app.py`
* Test: `tests/test_celery_app.py`

**Interfaces:**
* Consumes: Accepts `node_id`, `stage`, `callback_url` parameters.
* Produces: Executes the StageRunner task and pings `callback_url`.

- [ ] **Step 1: Write test for Celery task callback execution**
  ```python
  def test_celery_task_sends_callback(monkeypatch):
      # Mock requests.post, call Celery task, verify requests.post was called with callback_url
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `.venv/bin/pytest tests/test_celery_app.py`
  Expected: FAIL (or missing arguments errors).

- [ ] **Step 3: Modify `run_stage_task` in `src/quill/celery_app.py`**
  Refactor parameters to accept `callback_url` and use `requests.post` to report task outcomes back to the coordinator.

- [ ] **Step 4: Run all tests to verify they pass**
  Run: `.venv/bin/pytest tests/`
  Expected: PASS

- [ ] **Step 5: Commit changes**
  ```bash
  git add src/quill/celery_app.py tests/test_celery_app.py
  git commit -m "feat: adapt Celery task to send execution callbacks"
  ```
