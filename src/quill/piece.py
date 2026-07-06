"""Piece — markdown document with YAML frontmatter for stage tracking.

Each piece lives in its own directory under output/:
    output/<piece-id>/
        brief.md
        outline.md
        draft.md
        ...
        done.md

Each stage file has YAML frontmatter (shared metadata + current_stage)
and a body (the content for that stage). When a piece advances, the
current stage file is preserved and a new stage file is created.

For backward compatibility, single .md files in output/ are still
loaded (legacy format).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .models import Project, DocumentNode, StageState
from .db import db_session

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

# Matches YAML frontmatter between --- delimiters
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

def _get_stage_prefix(stage: str) -> str | None:
    """Derive numeric prefix from pipeline stage_order.

    Returns zero-padded 2-digit string (e.g. '01', '02') or None.
    Lazy-imports pipeline to avoid circular imports.
    """
    try:
        from .pipeline import load_pipeline
        pipeline = load_pipeline("default")
        if stage in pipeline.stage_order:
            idx = pipeline.stage_order.index(stage)
            return f"{idx + 1:02d}"
    except Exception:
        pass
    return None


def _stage_filename(stage: str, suffix: str = ".md") -> str:
    """Return the prefixed filename for a stage file.

    Examples: _stage_filename("draft") → "03_draft.md"
              _stage_filename("draft", ".decision.md") → "03_draft.decision.md"
              _stage_filename("unknown") → "unknown.md"
    """
    prefix = _get_stage_prefix(stage)
    if prefix:
        return f"{prefix}_{stage}{suffix}"
    return f"{stage}{suffix}"


@dataclass
class Piece:
    """A writing piece with metadata and stage tracking."""

    # Stage classification


    # Identity
    id: str = ""
    title: str = ""

    # Metadata (from brief)
    genre: str = ""  # fiction | non-fiction
    type: str = ""  # story | blog | editorial | analysis | tutorial | essay
    audience: str = ""
    tone: str = ""
    language: str = ""  # en | bg | mixed
    target_length: str = ""  # e.g. "5000-8000 words"
    constraints: list[str] = field(default_factory=list)

    # Orchestrator: parent-child tracking
    children: list[str] = field(default_factory=list)  # child piece IDs
    parent: str = ""  # parent piece ID (empty if top-level)

    # Workflow state
    current_stage: str = "brief"
    created: str = ""
    updated: str = ""

    # Agent configuration
    agent_set: str = ""  # empty = auto-detect
    trigger: str = "on_advance"  # manual | on_advance | auto

    # Stage state tracking
    stage_states: dict[str, str] = field(default_factory=dict)

    # Content (everything after the frontmatter of the CURRENT stage file)
    body: str = ""

    # File location
    _path: Path | None = field(default=None, repr=False)  # directory for new format, file for legacy
    _is_legacy: bool = field(default=False, repr=False)
    dual_write: bool = field(default=True, repr=False)

    @property
    def log(self):
        """Get a logger tagged with this piece's ID."""
        if not hasattr(self, "_log") or self._log is None:
            from .logging_config import get_piece_logger
            self._log = get_piece_logger("piece", self.id)
        return self._log

    def to_frontmatter(self) -> dict:
        """Export metadata as a dict for YAML serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "genre": self.genre,
            "type": self.type,
            "audience": self.audience,
            "tone": self.tone,
            "language": self.language,
            "target_length": self.target_length,
            "constraints": self.constraints,
            "current_stage": self.current_stage,
            "created": self.created,
            "updated": self.updated,
            "agent_set": self.agent_set,
            "trigger": self.trigger,
            "stage_states": self.stage_states,
            "children": self.children,
            "parent": self.parent,
        }

    def to_markdown(self) -> str:
        """Serialize piece to markdown with YAML frontmatter."""
        fm = yaml.dump(
            self.to_frontmatter(),
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        return f"---\n{fm}---\n\n{self.body}"

    def stage_dir(self) -> Path:
        """Get the piece directory (new format)."""
        if self._path and self._path.is_dir():
            return self._path
        # Legacy: derive directory from file path
        if self._path:
            return self._path.parent / self._path.stem
        return DEFAULT_OUTPUT_DIR / self.id

    def stage_file(self, stage: str | None = None) -> Path:
        """Get the file path for a specific stage."""
        stage = stage or self.current_stage
        return self.stage_dir() / _stage_filename(stage)

    def list_stages(self) -> list[dict]:
        """List all stages that exist for this piece."""
        try:
            session = db_session()
            stages = session.query(StageState).filter_by(document_node_id=self.id).all()
            if stages:
                res = []
                for s in stages:
                    if s.state == "empty" and not s.body and s.stage != self.current_stage:
                        continue
                    res.append({
                        "stage": s.stage,
                        "path": str(self.stage_dir() / _stage_filename(s.stage)),
                        "body_length": len(s.body) if s.body else 0,
                        "updated": s.updated_at.strftime("%Y-%m-%d") if s.updated_at else "",
                    })
                return sorted(res, key=lambda x: _stage_filename(x["stage"]))
        except Exception:
            pass

        d = self.stage_dir()
        if not d.exists():
            return []
        stages = []
        for f in sorted(d.glob("*.md")):
            # Skip decision, metrics, and debug files
            name = f.name
            if ".decision." in name or ".metrics." in name:
                continue
            if ".generate-prompt." in name or ".evaluate-prompt." in name:
                continue
            try:
                text = f.read_text(encoding="utf-8")
                m = _FRONTMATTER_RE.match(text)
                if m:
                    meta = yaml.safe_load(m.group(1))
                    body = text[m.end():]
                    # Strip numeric prefix from stem: "03_draft" → "draft"
                    stem = f.stem
                    if len(stem) > 2 and stem[0:2].isdigit() and stem[2] == "_":
                        stem = stem[3:]
                    stages.append({
                        "stage": stem,
                        "path": str(f),
                        "body_length": len(body),
                        "updated": meta.get("updated", ""),
                    })
            except Exception:
                pass
        return stages

    def display_stages(self) -> list[dict]:
        """List stages with prefixed display names for content stages.

        Content stages get a numeric prefix like ``04_revise.md``.
        Feedback stages (review, validate) keep their plain names.
        The actual filenames on disk are unchanged.
        """
        stages = self.list_stages()
        for entry in stages:
            entry["display_name"] = _stage_filename(entry["stage"])
        return stages

    def save(self, output_dir: Path | None = None) -> Path:
        """Save piece to database and/or disk. Returns the file path."""
        self.updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 1. Database persistence
        try:
            session = db_session()
            is_child = bool(self.parent)

            if not is_child:
                # Top-level project
                project = session.query(Project).filter_by(id=self.id).first()
                if not project:
                    project = Project(id=self.id)
                    session.add(project)
                
                project.title = self.title
                project.genre = self.genre or ""
                project.type = self.type or ""
                project.audience = self.audience or ""
                project.tone = self.tone or ""
                project.language = self.language or ""
                project.target_length = self.target_length or ""
                project.constraints = self.constraints or []
                project.current_stage = self.current_stage
                project.agent_set = self.agent_set or ""
                project.trigger = self.trigger or "on_advance"
                try:
                    if self.created:
                        project.created_at = datetime.strptime(self.created, "%Y-%m-%d")
                except Exception:
                    pass
                project.updated_at = datetime.utcnow()

                # Ensure DocumentNode exists for project root
                node = session.query(DocumentNode).filter_by(id=self.id).first()
                if not node:
                    node = DocumentNode(
                        id=self.id,
                        project_id=self.id,
                        parent_id=None,
                        node_type="project",
                    )
                    session.add(node)
                node.title = self.title
                node.updated_at = datetime.utcnow()
            else:
                # Child piece (chapter/scene)
                node = session.query(DocumentNode).filter_by(id=self.id).first()
                if not node:
                    node = DocumentNode(
                        id=self.id,
                        project_id=self.parent,
                        parent_id=self.parent,
                        node_type="chapter",
                    )
                    session.add(node)
                node.title = self.title
                node.updated_at = datetime.utcnow()

            # Merge current_stage into stage_states if not already there
            stages_to_save = dict(self.stage_states)
            if self.current_stage not in stages_to_save:
                stages_to_save[self.current_stage] = self.get_stage_state(self.current_stage)

            for stage_name, stage_state_val in stages_to_save.items():
                st_state = session.query(StageState).filter_by(document_node_id=self.id, stage=stage_name).first()
                if not st_state:
                    st_state = StageState(
                        document_node_id=self.id,
                        stage=stage_name,
                    )
                    session.add(st_state)
                st_state.state = stage_state_val
                st_state.loop_count = self.get_loop_count(stage_name)
                st_state.updated_at = datetime.utcnow()

                # If this is the current stage, save the body
                if stage_name == self.current_stage:
                    st_state.body = self.body

            session.commit()
        except Exception as e:
            logger.error("Failed to save piece '%s' to database: %s", self.id, e)
            try:
                db_session.rollback()
            except Exception:
                pass

        # 2. Filesystem / Dual-write persistence
        if self._is_legacy:
            # Legacy single-file format
            path = self._path or (output_dir or DEFAULT_OUTPUT_DIR) / f"{self.id}.md"
            path.write_text(self.to_markdown(), encoding="utf-8")
            self._path = path
            logger.info("Saved piece '%s' (legacy) to %s", self.title, path)
            return path

        if getattr(self, "dual_write", True):
            if self._path and self._path.is_dir():
                d = self._path
            else:
                base = output_dir or DEFAULT_OUTPUT_DIR
                d = base / self.id
            d.mkdir(parents=True, exist_ok=True)

            # Save stage file
            path = d / _stage_filename(self.current_stage)
            path.write_text(self.to_markdown(), encoding="utf-8")

            # Save/update meta.yaml
            meta_path = d / "meta.yaml"
            existing_meta = {}
            if meta_path.exists():
                try:
                    existing_meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    pass
            existing_meta.update(self.to_frontmatter())
            meta_path.write_text(
                yaml.dump(existing_meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            self._path = d
            logger.info("Saved piece '%s' stage '%s' to %s (dual-write)", self.title, self.current_stage, path)
            return path
        else:
            base = output_dir or DEFAULT_OUTPUT_DIR
            self._path = base / self.id
            return self._path / _stage_filename(self.current_stage)

    def get_loop_count(self, stage: str) -> int:
        """Get the current loop count for a stage from database or meta.yaml."""
        try:
            session = db_session()
            st_state = session.query(StageState).filter_by(document_node_id=self.id, stage=stage).first()
            if st_state:
                return st_state.loop_count
        except Exception:
            pass

        meta_path = self.stage_dir() / "meta.yaml"
        if not meta_path.exists():
            return 0
        try:
            meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
            return meta.get("loops", {}).get(stage, 0)
        except Exception:
            return 0

    def set_loop_count(self, stage: str, count: int):
        """Update the loop count for a stage in database and meta.yaml."""
        try:
            session = db_session()
            st_state = session.query(StageState).filter_by(document_node_id=self.id, stage=stage).first()
            if not st_state:
                st_state = StageState(
                    document_node_id=self.id,
                    stage=stage,
                )
                session.add(st_state)
            st_state.loop_count = count
            st_state.updated_at = datetime.utcnow()
            session.commit()
        except Exception as e:
            logger.error("Failed to set loop count in database for piece '%s' stage '%s': %s", self.id, stage, e)
            try:
                db_session.rollback()
            except Exception:
                pass

        if getattr(self, "dual_write", True):
            meta_path = self.stage_dir() / "meta.yaml"
            meta = {}
            if meta_path.exists():
                try:
                    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    pass
            if "loops" not in meta:
                meta["loops"] = {}
            meta["loops"][stage] = count
            try:
                meta_path.write_text(
                    yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

    def advance_to(self, next_stage: str):
        """Update current_stage in database and meta.yaml."""
        self.current_stage = next_stage
        self.updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            session = db_session()
            is_child = bool(self.parent)

            if not is_child:
                project = session.query(Project).filter_by(id=self.id).first()
                if project:
                    project.current_stage = next_stage
                    project.updated_at = datetime.utcnow()
            
            st_state = session.query(StageState).filter_by(document_node_id=self.id, stage=next_stage).first()
            if not st_state:
                st_state = StageState(
                    document_node_id=self.id,
                    stage=next_stage,
                )
                session.add(st_state)
            st_state.updated_at = datetime.utcnow()
            
            session.commit()
            logger.info("Advanced database to stage '%s'", next_stage)
        except Exception as e:
            logger.error("Failed to advance piece '%s' stage in database: %s", self.id, e)
            try:
                db_session.rollback()
            except Exception:
                pass

        if getattr(self, "dual_write", True):
            try:
                meta_path = self.stage_dir() / "meta.yaml"
                if meta_path.exists():
                    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
                else:
                    meta = {}
                meta["current_stage"] = next_stage
                meta["updated"] = self.updated
                meta_path.write_text(
                    yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
                logger.info("Advanced meta.yaml to stage '%s'", next_stage)
            except Exception as e:
                logger.warning("Failed to advance meta.yaml to stage '%s': %s", next_stage, e)

    # ── Stage state management ───────────────────────────────────────

    def get_stage_state(self, stage: str) -> str:
        """Get the state of a stage: fresh | generating | completed.

        Reads from meta.yaml stage_states dict. Unknown stages default to 'fresh'.
        """
        val = self.stage_states.get(stage, "fresh")
        if val == "empty" or val == "superseded":
            return "fresh"
        if val == "ready":
            return "completed"
        return val

    def set_stage_state(self, stage: str, state: str):
        """Set the state of a stage and persist to meta.yaml."""
        if state == "empty" or state == "superseded":
            state = "fresh"
        elif state == "ready":
            state = "completed"
        self.stage_states[stage] = state
        self._save_stage_states()

    def supersede_from(self, stage: str):
        """Mark all stages after `stage` as superseded (fresh), reset frontier, clear content.

        The given stage itself is NOT superseded — it's the new frontier.
        """
        from .pipeline import load_pipeline
        pipeline = load_pipeline("default")

        if stage not in pipeline.stage_order:
            return

        idx = pipeline.stage_order.index(stage)
        later_stages = pipeline.stage_order[idx + 1:]

        # 1. Update database
        try:
            session = db_session()
            for s in later_stages:
                self.stage_states[s] = "fresh"
                st_state = session.query(StageState).filter_by(document_node_id=self.id, stage=s).first()
                if not st_state:
                    st_state = StageState(
                        document_node_id=self.id,
                        stage=s,
                    )
                    session.add(st_state)
                st_state.state = "fresh"
                st_state.body = None
                st_state.decision = None
                st_state.critique = None
                st_state.loop_count = 0
                st_state.updated_at = datetime.utcnow()
            session.commit()
            logger.info("Superseded later stages in database for piece '%s'", self.id)
        except Exception as e:
            logger.error("Failed to supersede stages in database for piece '%s': %s", self.id, e)
            try:
                db_session.rollback()
            except Exception:
                pass

        # 2. Update filesystem / dual-write
        for s in later_stages:
            self.stage_states[s] = "fresh"
            if getattr(self, "dual_write", True):
                try:
                    # Clear content file
                    f = self.stage_dir() / _stage_filename(s)
                    if f.exists():
                        f.unlink()
                        logger.info("Superseded: removed %s", f)
                    # Clear decision file
                    decision_f = self.stage_dir() / _stage_filename(s, ".decision.md")
                    if decision_f.exists():
                        decision_f.unlink()
                    # Clear JSON file
                    json_f = self.stage_dir() / _stage_filename(s, ".json")
                    if json_f.exists():
                        json_f.unlink()
                except Exception as e:
                    logger.warning("Failed to remove file during supersede: %s", e)

        self.current_stage = stage
        self._save_stage_states()
        self.advance_to(stage)
        logger.info("Superseded from stage '%s', frontier reset", stage)

    def can_navigate(self, stage: str) -> bool:
        """Check if a stage is viewable. Fresh stages are locked.

        Fallback: if stage not in stage_states, allow up to current_stage
        (backward compat with pieces created before stage_states).
        """
        state = self.get_stage_state(stage)
        if state != "fresh":
            return True
        # Stage not in stage_states — fall back to current_stage as frontier
        try:
            from .pipeline import load_pipeline
            pipeline = load_pipeline("default")
            if stage in pipeline.stage_order and self.current_stage in pipeline.stage_order:
                return pipeline.stage_order.index(stage) <= pipeline.stage_order.index(self.current_stage)
        except Exception:
            pass
        return False

    def _save_stage_states(self):
        """Persist stage_states to database and meta.yaml."""
        try:
            session = db_session()
            for stage_name, stage_state_val in self.stage_states.items():
                st_state = session.query(StageState).filter_by(document_node_id=self.id, stage=stage_name).first()
                if not st_state:
                    st_state = StageState(
                        document_node_id=self.id,
                        stage=stage_name,
                    )
                    session.add(st_state)
                st_state.state = stage_state_val
                st_state.loop_count = self.get_loop_count(stage_name)
                st_state.updated_at = datetime.utcnow()
            session.commit()
        except Exception as e:
            logger.error("Failed to save stage states to database for piece '%s': %s", self.id, e)
            try:
                db_session.rollback()
            except Exception:
                pass

        if getattr(self, "dual_write", True):
            meta_path = self.stage_dir() / "meta.yaml"
            meta = {}
            if meta_path.exists():
                try:
                    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    pass
            meta["stage_states"] = self.stage_states
            try:
                meta_path.write_text(
                    yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

    @staticmethod
    def _clean_content(content: str) -> str:
        """Mechanical cleanup of LLM output — deterministic, no LLM judgment."""
        content = content.replace("—", " - ")    # em dash → dash
        content = content.replace("–", " - ")     # en dash → dash
        content = content.replace("\u00a0", " ")  # non-breaking space → space
        content = content.replace("\u2018", "'")  # left single quote
        content = content.replace("\u2019", "'")  # right single quote / apostrophe
        content = content.replace("\u201c", '"')  # left double quote
        content = content.replace("\u201d", '"')  # right double quote
        return content

    def write_output(self, stage: str, content: str):
        """Write agent output to database and stage file."""
        clean_content = self._clean_content(content)
        
        # 1. Update database
        try:
            session = db_session()
            st_state = session.query(StageState).filter_by(document_node_id=self.id, stage=stage).first()
            if not st_state:
                st_state = StageState(
                    document_node_id=self.id,
                    stage=stage,
                )
                session.add(st_state)
            st_state.body = clean_content
            st_state.updated_at = datetime.utcnow()
            session.commit()
            logger.info("Wrote output to database for piece '%s' stage '%s'", self.id, stage)
        except Exception as e:
            logger.error("Failed to write output to database: %s", e)
            try:
                db_session.rollback()
            except Exception:
                pass

        if stage == self.current_stage:
            self.body = clean_content

        # 2. Update filesystem / dual-write
        if getattr(self, "dual_write", True):
            try:
                output_file = self.stage_dir() / _stage_filename(stage)
                output_file.write_text(clean_content, encoding="utf-8")
                logger.info("Wrote output to %s", output_file)
            except Exception as e:
                logger.warning("Failed to write output to %s: %s", output_file, e)

    def write_decision(self, stage: str, decision_decision: str, decision_critique: str):
        """Write evaluation decision to database and separate .decision.md file."""
        # 1. Update database
        try:
            session = db_session()
            st_state = session.query(StageState).filter_by(document_node_id=self.id, stage=stage).first()
            if not st_state:
                st_state = StageState(
                    document_node_id=self.id,
                    stage=stage,
                )
                session.add(st_state)
            st_state.decision = decision_decision
            st_state.critique = decision_critique
            st_state.updated_at = datetime.utcnow()
            session.commit()
            logger.info("Wrote decision to database for piece '%s' stage '%s'", self.id, stage)
        except Exception as e:
            logger.error("Failed to write decision to database: %s", e)
            try:
                db_session.rollback()
            except Exception:
                pass

        # 2. Update filesystem / dual-write
        if getattr(self, "dual_write", True):
            try:
                decision_file = self.stage_dir() / _stage_filename(stage, ".decision.md")
                content = (
                    f"## Decision: {decision_decision}\n\n"
                    f"## Critique\n{decision_critique}\n"
                )
                decision_file.write_text(content, encoding="utf-8")
                logger.info("Wrote decision to %s", decision_file)
            except Exception as e:
                logger.warning("Failed to write decision to %s: %s", decision_file, e)

    def write_json(self, stage: str, content: str):
        """Write raw JSON output to database and `<stage>.json` file."""
        # 1. Update database
        try:
            session = db_session()
            st_state = session.query(StageState).filter_by(document_node_id=self.id, stage=stage).first()
            if not st_state:
                st_state = StageState(
                    document_node_id=self.id,
                    stage=stage,
                )
                session.add(st_state)
            st_state.decision = "advance"
            st_state.critique = content
            st_state.updated_at = datetime.utcnow()
            session.commit()
            logger.info("Wrote JSON output to database for piece '%s' stage '%s'", self.id, stage)
        except Exception as e:
            logger.error("Failed to write JSON output to database: %s", e)
            try:
                db_session.rollback()
            except Exception:
                pass

        # 2. Update filesystem / dual-write
        if getattr(self, "dual_write", True):
            try:
                json_file = self.stage_dir() / _stage_filename(stage, ".json")
                json_file.write_text(content, encoding="utf-8")
                logger.info("Wrote JSON output to %s", json_file)
            except Exception as e:
                logger.warning("Failed to write JSON output to %s: %s", json_file, e)

    def to_dict(self) -> dict:
        """Export as API-friendly dict."""
        d = self.to_frontmatter()
        d["body_length"] = len(self.body)
        d["path"] = str(self._path) if self._path else None
        d["is_legacy"] = self._is_legacy
        if not self._is_legacy:
            d["stages"] = self.list_stages()
            d["display_stages"] = self.display_stages()
        return d


def _load_from_text(text: str, path: Path) -> Piece:
    """Parse a piece from markdown text with YAML frontmatter."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"No YAML frontmatter found in {path}")

    meta = yaml.safe_load(m.group(1))
    body = text[m.end():]

    return Piece(
        id=meta.get("id", path.stem),
        title=meta.get("title", ""),
        genre=meta.get("genre", ""),
        type=meta.get("type", ""),
        audience=meta.get("audience", ""),
        tone=meta.get("tone", ""),
        language=meta.get("language", ""),
        target_length=meta.get("target_length", ""),
        constraints=meta.get("constraints", []) or [],
        current_stage=meta.get("current_stage", "brief"),
        created=meta.get("created", ""),
        updated=meta.get("updated", ""),
        agent_set=meta.get("agent_set", ""),
        trigger=meta.get("trigger", "on_advance"),
        stage_states=meta.get("stage_states", {}) or {},
        body=body,
        _path=path,
    )


def load_piece(path: Path, node: DocumentNode | None = None) -> Piece:
    """Load a piece from the database or directory (new) or single file (legacy)."""
    piece_id = path.stem if (path.exists() and path.is_file()) else path.name
    try:
        session = db_session()
        if node is None:
            node = session.query(DocumentNode).filter_by(id=piece_id).first()
        if node:
            # Find Project metadata
            project = node.project
            # Find all StageStates
            stages = node.stage_states
            stage_states = {s.stage: s.state for s in stages}
            
            is_child = node.parent_id is not None
            if not is_child and project:
                current_stage = project.current_stage
            else:
                if stages:
                    latest_stage = max(stages, key=lambda s: (s.updated_at or datetime.min))
                    current_stage = latest_stage.stage
                else:
                    current_stage = "brief"
            
            # Load body for current stage
            curr_stage_state = next((s for s in stages if s.stage == current_stage), None)
            body = curr_stage_state.body if curr_stage_state else ""
            if body is None:
                body = ""
                
            # Children mapping
            children = [c.id for c in node.children]
            
            piece = Piece(
                id=piece_id,
                title=node.title,
                genre=project.genre if project else "",
                type=project.type if project else "",
                audience=project.audience if project else "",
                tone=project.tone if project else "",
                language=project.language if project else "",
                target_length=project.target_length if project else "",
                constraints=(project.constraints if project else []) or [],
                current_stage=current_stage,
                created=project.created_at.strftime("%Y-%m-%d") if (project and project.created_at) else "",
                updated=node.updated_at.strftime("%Y-%m-%d") if node.updated_at else "",
                agent_set=project.agent_set if (project and not is_child) else "",
                trigger=project.trigger if (project and not is_child) else "on_advance",
                stage_states=stage_states,
                children=children,
                parent=node.parent_id or "",
                body=body,
                _path=path,
                _is_legacy=False,
            )
            if is_child and project:
                piece.agent_set = project.agent_set or ""
                piece.trigger = project.trigger or "on_advance"
            return piece
    except Exception as e:
        logger.warning("Failed to load piece '%s' from database, falling back to filesystem: %s", piece_id, e)

    if path.is_dir():
        # Fallback to filesystem
        meta_file = path / "meta.yaml"
        if not meta_file.exists():
            raise ValueError(f"No meta.yaml found in {path}")

        meta = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
        current_stage = meta.get("current_stage", "brief")

        # Load the current stage file
        stage_file = path / _stage_filename(current_stage)
        body = ""
        if stage_file.exists():
            text = stage_file.read_text(encoding="utf-8")
            m = _FRONTMATTER_RE.match(text)
            if m:
                body = text[m.end():]
            else:
                body = text
        else:
            logger.warning("Stage file %s not found, body empty", stage_file)

        piece = Piece(
            id=meta.get("id", path.name),
            title=meta.get("title", ""),
            genre=meta.get("genre", ""),
            type=meta.get("type", ""),
            audience=meta.get("audience", ""),
            tone=meta.get("tone", ""),
            language=meta.get("language", ""),
            target_length=meta.get("target_length", ""),
            constraints=meta.get("constraints", []) or [],
            current_stage=current_stage,
            created=meta.get("created", ""),
            updated=meta.get("updated", ""),
            agent_set=meta.get("agent_set", ""),
            trigger=meta.get("trigger", "on_advance"),
            stage_states=meta.get("stage_states", {}) or {},
            children=meta.get("children", []) or [],
            parent=meta.get("parent", ""),
            body=body,
            _path=path,
            _is_legacy=False,
        )
        return piece

    # Legacy single-file format
    text = path.read_text(encoding="utf-8")
    piece = _load_from_text(text, path)
    piece._is_legacy = True
    return piece


def list_pieces(output_dir: Path | None = None) -> list[Piece]:
    """List all pieces from the database, falling back to the output directory."""
    pieces = []
    seen_ids = set()

    # 1. Load pieces from database
    try:
        from sqlalchemy.orm import joinedload, selectinload
        session = db_session()
        nodes = (
            session.query(DocumentNode)
            .options(
                joinedload(DocumentNode.project),
                selectinload(DocumentNode.stage_states),
                selectinload(DocumentNode.children),
            )
            .order_by(DocumentNode.id)
            .all()
        )
        for node in nodes:
            try:
                path = (output_dir or DEFAULT_OUTPUT_DIR) / node.id
                piece = load_piece(path, node=node)
                pieces.append(piece)
                seen_ids.add(node.id)
            except Exception as e:
                logger.warning("Failed to load piece '%s' from DB: %s", node.id, e)
    except Exception as e:
        logger.warning("Failed to list pieces from database: %s", e)

    # 2. Scanning filesystem for any pieces not in database (for legacy compatibility)
    base = output_dir or DEFAULT_OUTPUT_DIR
    if base.exists():
        # New format: directories
        for d in sorted(base.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and not d.name.startswith("_"):
                if d.name not in seen_ids:
                    md_files = list(d.glob("*.md"))
                    if md_files:
                        try:
                            pieces.append(load_piece(d))
                            seen_ids.add(d.name)
                        except (ValueError, yaml.YAMLError) as e:
                            logger.warning("Skipping %s: %s", d.name, e)

        # Legacy format: standalone .md files
        for md_file in sorted(base.glob("*.md")):
            if md_file.stem not in seen_ids:
                try:
                    pieces.append(load_piece(md_file))
                    seen_ids.add(md_file.stem)
                except (ValueError, yaml.YAMLError) as e:
                    logger.warning("Skipping %s: %s", md_file.name, e)

    return pieces


def get_piece(piece_id: str, output_dir: Path | None = None) -> Piece | None:
    """Find a piece by ID."""
    path = (output_dir or DEFAULT_OUTPUT_DIR) / piece_id
    try:
        from sqlalchemy.orm import joinedload, selectinload
        session = db_session()
        node = (
            session.query(DocumentNode)
            .options(
                joinedload(DocumentNode.project),
                selectinload(DocumentNode.stage_states),
                selectinload(DocumentNode.children),
            )
            .filter_by(id=piece_id)
            .first()
        )
        if node:
            return load_piece(path, node=node)
    except Exception:
        pass

    if path.exists():
        try:
            return load_piece(path)
        except Exception:
            pass

    legacy_path = (output_dir or DEFAULT_OUTPUT_DIR) / f"{piece_id}.md"
    if legacy_path.exists():
        try:
            return load_piece(legacy_path)
        except Exception:
            pass

    # Fallback to listing
    for piece in list_pieces(output_dir):
        if piece.id == piece_id:
            return piece
    return None
