"""Command-line interface commands for Quill database sync."""

from __future__ import annotations

import os
import click
import yaml
from datetime import datetime
from pathlib import Path
from flask.cli import with_appcontext

from .db import db_session
from .models import Project, DocumentNode, StageState, Metrics, utc_now
from .piece import DEFAULT_OUTPUT_DIR, _stage_filename, _FRONTMATTER_RE
from .metrics import compute_metrics


@click.command("sync-legacy")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Force updating existing database records from filesystem.",
)
@with_appcontext
def sync_legacy_command(force: bool):
    """Import existing pieces from output/ directory into SQL database."""
    click.echo("Starting database sync from output/ directory...")

    if not DEFAULT_OUTPUT_DIR.exists():
        click.echo("Output directory does not exist. Nothing to sync.")
        return

    pieces_to_sync = []

    for entry in DEFAULT_OUTPUT_DIR.iterdir():
        if entry.is_dir():
            meta_file = entry / "meta.yaml"
            if meta_file.exists():
                try:
                    meta = yaml.safe_load(meta_file.read_text(encoding="utf-8")) or {}
                    pieces_to_sync.append((meta, entry, False))
                except Exception as e:
                    click.echo(f"Skipping directory '{entry.name}': invalid meta.yaml ({e})")
        elif entry.is_file() and entry.suffix == ".md":
            # Skip any temporary files, backup files, or standard files
            if entry.name.startswith(".") or entry.name in ("README.md", "TODO.md"):
                continue
            try:
                text = entry.read_text(encoding="utf-8")
                # Parse frontmatter to check if it's a valid legacy piece
                m = _FRONTMATTER_RE.match(text)
                if m:
                    meta = yaml.safe_load(m.group(1)) or {}
                    pieces_to_sync.append((meta, entry, True))
            except Exception as e:
                click.echo(f"Skipping legacy file '{entry.name}': {e}")

    # Sort pieces: projects first (no parent key or parent empty), then child nodes (chapters/scenes)
    pieces_to_sync.sort(key=lambda x: 1 if x[0].get("parent") else 0)

    session = db_session()
    imported_count = 0
    skipped_count = 0

    for meta, path, is_legacy in pieces_to_sync:
        piece_id = meta.get("id") or (path.stem if is_legacy else path.name)

        # 1. Safety check: skip if actively generating in the database
        active_generating = (
            session.query(StageState)
            .filter_by(document_node_id=piece_id, state="generating")
            .first()
        )
        if active_generating:
            click.echo(f"Skipping active piece '{piece_id}' (currently generating/running).")
            skipped_count += 1
            continue

        # 2. Deduplication check
        existing_project = session.query(Project).filter_by(id=piece_id).first()
        existing_node = session.query(DocumentNode).filter_by(id=piece_id).first()

        exists_in_db = (existing_project is not None) or (existing_node is not None)
        if exists_in_db and not force:
            click.echo(f"Piece '{piece_id}' already exists in database. Skipping.")
            skipped_count += 1
            continue

        # 3. Create or update Project/DocumentNode
        title = meta.get("title") or piece_id
        parent_id = meta.get("parent", "")
        is_child = bool(parent_id)
        current_stage = meta.get("current_stage", "brief")

        try:
            if not is_child:
                # Top-level Project
                project = session.query(Project).filter_by(id=piece_id).first()
                if not project:
                    project = Project(id=piece_id)
                    session.add(project)

                project.title = title
                project.genre = meta.get("genre", "")
                project.type = meta.get("type", "")
                project.audience = meta.get("audience", "")
                project.tone = meta.get("tone", "")
                project.language = meta.get("language", "")
                project.target_length = meta.get("target_length", "")
                project.constraints = meta.get("constraints", []) or []
                project.current_stage = current_stage
                project.agent_set = meta.get("agent_set", "")
                project.trigger = meta.get("trigger", "on_advance")

                created_str = meta.get("created", "")
                if created_str:
                    try:
                        project.created_at = datetime.strptime(created_str, "%Y-%m-%d")
                    except Exception:
                        pass

                updated_str = meta.get("updated", "")
                if updated_str:
                    try:
                        project.updated_at = datetime.strptime(updated_str, "%Y-%m-%d")
                    except Exception:
                        pass
                else:
                    project.updated_at = utc_now()

                # Project DocumentNode
                node = session.query(DocumentNode).filter_by(id=piece_id).first()
                if not node:
                    node = DocumentNode(
                        id=piece_id,
                        project_id=piece_id,
                        parent_id=None,
                        node_type="project",
                    )
                    session.add(node)
                node.title = title
                node.updated_at = project.updated_at
            else:
                # Child DocumentNode
                node = session.query(DocumentNode).filter_by(id=piece_id).first()
                if not node:
                    node = DocumentNode(
                        id=piece_id,
                        project_id=parent_id,
                        parent_id=parent_id,
                        node_type="chapter",
                    )
                    session.add(node)
                node.title = title
                updated_str = meta.get("updated", "")
                if updated_str:
                    try:
                        node.updated_at = datetime.strptime(updated_str, "%Y-%m-%d")
                    except Exception:
                        pass
                else:
                    node.updated_at = utc_now()

            # 4. Parse stages and metrics
            if is_legacy:
                # Legacy only has current stage
                text = path.read_text(encoding="utf-8")
                m = _FRONTMATTER_RE.match(text)
                body_content = text[m.end() :] if m else text

                # Save StageState
                st_state = (
                    session.query(StageState)
                    .filter_by(document_node_id=piece_id, stage=current_stage)
                    .first()
                )
                if not st_state:
                    st_state = StageState(
                        document_node_id=piece_id,
                        stage=current_stage,
                    )
                    session.add(st_state)
                st_state.state = meta.get("stage_states", {}).get(current_stage, "ready")
                st_state.body = body_content
                st_state.loop_count = meta.get("loops", {}).get(current_stage, 0)
                st_state.updated_at = node.updated_at

                # Compute metrics
                try:
                    metrics_data = compute_metrics(body_content)
                    metric = (
                        session.query(Metrics)
                        .filter_by(document_node_id=piece_id, stage=current_stage, label="current")
                        .first()
                    )
                    if not metric:
                        metric = Metrics(
                            document_node_id=piece_id,
                            stage=current_stage,
                            label="current",
                        )
                        session.add(metric)
                    metric.flesch_ease = metrics_data.get("flesch_ease", 0.0)
                    metric.flesch_kincaid = metrics_data.get("flesch_kincaid", 0.0)
                    metric.word_count = metrics_data.get("word_count", 0)
                    metric.sentence_count = metrics_data.get("sentence_count", 0)
                    metric.avg_sentence_length = metrics_data.get("avg_sentence_length", 0.0)
                    metric.type_token_ratio = metrics_data.get("type_token_ratio", 0.0)
                    metric.passive_voice_pct = metrics_data.get("passive_voice_pct", 0.0)
                    metric.updated_at = node.updated_at
                except Exception as e:
                    click.echo(f"Could not compute metrics for legacy piece {piece_id}: {e}")
            else:
                # Directory format: parse all stage files
                stage_files = sorted(path.glob("*.md"))
                for f in stage_files:
                    name = f.name
                    if ".decision." in name or ".metrics." in name:
                        continue
                    if (
                        ".generate-prompt." in name
                        or ".evaluate-prompt." in name
                        or "-prompt.md" in name
                    ):
                        continue
                    if f.name in ("meta.yaml", "run-log.jsonl"):
                        continue

                    stem = f.stem
                    if len(stem) > 2 and stem[0:2].isdigit() and stem[2] == "_":
                        stage_name = stem[3:]
                    else:
                        stage_name = stem

                    # Read content
                    text = f.read_text(encoding="utf-8")
                    m = _FRONTMATTER_RE.match(text)
                    body_content = text[m.end() :] if m else text

                    # Loop count and state
                    loops = meta.get("loops", {}) or {}
                    loop_count = loops.get(stage_name, 0)
                    stage_states = meta.get("stage_states", {}) or {}
                    state_val = stage_states.get(stage_name, "ready")

                    # Parse decision/critique if exists
                    prefix = (
                        f.name.split("_")[0]
                        if "_" in f.name and f.name.split("_")[0].isdigit()
                        else ""
                    )
                    decision_filename = (
                        f"{prefix}_{stage_name}.decision.md" if prefix else f"{stage_name}.decision.md"
                    )
                    metrics_filename = (
                        f"{prefix}_{stage_name}.metrics.yaml" if prefix else f"{stage_name}.metrics.yaml"
                    )

                    decision_file = path / decision_filename
                    decision_val = None
                    critique_val = None
                    if decision_file.exists():
                        dec_text = decision_file.read_text(encoding="utf-8")
                        import re

                        dec_match = re.search(r"^## Decision:\s*(.*?)$", dec_text, re.MULTILINE)
                        if dec_match:
                            decision_val = dec_match.group(1).strip()
                        crit_match = re.search(
                            r"^## Critique\s*\n(.*)$", dec_text, re.DOTALL | re.MULTILINE
                        )
                        if crit_match:
                            critique_val = crit_match.group(1).strip()

                    # Save StageState
                    st_state = (
                        session.query(StageState)
                        .filter_by(document_node_id=piece_id, stage=stage_name)
                        .first()
                    )
                    if not st_state:
                        st_state = StageState(
                            document_node_id=piece_id,
                            stage=stage_name,
                        )
                        session.add(st_state)
                    st_state.state = state_val
                    st_state.loop_count = loop_count
                    st_state.body = body_content
                    st_state.decision = decision_val
                    st_state.critique = critique_val
                    st_state.updated_at = utc_now()

                    # Parse or compute metrics
                    metrics_file = path / metrics_filename
                    metrics_data = None
                    if metrics_file.exists():
                        try:
                            metrics_data = yaml.safe_load(metrics_file.read_text(encoding="utf-8"))
                        except Exception:
                            pass

                    if not metrics_data:
                        try:
                            metrics_data = compute_metrics(body_content)
                        except Exception:
                            pass

                    if metrics_data:
                        metric = (
                            session.query(Metrics)
                            .filter_by(document_node_id=piece_id, stage=stage_name, label="current")
                            .first()
                        )
                        if not metric:
                            metric = Metrics(
                                document_node_id=piece_id,
                                stage=stage_name,
                                label="current",
                            )
                            session.add(metric)
                        metric.flesch_ease = metrics_data.get("flesch_ease", 0.0)
                        metric.flesch_kincaid = metrics_data.get("flesch_kincaid", 0.0)
                        metric.word_count = metrics_data.get("word_count", 0)
                        metric.sentence_count = metrics_data.get("sentence_count", 0)
                        metric.avg_sentence_length = metrics_data.get("avg_sentence_length", 0.0)
                        metric.type_token_ratio = metrics_data.get("type_token_ratio", 0.0)
                        metric.passive_voice_pct = metrics_data.get("passive_voice_pct", 0.0)
                        metric.updated_at = utc_now()

            session.commit()
            click.echo(f"Successfully synced piece '{piece_id}' ('{title}').")
            imported_count += 1
        except Exception as e:
            session.rollback()
            click.echo(f"Failed to sync piece '{piece_id}': {e}")

    click.echo(f"Sync complete. Synced: {imported_count}, Skipped: {skipped_count}.")
