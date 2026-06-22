"""Runner — stage execution engine with critique-decide-loop logic.

For each stage:
1. Load agent config + prompt template
2. Read input files (previous stage output)
3. Fill prompt template with content
4. Call LLM
5. Parse response → decision (advance | loop_back)
6. Execute decision: write output file, update meta, loop or advance

Loop tracking is stored in meta.yaml under `loops`:
    loops:
        review: 2    # has looped twice
        revise: 0
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import jinja2
import yaml

from .agent import AgentConfig, AgentDecision, load_agent_config, parse_agent_response
from .llm import LLMClient
from .piece import Piece, load_piece, _FRONTMATTER_RE, _stage_filename
from .run_logger import RunLogger

logger = logging.getLogger(__name__)


class RunManager:
    """Singleton manager for async agent runs with SSE event streaming.

    Uses a ThreadPoolExecutor(max_workers=2) to run StageRunner in background
    threads. Each run gets an in-memory event queue that SSE endpoints can
    subscribe to.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._executor = ThreadPoolExecutor(max_workers=2)
                    inst._runs = {}  # run_id -> run info dict
                    inst._run_lock = threading.Lock()
                    cls._instance = inst
        return cls._instance

    def start_run(
        self,
        piece_id: str,
        stage: str | None = None,
        agent_set: str = "default",
        chain: bool = False,
    ) -> str:
        """Start a background run and return the run_id.

        Args:
            piece_id: The piece to run on.
            stage: Stage to run (default: piece's current stage).
            agent_set: Agent set to use.
            chain: If True, run all remaining stages.

        Returns:
            run_id string for SSE subscription.
        """
        self._cleanup_old_runs()

        run_id = uuid.uuid4().hex[:12]
        event_queue: queue.Queue = queue.Queue()

        with self._run_lock:
            self._runs[run_id] = {
                "queue": event_queue,
                "status": "running",
                "result": None,
                "piece_id": piece_id,
                "stage": stage,
                "agent_set": agent_set,
                "chain": chain,
                "started_at": time.time(),
            }

        self._executor.submit(
            self._execute_run, run_id, piece_id, stage, agent_set, chain, event_queue,
        )
        return run_id

    def get_run(self, run_id: str) -> dict | None:
        """Get run info by id."""
        with self._run_lock:
            return self._runs.get(run_id)

    def get_events(self, run_id: str):
        """Generator that yields SSE-formatted event strings.

        Blocks until the run completes (sentinel None in queue).
        Yields lines like:
            event: stage_start
            data: {"stage": "review", ...}

        Handles client disconnect by catching GeneratorExit.
        """
        with self._run_lock:
            run = self._runs.get(run_id)
        if not run:
            yield f"event: error\ndata: {__import__('json').dumps({'error': 'Run not found'})}\n\n"
            return

        q = run["queue"]
        try:
            while True:
                try:
                    event = q.get(timeout=300)  # 5 min timeout
                except queue.Empty:
                    # Heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
                    continue

                if event is None:
                    # Sentinel: run is complete
                    with self._run_lock:
                        run_info = self._runs.get(run_id, {})
                    yield f"event: run_complete\ndata: {__import__('json').dumps({'status': run_info.get('status', 'unknown'), 'result': run_info.get('result')})}\n\n"
                    return

                event_type = event.get("type", "message")
                data = event.get("data", {})
                yield f"event: {event_type}\ndata: {__import__('json').dumps(data)}\n\n"
        except GeneratorExit:
            # Client disconnected — stop consuming
            return

    def _execute_run(self, run_id, piece_id, stage, agent_set, chain, event_queue):
        """Background worker that runs StageRunner and emits events."""
        import json as _json

        try:
            runner = StageRunner(agent_set=agent_set)

            if chain:
                results = runner.run_chain(
                    piece_id, from_stage=stage, event_queue=event_queue,
                )
                result_data = {
                    "chain": True,
                    "results": [
                        {
                            "stage": r.stage,
                            "decision": r.decision,
                            "critique": r.critique[:500] + "..." if len(r.critique) > 500 else r.critique,
                            "loop_count": r.loop_count,
                            "error": r.error,
                        }
                        for r in results
                    ],
                }
            else:
                result = runner.run_stage(
                    piece_id, stage or "", event_queue=event_queue,
                )
                result_data = {
                    "stage": result.stage,
                    "decision": result.decision,
                    "critique": result.critique,
                    "loop_count": result.loop_count,
                    "error": result.error,
                }

            with self._run_lock:
                self._runs[run_id]["status"] = "complete"
                self._runs[run_id]["result"] = result_data

        except Exception as exc:
            logger.exception("Run %s failed", run_id)
            with self._run_lock:
                self._runs[run_id]["status"] = "error"
                self._runs[run_id]["result"] = {"error": str(exc)}
            event_queue.put({"type": "error", "data": {"error": str(exc)}})

        finally:
            # Signal completion
            event_queue.put(None)

    def _cleanup_old_runs(self):
        """Remove runs older than 5 minutes (thread-safe)."""
        cutoff = time.time() - 300
        with self._run_lock:
            expired = [
                rid for rid, info in self._runs.items()
                if info["started_at"] < cutoff
            ]
            for rid in expired:
                del self._runs[rid]


def _render_prompt(template: str, context: dict) -> str:
    """Render a prompt template with Jinja2, falling back to .replace().

    Jinja2 enables conditionals ({% if %}), loops, and filters.
    Falls back to simple string replacement if the template contains
    syntax that breaks Jinja2 (e.g., code examples with { }).
    """
    try:
        t = jinja2.Environment(
            undefined=jinja2.Undefined  # silently ignore undefined vars
        ).from_string(template)
        return t.render(**context)
    except jinja2.TemplateSyntaxError:
        # Fallback: manual .replace() for templates with non-Jinja2 braces
        result = template
        for key, value in context.items():
            result = result.replace("{{" + key + "}}", str(value))
        return result


class StageRunner:
    """Executes a pipeline stage using an LLM agent."""

    def __init__(self, agent_set: str = "default"):
        self.agent_set = agent_set
        self.run_logger = RunLogger()

    def _build_render_context(
        self, piece: "Piece", stage: str, input_content: str, metrics_context: str,
        loop_count: int | None = None, extra: dict | None = None,
    ) -> dict:
        """Build the full template variable context for prompt rendering."""
        if loop_count is None:
            loop_count = self.get_loop_count(piece, stage)
        ctx = {
            "TITLE": piece.title,
            "GENRE": piece.genre,
            "TYPE": piece.type,
            "LANGUAGE": piece.language,
            "STAGE": stage,
            "PIECE_ID": piece.id,
            "CONTENT": input_content,
            "METRICS": metrics_context,
            "loop_count": loop_count,
            "is_looping": loop_count > 0,
        }
        if extra:
            ctx.update(extra)
        return ctx

    @staticmethod
    def _get_structured_output_format() -> dict | None:
        """Return response_format dict if structured_output is enabled in config."""
        from .agent import load_model_config
        cfg = load_model_config()
        if cfg.get("structured_output"):
            return {"type": "json_object"}
        return None

    @staticmethod
    def _date_context() -> str:
        """Return a date context string to inject into system prompts."""
        now = datetime.now()
        return (
            f"IMPORTANT: Today is {now.strftime('%d %B %Y')}. "
            f"Your training data may be older. "
            f"Execute all tasks knowing the current date is {now.strftime('%d %B %Y')}."
        )

    @classmethod
    def _with_date(cls, system_prompt: str) -> str:
        """Prepend date context to a system prompt."""
        return f"{system_prompt}\n\n{cls._date_context()}"

    def _check_loop_guardrail(self, piece: Piece, stage: str, loop_count: int) -> str:
        """Check if metrics are degrading across loop iterations.

        Returns a description of the degradation if guardrail triggers,
        or empty string if metrics are stable/improving.

        Compares current {stage}.metrics.yaml with the snapshot saved
        before the first loop (stored as {stage}.guardrail-metrics.yaml).
        """
        from .metrics import load_metrics
        stage_dir = piece.stage_dir()
        stage_file = stage_dir / _stage_filename(stage)

        # Load current metrics
        current = load_metrics(stage_file)
        if not current:
            return ""

        # Load baseline (snapshot from before first loop)
        baseline_file = stage_dir / _stage_filename(stage, ".guardrail-metrics.yaml")
        if not baseline_file.exists():
            return ""
        baseline = yaml.safe_load(baseline_file.read_text()) or {}
        if not baseline:
            return ""

        issues = []

        # Word count drop > 30%
        curr_wc = current.get("word_count", 0)
        base_wc = baseline.get("word_count", 0)
        if base_wc > 0 and curr_wc > 0:
            drop = (base_wc - curr_wc) / base_wc
            if drop > 0.30:
                issues.append(f"word count dropped {drop:.0%} ({base_wc} → {curr_wc})")

        # Flesch ease shift > 15 points (readability regression)
        curr_flesch = current.get("flesch_ease", 50)
        base_flesch = baseline.get("flesch_ease", 50)
        shift = abs(curr_flesch - base_flesch)
        if shift > 15:
            direction = "harder" if curr_flesch < base_flesch else "easier"
            issues.append(f"readability shifted {shift:.0f} pts ({direction})")

        # Vocabulary diversity drop > 10%
        curr_ttr = current.get("type_token_ratio", 0.5)
        base_ttr = baseline.get("type_token_ratio", 0.5)
        if base_ttr > 0 and curr_ttr > 0:
            ttr_drop = (base_ttr - curr_ttr) / base_ttr
            if ttr_drop > 0.10:
                issues.append(f"vocabulary diversity dropped {ttr_drop:.0%}")

        # Passive voice increase > 10 percentage points
        curr_pv = current.get("passive_voice_pct", 0)
        base_pv = baseline.get("passive_voice_pct", 0)
        if curr_pv - base_pv > 10:
            issues.append(f"passive voice increased {curr_pv - base_pv:.0f}pp")

        return "; ".join(issues)

    def _save_guardrail_snapshot(self, piece: Piece, stage: str):
        """Save current metrics as baseline for loop guardrail comparison."""
        from .metrics import load_metrics
        stage_dir = piece.stage_dir()
        stage_file = stage_dir / _stage_filename(stage)
        current = load_metrics(stage_file)
        if current:
            snapshot_file = stage_dir / _stage_filename(stage, ".guardrail-metrics.yaml")
            snapshot_file.write_text(
                yaml.dump(current, default_flow_style=False),
                encoding="utf-8",
            )
            logger.info("Saved guardrail snapshot for %s", stage)

    def _cleanup_guardrail_snapshot(self, piece: Piece, stage: str):
        """Remove guardrail snapshot after successful advance."""
        stage_dir = piece.stage_dir()
        snapshot_file = stage_dir / _stage_filename(stage, ".guardrail-metrics.yaml")
        if snapshot_file.exists():
            snapshot_file.unlink()
            logger.info("Cleaned up guardrail snapshot for %s", stage)

    def get_loop_count(self, piece: Piece, stage: str) -> int:
        """Get the current loop count for a stage."""
        meta_path = piece.stage_dir() / "meta.yaml"
        if not meta_path.exists():
            return 0
        meta = yaml.safe_load(meta_path.read_text()) or {}
        return meta.get("loops", {}).get(stage, 0)

    def set_loop_count(self, piece: Piece, stage: str, count: int):
        """Update the loop count for a stage in meta.yaml."""
        meta_path = piece.stage_dir() / "meta.yaml"
        meta = yaml.safe_load(meta_path.read_text()) or {}
        if "loops" not in meta:
            meta["loops"] = {}
        meta["loops"][stage] = count
        meta_path.write_text(
            yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def compose_prompt(self, piece_id: str, stage: str, output_dir: Path | None = None) -> dict:
        """Assemble the full prompt for a stage without calling the LLM.

        Returns a dict with the system prompt, user prompt, and metadata
        so you can inspect exactly what would be sent.
        """
        from .pipeline import load_pipeline
        pipeline = load_pipeline("default")
        stage_def = pipeline.get_stage(stage)

        from .piece import DEFAULT_OUTPUT_DIR
        base = output_dir or DEFAULT_OUTPUT_DIR
        piece_dir = base / piece_id
        if not piece_dir.exists():
            return {"error": f"Piece '{piece_id}' not found"}

        piece = load_piece(piece_dir)

        agent_cfg = load_agent_config(self.agent_set, stage)
        if not agent_cfg or not agent_cfg.prompt_template:
            return {"error": f"No agent config for stage '{stage}' in set '{self.agent_set}'"}

        loop_count = self.get_loop_count(piece, stage)
        input_content = self._read_inputs(piece, stage, pipeline, loop_count)
        metrics_context = self._build_metrics_context(piece, stage, pipeline)

        ctx = self._build_render_context(piece, stage, input_content, metrics_context, loop_count)
        prompt = _render_prompt(agent_cfg.prompt_template, ctx)

        content_stages = {"outline", "draft", "revise", "humanize", "polish"}
        is_content_stage = stage in content_stages

        if is_content_stage:
            gen_system = self._with_date(
                f"You are a {stage} agent for a {piece.genre} {piece.type} "
                f"in {piece.language}. Produce high-quality content. "
                f"Do NOT include any JSON or decision blocks — just write the content."
            )
            # Build the evaluate prompt from template (no LLM call)
            eval_template = self._load_evaluate_template(self.agent_set)
            if eval_template:
                eval_ctx = self._build_render_context(
                    piece, stage, input_content, "", loop_count,
                    extra={"GENERATED": "<not yet generated — will be filled at runtime>",
                           "INPUT_CONTENT": input_content},
                )
                eval_prompt = _render_prompt(eval_template, eval_ctx)
            else:
                eval_prompt = (
                    f"You are a quality evaluator for a {piece.genre} {piece.type}.\n\n"
                    f"## Stage: {stage}\n\n"
                    f"## Input given to the {stage} agent:\n{input_content}\n\n"
                    f"## Generated {stage} output:\n<not yet generated>\n\n"
                    f"## Task\n"
                    f"Evaluate the generated {stage} output.\n\n"
                    f"Be strict but fair. Only loop_back if there are real, fixable problems."
                )
            eval_system = self._with_date(
                f"You are a quality evaluator. Respond with ONLY a JSON block "
                f"containing 'decision' (advance or loop_back) and 'critique'."
            )
            return {
                "piece_id": piece_id,
                "stage": stage,
                "agent_set": self.agent_set,
                "loop_count": loop_count,
                "max_loops": agent_cfg.max_loops,
                "is_content_stage": True,
                "model": agent_cfg.model,
                "api_base": agent_cfg.api_base,
                "temperature": agent_cfg.temperature,
                "max_tokens": agent_cfg.max_tokens,
                "generate": {
                    "system": gen_system,
                    "user": prompt,
                    "char_count": len(prompt),
                },
                "evaluate": {
                    "system": eval_system,
                    "user": eval_prompt,
                    "char_count": len(eval_prompt),
                    "note": "The 'Generated output' section above shows '<not yet generated>' — the real evaluate prompt includes the actual generated text from the generate call.",
                },
                "input_content_char_count": len(input_content),
                "template_vars": {
                    "TITLE": piece.title,
                    "GENRE": piece.genre,
                    "TYPE": piece.type,
                    "LANGUAGE": piece.language,
                    "STAGE": stage,
                    "PIECE_ID": piece_id,
                    "METRICS": metrics_context,
                    "loop_count": loop_count,
                    "is_looping": loop_count > 0,
                    "max_loops": agent_cfg.max_loops,
                },
            }
        else:
            eval_system = self._with_date(
                f"You are a {stage} agent for a {piece.genre} {piece.type} "
                f"in {piece.language}. Be critical and precise. "
                f"Respond with a JSON block containing 'decision' and 'critique'."
            )
            return {
                "piece_id": piece_id,
                "stage": stage,
                "agent_set": self.agent_set,
                "loop_count": loop_count,
                "max_loops": agent_cfg.max_loops,
                "is_content_stage": False,
                "model": agent_cfg.model,
                "api_base": agent_cfg.api_base,
                "temperature": agent_cfg.temperature,
                "max_tokens": agent_cfg.max_tokens,
                "single_call": {
                    "system": eval_system,
                    "user": prompt,
                    "char_count": len(prompt),
                },
                "input_content_char_count": len(input_content),
                "template_vars": {
                    "TITLE": piece.title,
                    "GENRE": piece.genre,
                    "TYPE": piece.type,
                    "LANGUAGE": piece.language,
                    "STAGE": stage,
                    "PIECE_ID": piece_id,
                    "METRICS": metrics_context,
                    "loop_count": loop_count,
                    "is_looping": loop_count > 0,
                    "max_loops": agent_cfg.max_loops,
                },
            }

    def _emit(self, event_queue, event_type: str, data: dict):
        """Emit an event to the queue if provided."""
        if event_queue is not None:
            event_queue.put({"type": event_type, "data": data})

    def run_stage(self, piece_id: str, stage: str, output_dir: Path | None = None, event_queue=None) -> AgentDecision:
        """Execute a pipeline stage.

        Args:
            piece_id: The piece ID to process.
            stage: The stage to execute (e.g. "review", "revise").
            output_dir: Override output directory.

        Returns:
            AgentDecision with the result.
        """
        from .pipeline import load_pipeline
        pipeline = load_pipeline("default")
        stage_def = pipeline.get_stage(stage)

        # Load piece
        from .piece import DEFAULT_OUTPUT_DIR
        base = output_dir or DEFAULT_OUTPUT_DIR
        piece_dir = base / piece_id
        if not piece_dir.exists():
            return AgentDecision(
                decision="error",
                critique="",
                output="",
                error=f"Piece '{piece_id}' not found",
            )

        piece = load_piece(piece_dir)

        # Load agent config
        agent_cfg = load_agent_config(self.agent_set, stage)
        if not agent_cfg or not agent_cfg.prompt_template:
            return AgentDecision(
                decision="error",
                critique="",
                output="",
                error=f"No agent config for stage '{stage}' in set '{self.agent_set}'",
            )

        # Check loop limit
        loop_count = self.get_loop_count(piece, stage)
        if loop_count >= agent_cfg.max_loops:
            logger.info("Stage '%s' reached max loops (%d), forcing advance",
                       stage, agent_cfg.max_loops)
            return AgentDecision(
                decision="advance",
                critique=f"Max loops ({agent_cfg.max_loops}) reached. Forcing advance.",
                output="",
                loop_count=loop_count,
                stage=stage,
            )

        # Read input files
        input_content = self._read_inputs(piece, stage, pipeline, loop_count)

        # Fill prompt template
        from .metrics import load_metrics
        metrics_context = self._build_metrics_context(piece, stage, pipeline)
        loop_count = self.get_loop_count(piece, stage)
        ctx = self._build_render_context(piece, stage, input_content, metrics_context, loop_count)
        prompt = _render_prompt(agent_cfg.prompt_template, ctx)

        client = LLMClient(
            api_base=agent_cfg.api_base,
            api_key=agent_cfg.api_key,
            model=agent_cfg.model,
            temperature=agent_cfg.temperature,
            max_tokens=agent_cfg.max_tokens,
        )

        content_stages = {"outline", "draft", "revise", "humanize", "polish"}
        is_content_stage = stage in content_stages

        self._emit(event_queue, "stage_start", {
            "stage": stage,
            "is_content_stage": is_content_stage,
            "prompt_chars": len(prompt),
            "loop_count": loop_count,
        })

        if is_content_stage:
            # Two-call approach: generate first, then evaluate
            gen_system = self._with_date(
                f"You are a {stage} agent for a {piece.genre} {piece.type} "
                f"in {piece.language}. Produce high-quality content. "
                f"Do NOT include any JSON or decision blocks — just write the content."
            )
            self.run_logger.log(piece, stage, "generate", gen_system, prompt)
            self._emit(event_queue, "stage_llm_call", {
                "stage": stage, "call": "generate", "prompt_chars": len(prompt),
            })
            try:
                generated = client.chat(gen_system, prompt)
            except ConnectionError as e:
                return AgentDecision(
                    decision="error", critique="", output="",
                    error=str(e), stage=stage,
                )

            # Persist generated content immediately (survives loop_back)
            self._write_output(piece, stage, generated)

            # Second call: evaluate the generated content
            self._emit(event_queue, "stage_llm_call", {
                "stage": stage, "call": "evaluate", "output_chars": len(generated),
            })
            decision = self._evaluate_output(
                client, stage, piece, generated, pipeline, input_content,
                agent_set=self.agent_set,
            )
            decision.body = generated
            decision.output = generated

            # Persist evaluation result to separate file
            self._write_decision(piece, stage, decision)
        else:
            # Feedback stages: single call with JSON decision expected
            eval_system = self._with_date(
                f"You are a {stage} agent for a {piece.genre} {piece.type} "
                f"in {piece.language}. Be critical and precise. "
                f"Respond with a JSON block containing 'decision' and 'critique'."
            )
            self.run_logger.log(piece, stage, "agent", eval_system, prompt)
            response_format = self._get_structured_output_format()
            self._emit(event_queue, "stage_llm_call", {
                "stage": stage, "call": "agent", "prompt_chars": len(prompt),
            })
            try:
                response = client.chat(eval_system, prompt, response_format=response_format)
            except ConnectionError as e:
                return AgentDecision(
                    decision="error", critique="", output="",
                    error=str(e), stage=stage,
                )
            decision = parse_agent_response(response)
            decision.output = response
            self.run_logger.log(piece, stage, "agent", eval_system, prompt, {
                "decision": decision.decision, "critique": decision.critique[:500],
            })

        decision.loop_count = loop_count
        decision.stage = stage

        # Loop guardrail: check for metric degradation across iterations
        if decision.decision == "loop_back" and loop_count > 0:
            guardrail = self._check_loop_guardrail(piece, stage, loop_count)
            if guardrail:
                decision.decision = "advance"
                decision.critique = (
                    f"[Loop guardrail] Forcing advance after {loop_count} loops. "
                    f"Metrics degraded: {guardrail}. "
                    f"Original critique: {decision.critique}"
                )
                logger.warning("Loop guardrail triggered for '%s': %s", stage, guardrail)
                self._emit(event_queue, "loop_guardrail", {
                    "stage": stage, "loop_count": loop_count,
                    "reason": guardrail, "forced_advance": True,
                })
        elif decision.decision == "loop_back" and loop_count == 0:
            # Save baseline metrics snapshot for future guardrail comparisons
            self._save_guardrail_snapshot(piece, stage)

        # Execute decision
        if decision.decision == "loop_back":
            self.set_loop_count(piece, stage, loop_count + 1)
            # For feedback stages, write critique to decision file
            if not is_content_stage:
                self._write_decision(piece, stage, decision)
            # Content stages already wrote both output and decision above
            logger.info("Stage '%s' loop_back (loop %d/%d)",
                       stage, loop_count + 1, agent_cfg.max_loops)
            self._emit(event_queue, "loop_start", {
                "stage": stage, "loop_count": loop_count + 1,
                "max_loops": agent_cfg.max_loops,
                "critique": decision.critique[:300],
            })
        elif decision.decision == "advance":
            # Reset loop count for this stage
            self.set_loop_count(piece, stage, 0)
            self._cleanup_guardrail_snapshot(piece, stage)
            # Content stages: output already written above, just clean up decision file
            # Feedback stages: write critique as the stage output
            if not is_content_stage:
                self._write_output(piece, stage, self._format_feedback(decision.critique))
            # Compute text metrics for content stages
            if is_content_stage:
                self._compute_metrics(piece, stage)
            # Advance meta.yaml to next stage
            if stage_def and stage_def.next:
                self._advance_meta(piece, stage_def.next)
            logger.info("Stage '%s' → advance to '%s'", stage,
                       stage_def.next if stage_def else "?")
        else:
            logger.warning("Stage '%s' returned unknown decision: '%s'",
                          stage, decision.decision)

        self._emit(event_queue, "stage_complete", {
            "stage": stage,
            "decision": decision.decision,
            "critique": decision.critique[:500],
            "loop_count": loop_count,
            "error": decision.error,
        })

        return decision

    def run_chain(self, piece_id: str, from_stage: str | None = None,
                  output_dir: Path | None = None, event_queue=None) -> list[AgentDecision]:
        """Run a chain of stages from the current stage to done.

        Args:
            piece_id: The piece ID to process.
            from_stage: Start from this stage (default: current stage).
            output_dir: Override output directory.
            event_queue: Optional queue for SSE event emission.

        Returns:
            List of AgentDecision results for each stage run.
        """
        from .pipeline import load_pipeline
        from .piece import DEFAULT_OUTPUT_DIR
        pipeline = load_pipeline("default")
        base = output_dir or DEFAULT_OUTPUT_DIR

        piece_dir = base / piece_id
        if not piece_dir.exists():
            return [AgentDecision(
                decision="error", critique="", output="",
                error=f"Piece '{piece_id}' not found",
            )]

        piece = load_piece(piece_dir)
        current = from_stage or piece.current_stage
        results = []
        max_stages = 20  # safety limit
        skipped_stages = []

        self._emit(event_queue, "chain_start", {
            "piece_id": piece_id,
            "from_stage": current,
            "agent_set": self.agent_set,
        })

        while current and current != "done" and len(results) < max_stages:
            # Check if agent set has a prompt for this stage
            agent_cfg = load_agent_config(self.agent_set, current)
            if not agent_cfg or not agent_cfg.prompt_template:
                logger.warning(
                    "Skipping stage '%s' — no agent prompt in set '%s'",
                    current, self.agent_set,
                )
                skipped_stages.append(current)
                # Advance to next stage via pipeline
                stage_def = pipeline.get_stage(current)
                if stage_def and stage_def.next:
                    current = stage_def.next
                    continue
                else:
                    break

            result = self.run_stage(piece_id, current, output_dir, event_queue=event_queue)
            results.append(result)

            self._emit(event_queue, "chain_stage_complete", {
                "stage": result.stage,
                "decision": result.decision,
                "completed": len(results),
                "error": result.error,
            })

            if result.error:
                break
            if result.decision == "advance":
                # Reload piece to get updated current_stage
                piece = load_piece(piece_dir)
                current = piece.current_stage
            elif result.decision == "loop_back":
                # Stay on same stage, run again (loop limit handled in run_stage)
                pass
            else:
                break

        # If no stages ran and we only skipped, return an error
        if not results and skipped_stages:
            self._emit(event_queue, "chain_complete", {
                "total_stages": 0,
                "skipped": skipped_stages,
                "error": True,
            })
            return [AgentDecision(
                decision="error", critique="", output="",
                error=(
                    f"No agent prompts found for any stage starting from "
                    f"'{from_stage or piece.current_stage}' in set '{self.agent_set}'. "
                    f"Skipped: {', '.join(skipped_stages)}"
                ),
            )]

        self._emit(event_queue, "chain_complete", {
            "total_stages": len(results),
            "skipped": skipped_stages,
            "last_decision": results[-1].decision if results else None,
        })
        return results

    # Stage-specific input requirements (override default "previous stage" logic)
    # Maps stage → list of files to read as input
    # Content stages read from the PREVIOUS CONTENT stage, not the feedback stage before them
    _STAGE_INPUTS = {
        "outline": ["brief.md"],                       # needs brief
        "draft": ["outline.md", "brief.md"],           # needs outline + brief
        "revise": ["draft.md", "review.md"],       # needs draft + critique
        "humanize": ["revise.md"],                  # needs revised text
        "polish": ["humanize.md", "validate.md"],   # needs humanized text + validation feedback
    }

    def _read_inputs(self, piece: Piece, stage: str, pipeline, loop_count: int = 0) -> str:
        """Read input files for a stage.

        Uses stage-specific input mapping when defined,
        otherwise falls back to reading the previous stage's output.
        """
        stage_dir = piece.stage_dir()
        inputs = []

        # Stage-specific inputs
        if stage in self._STAGE_INPUTS:
            for input_stage in self._STAGE_INPUTS[stage]:
                # Strip .md suffix to get the stage name
                input_stage_name = input_stage.replace(".md", "")
                fpath = stage_dir / _stage_filename(input_stage_name)
                if fpath.exists():
                    text = fpath.read_text(encoding="utf-8")
                    m = _FRONTMATTER_RE.match(text)
                    inputs.append(f"=== {fpath.name} ===\n{text[m.end():] if m else text}")
        else:
            # Default: read previous stage's output
            stage_order = pipeline.stage_order
            if stage in stage_order:
                idx = stage_order.index(stage)
                if idx > 0:
                    prev_stage = stage_order[idx - 1]
                    prev_file = stage_dir / _stage_filename(prev_stage)
                    if prev_file.exists():
                        text = prev_file.read_text(encoding="utf-8")
                        m = _FRONTMATTER_RE.match(text)
                        inputs.append(f"=== {_stage_filename(prev_stage)} ===\n{text[m.end():] if m else text}")

        # If looping, also read the current stage's existing content and decision
        if loop_count > 0:
            current_file = stage_dir / _stage_filename(stage)
            if current_file.exists():
                text = current_file.read_text(encoding="utf-8")
                m = _FRONTMATTER_RE.match(text)
                body = text[m.end():] if m else text
                if body.strip():
                    inputs.append(f"=== {_stage_filename(stage)} (previous attempt) ===\n{body}")

            decision_file = stage_dir / _stage_filename(stage, ".decision.md")
            if decision_file.exists():
                text = decision_file.read_text(encoding="utf-8")
                inputs.append(f"=== {_stage_filename(stage, '.decision.md')} (evaluation feedback) ===\n{text}")

        return "\n\n".join(inputs) if inputs else "(no input files found)"

    def _format_feedback(self, critique: str) -> str:
        """Clean feedback text by stripping JSON code fences and formatting."""
        from .agent import _strip_json_block
        cleaned = _strip_json_block(critique)
        return cleaned if cleaned else critique

    def _write_output(self, piece: Piece, stage: str, content: str):
        """Write agent output to a stage file."""
        output_file = piece.stage_dir() / _stage_filename(stage)
        output_file.write_text(content, encoding="utf-8")
        logger.info("Wrote output to %s", output_file)

    def _write_critique(self, piece: Piece, stage: str, critique: str):
        """Write critique to a stage file (for loop context)."""
        output_file = piece.stage_dir() / _stage_filename(stage)
        output_file.write_text(critique, encoding="utf-8")
        logger.info("Wrote critique to %s", output_file)

    def _write_decision(self, piece: Piece, stage: str, decision: "AgentDecision"):
        """Write evaluation decision to a separate .decision.md file."""
        decision_file = piece.stage_dir() / _stage_filename(stage, ".decision.md")
        content = (
            f"## Decision: {decision.decision}\n\n"
            f"## Critique\n{decision.critique}\n"
        )
        decision_file.write_text(content, encoding="utf-8")
        logger.info("Wrote decision to %s", decision_file)

    def _compute_metrics(self, piece: Piece, stage: str):
        """Compute and save text metrics for a stage's output file."""
        from .metrics import compute_and_save
        stage_file = piece.stage_dir() / _stage_filename(stage)
        if stage_file.exists():
            try:
                metrics = compute_and_save(stage_file)
                logger.info("Metrics for %s/%s: flesch=%.1f, words=%d",
                           piece.id, stage, metrics["flesch_ease"], metrics["word_count"])
            except Exception as e:
                logger.warning("Failed to compute metrics for %s/%s: %s",
                              piece.id, stage, e)

    def _build_metrics_context(self, piece: Piece, stage: str, pipeline) -> str:
        """Build a metrics context string for the agent prompt.

        Loads metrics from the input stages and formats them as a readable block.
        """
        from .metrics import load_metrics

        stage_dir = piece.stage_dir()
        lines = []

        # Get input stage names
        if stage in self._STAGE_INPUTS:
            input_stages = [f.replace(".md", "") for f in self._STAGE_INPUTS[stage]]
        else:
            stage_order = pipeline.stage_order
            if stage in stage_order:
                idx = stage_order.index(stage)
                input_stages = [stage_order[idx - 1]] if idx > 0 else []
            else:
                input_stages = []

        for input_stage in input_stages:
            stage_file = stage_dir / _stage_filename(input_stage)
            m = load_metrics(stage_file) if stage_file.exists() else None
            if m:
                lines.append(f"--- {input_stage} metrics ---")
                lines.append(f"  Flesch Reading Ease: {m.get('flesch_ease', 'n/a')}")
                lines.append(f"  Flesch-Kincaid Grade: {m.get('flesch_kincaid', 'n/a')}")
                lines.append(f"  Word count: {m.get('word_count', 'n/a')}")
                lines.append(f"  Avg sentence length: {m.get('avg_sentence_length', 'n/a')} words")
                lines.append(f"  Vocabulary diversity: {round(m.get('type_token_ratio', 0) * 100, 1)}%")
                lines.append(f"  Passive voice: {m.get('passive_voice_pct', 'n/a')}%")

        # Also include current stage metrics if looping
        current_stage_file = stage_dir / _stage_filename(stage)
        if current_stage_file.exists():
            m = load_metrics(current_stage_file)
            if m:
                lines.append(f"--- {stage} metrics (current) ---")
                lines.append(f"  Flesch Reading Ease: {m.get('flesch_ease', 'n/a')}")
                lines.append(f"  Word count: {m.get('word_count', 'n/a')}")
                lines.append(f"  Vocabulary diversity: {round(m.get('type_token_ratio', 0) * 100, 1)}%")

        return "\n".join(lines) if lines else "(no metrics available)"

    def _evaluate_output(
        self, client: "LLMClient", stage: str, piece: "Piece",
        generated: str, pipeline, input_content: str,
        agent_set: str = "default",
    ) -> AgentDecision:
        """Second call: evaluate generated content and return a JSON decision.

        Loads the evaluate.prompt.md template from the agent set, fills in
        {{GENERATED}}, {{INPUT_CONTENT}}, and standard variables, then calls
        the LLM with the full (untruncated) content.
        """
        # Load evaluate prompt template
        eval_template = self._load_evaluate_template(agent_set)

        if eval_template:
            # Compute metrics on the generated text for the evaluator
            from .metrics import compute_and_save, load_metrics
            stage_file = piece.stage_dir() / _stage_filename(stage)
            metrics_str = ""
            if stage_file.exists():
                try:
                    compute_and_save(stage_file)
                    m = load_metrics(stage_file)
                    if m:
                        metrics_str = "\n".join([
                            f"--- {stage} metrics ---",
                            f"  Flesch Reading Ease: {m.get('flesch_ease', 'n/a')}",
                            f"  Flesch-Kincaid Grade: {m.get('flesch_kincaid', 'n/a')}",
                            f"  Word count: {m.get('word_count', 'n/a')}",
                            f"  Avg sentence length: {m.get('avg_sentence_length', 'n/a')} words",
                            f"  Vocabulary diversity: {round(m.get('type_token_ratio', 0) * 100, 1)}%",
                            f"  Passive voice: {m.get('passive_voice_pct', 'n/a')}%",
                        ])
                except Exception as e:
                    logger.warning("Failed to compute metrics for evaluate prompt: %s", e)

            eval_ctx = self._build_render_context(
                piece, stage, input_content, metrics_str, 0,
                extra={"GENERATED": generated, "INPUT_CONTENT": input_content},
            )
            prompt = _render_prompt(eval_template, eval_ctx)
            eval_system = self._with_date(
                f"You are a quality evaluator. Respond with ONLY a JSON block "
                f"containing 'decision' (advance or loop_back) and 'critique'."
            )
            self.run_logger.log(piece, stage, "evaluate", eval_system, prompt)
        else:
            # Fallback to hardcoded if no template exists
            logger.warning("No evaluate.prompt.md in agent set '%s', using fallback", agent_set)
            prompt = (
                f"You are a quality evaluator for a {piece.genre} {piece.type}.\n\n"
                f"## Stage: {stage}\n\n"
                f"## Input given to the {stage} agent:\n{input_content}\n\n"
                f"## Generated {stage} output:\n{generated}\n\n"
                f"## Task\n"
                f"Evaluate the generated {stage} output. Is it high quality? "
                f"Does it meet the requirements? Respond with ONLY a JSON block:\n\n"
                f'{{"decision": "advance", "critique": "brief feedback"}}\n'
                f'or\n'
                f'{{"decision": "loop_back", "critique": "specific issues to fix"}}\n\n'
                f"Be strict but fair. Only loop_back if there are real, fixable problems."
            )
            eval_system = self._with_date(
                f"You are a quality evaluator. Respond with ONLY a JSON block "
                f"containing 'decision' (advance or loop_back) and 'critique'."
            )

        response_format = self._get_structured_output_format()
        try:
            eval_response = client.chat(eval_system, prompt, response_format=response_format)
        except ConnectionError:
            return AgentDecision(decision="advance", critique="Evaluation call failed, advancing by default.", output="")

        result = parse_agent_response(eval_response)
        self.run_logger.log(piece, stage, "evaluate", eval_system, prompt, {
            "decision": result.decision, "critique": result.critique[:500],
        })
        return result

    def _load_evaluate_template(self, agent_set: str) -> str | None:
        """Load evaluate.prompt.md from an agent set directory."""
        from .agent import AGENTS_DIR
        template_file = AGENTS_DIR / agent_set / "evaluate.prompt.md"
        if template_file.exists():
            return template_file.read_text(encoding="utf-8")
        return None

    def _advance_meta(self, piece: Piece, next_stage: str):
        """Update meta.yaml to point to the next stage."""
        meta_path = piece.stage_dir() / "meta.yaml"
        meta = yaml.safe_load(meta_path.read_text()) or {}
        meta["current_stage"] = next_stage
        meta["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        meta_path.write_text(
            yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        logger.info("Advanced meta.yaml to stage '%s'", next_stage)
