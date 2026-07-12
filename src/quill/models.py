"""Database schema models for the Quill application.

Defines the SQLAlchemy relational database models that replace filesystem/YAML-based
tracking of project metadata, stage status, metrics, and agent logs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Return timezone-naive UTC datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)



class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class Project(Base):
    """Top-level writing project metadata."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    genre: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    audience: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_length: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    constraints: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    current_stage: Mapped[str] = mapped_column(String, default="brief")
    agent_set: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    trigger: Mapped[str] = mapped_column(String, default="on_advance")
    revision_strategy: Mapped[str] = mapped_column(String, default="cascade")  # cascade | full | surgical
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    # Relationships
    document_nodes: Mapped[List[DocumentNode]] = relationship(
        "DocumentNode", back_populates="project", cascade="all, delete-orphan"
    )
    agent_logs: Mapped[List[AgentLog]] = relationship(
        "AgentLog", back_populates="project", cascade="all, delete-orphan"
    )


class DocumentNode(Base):
    """A node in a hierarchical document tree structure (e.g. Project root, Chapters, Scenes)."""

    __tablename__ = "document_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("document_nodes.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    node_type: Mapped[str] = mapped_column(String, default="chapter")  # project | chapter | scene
    order_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="document_nodes")
    parent: Mapped[Optional[DocumentNode]] = relationship(
        "DocumentNode", remote_side=[id], back_populates="children"
    )
    children: Mapped[List[DocumentNode]] = relationship(
        "DocumentNode", back_populates="parent", cascade="all, delete-orphan"
    )
    stage_states: Mapped[List[StageState]] = relationship(
        "StageState", back_populates="document_node", cascade="all, delete-orphan"
    )
    metrics: Mapped[List[Metrics]] = relationship(
        "Metrics", back_populates="document_node", cascade="all, delete-orphan"
    )
    agent_logs: Mapped[List[AgentLog]] = relationship(
        "AgentLog", back_populates="document_node", cascade="all, delete-orphan"
    )


class StageState(Base):
    """The workflow state, content, and inputs/outputs for a specific iteration of a stage."""

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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    # Backward compatibility properties mapping old columns to new columns
    def _get_json_data(self) -> dict:
        if self.output_text and self.output_text.strip().startswith("{") and self.output_text.strip().endswith("}"):
            try:
                import json
                data = json.loads(self.output_text)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def _set_json_value(self, key: str, value: Optional[str]):
        data = self._get_json_data()
        if not data and self.output_text and not (self.output_text.strip().startswith("{") and self.output_text.strip().endswith("}")):
            # Convert existing plain text to "body" or similar depending on context
            # By default, treat it as "body"
            data["body"] = self.output_text

        if value is None:
            data.pop(key, None)
        else:
            data[key] = value

        if not data:
            self.output_text = None
        elif len(data) == 1 and "body" in data:
            self.output_text = data["body"]
        else:
            import json
            self.output_text = json.dumps(data)

    @property
    def body(self) -> Optional[str]:
        data = self._get_json_data()
        if data:
            return data.get("body")
        return self.output_text

    @body.setter
    def body(self, value: Optional[str]):
        self._set_json_value("body", value)

    @property
    def critique(self) -> Optional[str]:
        data = self._get_json_data()
        if data:
            return data.get("critique")
        return None

    @critique.setter
    def critique(self, value: Optional[str]):
        self._set_json_value("critique", value)

    @property
    def decision(self) -> Optional[str]:
        data = self._get_json_data()
        if data:
            return data.get("decision")
        return None

    @decision.setter
    def decision(self, value: Optional[str]):
        self._set_json_value("decision", value)




    @property
    def state(self) -> str:
        if self.status == "completed":
            return "ready"
        if self.status == "new":
            return "fresh"
        if self.status == "processing":
            return "generating"
        return self.status

    @state.setter
    def state(self, value: str):
        if value in ("ready", "completed"):
            self.status = "completed"
        elif value in ("empty", "fresh", "new"):
            self.status = "new"
        elif value in ("generating", "processing"):
            self.status = "processing"
        else:
            self.status = value

    @property
    def loop_count(self) -> int:
        return max(0, self.iteration - 1)

    @loop_count.setter
    def loop_count(self, value: int):
        self.iteration = value + 1

    # Relationships
    document_node: Mapped[DocumentNode] = relationship("DocumentNode", back_populates="stage_states")



class Metrics(Base):
    """Mechanical readability and style score snapshot for a DocumentNode stage."""

    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_node_id: Mapped[str] = mapped_column(
        String, ForeignKey("document_nodes.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, default="current")  # current | baseline
    flesch_ease: Mapped[float] = mapped_column(Float, default=0.0)
    flesch_kincaid: Mapped[float] = mapped_column(Float, default=0.0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    sentence_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_sentence_length: Mapped[float] = mapped_column(Float, default=0.0)
    type_token_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    passive_voice_pct: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    # Relationships
    document_node: Mapped[DocumentNode] = relationship("DocumentNode", back_populates="metrics")


class AgentLog(Base):
    """An append-only database record of agent decisions, LLM calls, costs, and critiques."""

    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    document_node_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("document_nodes.id", ondelete="CASCADE"), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    call_type: Mapped[str] = mapped_column(String, nullable=False)  # generate | agent | evaluate | research
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_chars: Mapped[int] = mapped_column(Integer, default=0)
    user_chars: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Dynamically logged keys from results
    state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    queries: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    results: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cached: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    used_fallback: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    critique: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Cost tracking details
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    project: Mapped[Optional[Project]] = relationship("Project", back_populates="agent_logs")
    document_node: Mapped[Optional[DocumentNode]] = relationship("DocumentNode", back_populates="agent_logs")
