# ADR-003: Module Structure and Size Limits

**Status:** Accepted
**Date:** 2026-06-22
**Context:** runner.py grew to 1000+ lines because it handled prompt building, LLM calls, file I/O, metrics, event emission, run management, and logging — all in one class. Adding features (Jinja2, guardrails, async, structured output) each added 50-100 lines to the same file. The class violated single responsibility and made tests brittle (mocking 6+ subsystems per test).

## Decision

### 1. One class, one responsibility

Each class answers one question. If you can't describe it in one sentence, it's too broad.

| Class | Question it answers |
|-------|-------------------|
| `PromptBuilder` | "What goes to the LLM?" |
| `StageRunner` | "What stage runs next and what happens with the result?" |
| `RunManager` | "Is this run happening in the background?" |
| `MetricsService` | "What do the numbers say?" |
| `RunLogger` | "What happened and when?" |
| `LLMClient` | "How do we talk to the model?" |

### 2. File size limit: 300 lines

No source file exceeds 300 lines (excluding tests). If a file approaches 250 lines, split it. This is a hard limit, not a guideline.

**Rationale:** 300 lines fits in one screen. A developer can hold the entire file in working memory. Beyond that, you're scrolling and forgetting.

### 3. No God Objects

A class that takes more than 3 constructor parameters or has more than 10 public methods is doing too much. Split it.

### 4. Dependency direction

```
PromptBuilder ──┐
MetricsService ─┤
RunLogger ──────┼──→ StageRunner (orchestrator)
LLMClient ──────┤
RunManager ─────┘
```

Leaf classes (PromptBuilder, MetricsService, etc.) know nothing about each other. StageRunner orchestrates them. No circular dependencies.

### 5. File I/O is isolated

Only `RunLogger` and `MetricsService` touch the filesystem. StageRunner never calls `Path.write_text()` directly — it delegates to the appropriate service.

### 6. Events are a protocol, not a feature

Event emission is a callback interface (`Callable[[str, dict], None]`), not a dependency on RunManager. StageRunner accepts an optional `emit` callable. RunManager provides one implementation; tests provide a no-op.

## Consequences

- **runner.py** becomes a package: `src/quill/runner/`
  - `__init__.py` — exports StageRunner (public API unchanged)
  - `prompt_builder.py` — PromptBuilder class
  - `stage_runner.py` — StageRunner class (orchestrator, <300 lines)
  - `metrics_service.py` — MetricsService class
  - `run_logger.py` — RunLogger class
  - `run_manager.py` — RunManager class
- **Existing API unchanged** — `from quill.runner import StageRunner` still works
- **Tests become focused** — each class tested in isolation, mock only what it touches
- **New features get a home** — adding a feature means adding to one class, not bloating a monolith

## Non-goals

- Microservices / separate processes — this is file-level separation, not service-level
- Abstract base classes / interfaces — Python duck typing is fine
- DI framework — constructor injection is sufficient
