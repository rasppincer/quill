import os
import logging
import re
import yaml
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from .models import Project, DocumentNode, StageState, utc_now
from .pipeline import Pipeline, WORKFLOWS_DIR, Stage
from .narrative_state import NarrativeState

logger = logging.getLogger(__name__)

# Stages that run sequentially per chapter
CHAPTERED_STAGES = {"draft", "review", "revise", "humanize", "validate", "polish", "state"}

def load_pipeline(name: str = "default") -> Pipeline:
    """Load Pipeline stage configurations from workflows YAML file."""
    path = WORKFLOWS_DIR / f"{name}.yaml"
    if not path.exists():
        path = WORKFLOWS_DIR / "default.yaml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    
    stages = {}
    for s in data.get("stages", []):
        stages[s["key"]] = Stage(
            key=s["key"],
            name=s["name"],
            description=s.get("description", ""),
            mode=s.get("mode", "content"),
            next=s.get("next"),
            can_reject_to=s.get("can_reject_to", []),
            required_fields=s.get("required_fields", []),
            required_artifacts=s.get("required_artifacts", []),
            rules=s.get("rules", []),
            checklist=s.get("checklist", ""),
        )
    
    stage_order = [s["key"] for s in data.get("stages", [])]
    return Pipeline(
        name=data.get("name", name),
        description=data.get("description", ""),
        stages=stages,
        stage_order=stage_order,
        stage_inputs=data.get("stage_inputs", {})
    )

def extract_chapters(text: str) -> List[Dict[str, str]]:
    """Extract segment/chapter names from structure output."""
    if not text:
        return []
    headers = re.findall(r'^##\s+(?:Segment|Part|Chapter)\s*(\d+)\s*[:\s]*(.*)', text, re.MULTILINE)
    return [{"title": h[1].strip() or f"Chapter {h[0]}"} for h in headers]

def get_or_create_stage_state(session: Session, node_id: str, stage: str) -> StageState:
    """Helper to retrieve or insert a StageState row."""
    st = session.query(StageState).filter_by(document_node_id=node_id, stage=stage).first()
    if not st:
        st = StageState(
            document_node_id=node_id,
            stage=stage,
            iteration=1,
            status="new",
            is_active=True
        )
        session.add(st)
    return st

class WorkflowEngine:
    """Stateless DB-centric writing workflow engine."""

    def evaluate_and_dispatch(self, session: Session, node_id: str, completed_stage: str):
        """Determine next step in writing pipeline and enqueue Celery task."""
        logger.info("Evaluating workflow after completed stage '%s' on node '%s'", completed_stage, node_id)

        node = session.query(DocumentNode).filter_by(id=node_id).first()
        if not node:
            logger.error("Node '%s' not found", node_id)
            return

        project = session.query(Project).filter_by(id=node.project_id).first()
        if not project:
            logger.error("Project '%s' not found", node.project_id)
            return

        pipeline = load_pipeline(project.agent_set or "default")

        # 1. Sequential chapter resolution
        if node.node_type == "chapter":
            chapters = self._get_sorted_chapters(session, project.id)
            current_idx = next((i for i, ch in enumerate(chapters) if ch.id == node_id), -1)

            # Check if there are remaining chapters to process for this stage
            next_ch_idx = self._find_next_uncompleted_chapter(session, chapters, current_idx, completed_stage)
            if next_ch_idx is not None:
                # Dispatch on the next chapter
                self._dispatch_task(chapters[next_ch_idx].id, completed_stage, session)
                return

            # All chapters completed this stage! Move project to next stage
            next_stage = pipeline.next_stage(completed_stage)
            if not next_stage:
                logger.info("Pipeline completed all stages.")
                project.current_stage = "done"
                session.commit()
                return

            project.current_stage = next_stage
            session.commit()

            # Handle transition to next stage
            self._transition_project_stage(session, project, pipeline, next_stage)

        # 2. Project-level stage resolution
        else:
            if completed_stage == "structure":
                self._ensure_chapters_exist(session, project)

            # Get stage state
            st_state = session.query(StageState).filter_by(document_node_id=project.id, stage=completed_stage).first()
            decision_val = st_state.decision if st_state else None

            # Resolve next stage
            next_stage = pipeline.next_stage(completed_stage, decision_val)
            if not next_stage:
                logger.info("Pipeline completed all stages.")
                project.current_stage = "done"
                session.commit()
                return

            project.current_stage = next_stage
            session.commit()

            # If rejecting, apply revision strategy
            if decision_val == "reject":
                self._apply_revision_strategy(session, project, pipeline, next_stage, st_state.critique)
            else:
                self._transition_project_stage(session, project, pipeline, next_stage)

    def _transition_project_stage(self, session: Session, project: Project, pipeline: Pipeline, next_stage: str):
        """Transition the project to the next stage in the pipeline."""
        if next_stage in CHAPTERED_STAGES:
            # Initialize next stage state for all child chapters to new
            chapters = self._get_sorted_chapters(session, project.id)
            for ch in chapters:
                st = get_or_create_stage_state(session, ch.id, next_stage)
                st.status = "new"
                st.is_active = True
            session.commit()

            # Dispatch Chapter 1
            if chapters:
                self._dispatch_task(chapters[0].id, next_stage, session)
        else:
            # Project-level stage
            st = get_or_create_stage_state(session, project.id, next_stage)
            st.status = "new"
            st.is_active = True
            session.commit()

            self._dispatch_task(project.id, next_stage, session)

    def _apply_revision_strategy(self, session: Session, project: Project, pipeline: Pipeline, target_stage: str, critique: str):
        """Apply revision strategies: cascade, full, surgical to chapter nodes."""
        chapters = self._get_sorted_chapters(session, project.id)
        if not chapters:
            return

        # Parse critique to identify flagged chapters
        flagged_indices = []
        if critique:
            matches = re.findall(r'\b(?:chapter|segment|part)\s*(\d+)\b', critique, re.IGNORECASE)
            if matches:
                flagged_indices = [int(m) for m in matches]

        # Global Critique Fallback
        if not flagged_indices:
            flagged_indices = [1]

        strategy = getattr(project, "revision_strategy", "cascade") or "cascade"
        logger.info("Applying revision strategy '%s' for target stage '%s' based on critique. Flagged indices: %s", 
                    strategy, target_stage, flagged_indices)

        # Flag chapters to run based on strategy
        to_run = set()
        if strategy == "full":
            to_run = set(range(1, len(chapters) + 1))
        elif strategy == "surgical":
            to_run = set(flagged_indices)
        else:  # cascade
            earliest_flag = min(flagged_indices) if flagged_indices else 1
            to_run = set(range(earliest_flag, len(chapters) + 1))

        # Update stage states
        for idx, ch in enumerate(chapters, 1):
            st = get_or_create_stage_state(session, ch.id, target_stage)
            if idx in to_run:
                st.iteration = st.iteration + 1
                st.status = "new"
                st.output_text = None
                st.is_active = True
            else:
                # Skipped chapter: mark completed and copy output from preceding stage
                st.status = "completed"
                st.is_active = True
                
                # Fetch preceding output
                prev_content = None
                for s in ["revise", "draft"]:
                    prev_st = session.query(StageState).filter_by(document_node_id=ch.id, stage=s).first()
                    if prev_st and prev_st.output_text:
                        prev_content = prev_st.output_text
                        break
                st.output_text = prev_content
        
        session.commit()

        # Find the first chapter to run
        first_to_run_idx = next((i for i, ch in enumerate(chapters, 1) if i in to_run), None)
        if first_to_run_idx is not None:
            self._dispatch_task(chapters[first_to_run_idx - 1].id, target_stage, session)

    def _ensure_chapters_exist(self, session: Session, project: Project):
        """Parse structure and insert DocumentNodes for chapters if they do not exist."""
        struct_st = session.query(StageState).filter_by(document_node_id=project.id, stage="structure").first()
        if struct_st and struct_st.output_text:
            chapters_meta = extract_chapters(struct_st.output_text)
            existing = session.query(DocumentNode).filter_by(project_id=project.id, node_type="chapter").all()
            if not existing:
                for idx, ch in enumerate(chapters_meta):
                    child_node = DocumentNode(
                        id=f"{project.id}-chapter-{idx+1}",
                        project_id=project.id,
                        parent_id=project.id,
                        node_type="chapter",
                        title=ch["title"],
                        order_index=idx
                    )
                    session.add(child_node)
                session.commit()

    def _get_sorted_chapters(self, session: Session, project_id: str) -> List[DocumentNode]:
        """Fetch and return child chapter nodes sorted sequentially."""
        nodes = session.query(DocumentNode).filter_by(project_id=project_id, node_type="chapter").all()
        return sorted(nodes, key=lambda n: n.order_index if n.order_index is not None else int(n.id.split("-")[-1]) if n.id.split("-")[-1].isdigit() else 0)

    def _find_next_uncompleted_chapter(self, session: Session, chapters: List[DocumentNode], current_idx: int, stage: str) -> Optional[int]:
        """Find the next chapter in order that is not completed for the stage."""
        for i in range(current_idx + 1, len(chapters)):
            st = session.query(StageState).filter_by(document_node_id=chapters[i].id, stage=stage).first()
            if not st or st.status != "completed":
                return i
        return None

    def _dispatch_task(self, node_id: str, stage: str, session: Session):
        """Prepare sliding context and enqueue Celery task."""
        node = session.query(DocumentNode).filter_by(id=node_id).first()
        project = session.query(Project).filter_by(id=node.project_id).first()
        
        extra_context = None
        if node.node_type == "chapter" and stage in CHAPTERED_STAGES:
            chapters = self._get_sorted_chapters(session, project.id)
            current_idx = next((i for i, ch in enumerate(chapters) if ch.id == node_id), -1)
            extra_context = self._build_sliding_context(session, project, chapters, current_idx, stage)

        # Update DB state status to processing
        st = get_or_create_stage_state(session, node_id, stage)
        st.status = "processing"
        st.updated_at = utc_now()
        session.commit()

        # Enqueue Celery task dynamically to avoid circular import
        from .celery_app import run_stage_task
        callback_url = os.environ.get("QUILL_COORDINATOR_CALLBACK_URL", "http://localhost:8325/api/workflow/callback")
        
        logger.info("Enqueuing Celery task for node '%s' stage '%s'", node_id, stage)
        run_stage_task.delay(node_id, stage, callback_url=callback_url, extra_context=extra_context)

    def _build_sliding_context(self, session: Session, project: Project, chapters: List[DocumentNode], current_idx: int, stage: str) -> Dict[str, Any]:
        """Build sliding window context for chapter prompts."""
        prior_parts = []

        # 1. Distant chapters: NarrativeState summaries (1..N-2)
        prior_states = []
        for idx in range(0, current_idx - 1):
            st = session.query(StageState).filter_by(document_node_id=chapters[idx].id, stage="state").first()
            if st and st.output_text:
                try:
                    # Strip frontmatter if present
                    text = st.output_text
                    if text.startswith("---"):
                        parts = text.split("---")
                        if len(parts) >= 3:
                            text = "---".join(parts[2:])
                    ns = NarrativeState.from_yaml(text)
                    prior_states.append(ns)
                except Exception as e:
                    logger.error("Failed to parse NarrativeState for chapter %d: %s", idx+1, e)

        if prior_states:
            merged = NarrativeState.merge(prior_states)
            prior_parts.append(
                f"=== Narrative State (chapters 1-{current_idx}) ===\n{merged.to_yaml()}"
            )

        # 2. Close neighbor: full text of Chapter N-1 for target stage (or preceding draft/revise stage)
        if current_idx > 0:
            prev_ch = chapters[current_idx - 1]
            prev_text = None
            # Look for stage output, or revise, or draft
            for s in [stage, "revise", "draft"]:
                st = session.query(StageState).filter_by(document_node_id=prev_ch.id, stage=s).first()
                if st and st.output_text:
                    prev_text = st.output_text
                    break
            
            if prev_text:
                prior_parts.append(
                    f"=== Chapter {current_idx} full text ===\n{prev_text}"
                )

        prior_context = "\n\n".join(prior_parts) if prior_parts else ""

        # 3. Forward outlines (N+1, N+2) from project structure output
        forward_outlines = []
        struct_st = session.query(StageState).filter_by(document_node_id=project.id, stage="structure").first()
        if struct_st and struct_st.output_text:
            headers = re.findall(r'^##\s+(?:Segment|Part|Chapter)\s*\d+[:\s]*(.*)', struct_st.output_text, re.MULTILINE)
            for idx in range(current_idx + 1, min(current_idx + 3, len(headers))):
                forward_outlines.append(f"Segment {idx + 1}: {headers[idx].strip()}")
        
        forward_text = "\n".join(forward_outlines) if forward_outlines else ""

        # 4. Parent brief
        parent_brief = ""
        brief_st = session.query(StageState).filter_by(document_node_id=project.id, stage="brief").first()
        if brief_st and brief_st.output_text:
            parent_brief = brief_st.output_text

        return {
            "CHAPTER_INDEX": current_idx + 1,
            "TOTAL_CHAPTERS": len(chapters),
            "PRIOR_CONTEXT": prior_context,
            "FORWARD_OUTLINES": forward_text,
            "PARENT_BRIEF": parent_brief,
        }

workflow_engine = WorkflowEngine()
