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

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

# Matches YAML frontmatter between --- delimiters
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Stage → numeric prefix mapping for sorted file listing
_STAGE_PREFIXES = {
    "brief": "01", "outline": "02", "draft": "03",
    "review": "04", "revise": "05", "humanize": "06",
    "validate": "07", "polish": "08", "done": "09",
}


def _stage_filename(stage: str, suffix: str = ".md") -> str:
    """Return the prefixed filename for a stage file.

    Examples: _stage_filename("draft") → "03_draft.md"
              _stage_filename("draft", ".decision.md") → "03_draft.decision.md"
              _stage_filename("unknown") → "unknown.md"
    """
    prefix = _STAGE_PREFIXES.get(stage)
    if prefix:
        return f"{prefix}_{stage}{suffix}"
    return f"{stage}{suffix}"


@dataclass
class Piece:
    """A writing piece with metadata and stage tracking."""

    # Stage classification
    CONTENT_STAGES = {"draft", "revise", "humanize", "polish", "done"}
    STAGE_PREFIXES = _STAGE_PREFIXES  # delegate to module-level

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

    # Workflow state
    current_stage: str = "brief"
    created: str = ""
    updated: str = ""

    # Agent configuration
    agent_set: str = ""  # empty = auto-detect

    # Content (everything after the frontmatter of the CURRENT stage file)
    body: str = ""

    # File location
    _path: Path | None = field(default=None, repr=False)  # directory for new format, file for legacy
    _is_legacy: bool = field(default=False, repr=False)

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
        """List all stage files that exist for this piece."""
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
        """Save piece to disk. Returns the file path.

        New format: saves to output/<id>/<current_stage>.md + updates meta.yaml
        Legacy format: overwrites the single .md file
        """
        self.updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if self._is_legacy:
            # Legacy single-file format
            path = self._path or (output_dir or DEFAULT_OUTPUT_DIR) / f"{self.id}.md"
            path.write_text(self.to_markdown(), encoding="utf-8")
            self._path = path
            logger.info("Saved piece '%s' (legacy) to %s", self.title, path)
            return path

        # New directory-per-piece format
        base = output_dir or DEFAULT_OUTPUT_DIR
        d = base / self.id
        d.mkdir(parents=True, exist_ok=True)

        # Save stage file
        path = d / _stage_filename(self.current_stage)
        path.write_text(self.to_markdown(), encoding="utf-8")

        # Save/update meta.yaml
        meta_path = d / "meta.yaml"
        meta_data = self.to_frontmatter()
        meta_path.write_text(
            yaml.dump(meta_data, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        self._path = d
        logger.info("Saved piece '%s' stage '%s' to %s", self.title, self.current_stage, path)
        return path

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
        body=body,
        _path=path,
    )


def load_piece(path: Path) -> Piece:
    """Load a piece from a directory (new) or single file (legacy).

    New format: path is a directory with meta.yaml + <stage>.md files.
    meta.yaml is the source of truth for metadata and current_stage.
    Legacy format: path is a single .md file.
    """
    if path.is_dir():
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
    """List all pieces in the output directory.

    Scans for:
    - Directories containing .md files (new format)
    - Standalone .md files (legacy format, excludes template dirs)
    """
    base = output_dir or DEFAULT_OUTPUT_DIR
    if not base.exists():
        return []

    pieces = []
    seen_ids = set()

    # New format: directories
    for d in sorted(base.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and not d.name.startswith("_"):
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
            except (ValueError, yaml.YAMLError) as e:
                logger.warning("Skipping %s: %s", md_file.name, e)

    return pieces


def get_piece(piece_id: str, output_dir: Path | None = None) -> Piece | None:
    """Find a piece by ID."""
    for piece in list_pieces(output_dir):
        if piece.id == piece_id:
            return piece
    return None
