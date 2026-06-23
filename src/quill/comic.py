"""Comic — comics-style version generation from narrative text.

Takes a piece's content and produces a self-contained HTML comic page.
Uses an LLM to break the narrative into panels with:
- Scene descriptions (visual direction)
- Dialogue (speech bubbles)
- Narration (caption boxes)
- Emotional beats and visual cues

The output is a standalone HTML file with CSS-driven comic layout.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import jinja2
import yaml

from .llm import LLMClient
from .piece import Piece, _FRONTMATTER_RE, _stage_filename

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Jinja2 template loader
# ---------------------------------------------------------------------------

_TEMPLATE_LOADER = jinja2.PackageLoader("quill", "templates")
_TEMPLATE_ENV = jinja2.Environment(
    loader=_TEMPLATE_LOADER,
    autoescape=False,
)


@dataclass
class ComicPanel:
    """A single panel in the comic."""
    panel_number: int
    scene_description: str  # Visual direction for the scene
    dialogue: list[dict] = field(default_factory=list)  # [{"speaker": "", "text": ""}]
    narration: str = ""  # Caption/narrator text
    sound_effect: str = ""  # SFX text
    emotion: str = ""  # Emotional beat (e.g., "tension", "shock", "calm")
    transition: str = ""  # Panel transition hint (e.g., "cut to", "meanwhile")


@dataclass
class ComicPage:
    """A page of comic panels."""
    page_number: int
    title: str = ""
    panels: list[ComicPanel] = field(default_factory=list)


@dataclass
class ComicBook:
    """Full comic adaptation of a piece."""
    title: str
    pages: list[ComicPage] = field(default_factory=list)
    style: str = "manga"  # manga | western | noir
    raw_response: str = ""


# ---------------------------------------------------------------------------
# Panel extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are a comic book adaptation expert. Break the following narrative into comic panels.

RULES:
- Create 4-8 panels per page
- Each panel needs: scene description (visual direction), dialogue (if any), narration (if any)
- Preserve the story's key beats, emotional moments, and dialogue
- Scene descriptions should be specific and visual (camera angle, lighting, character expression)
- Adapt prose into speech bubbles — keep dialogue punchy and concise
- Use narration boxes for internal thoughts, time transitions, and atmosphere
- Mark emotional beats and sound effects where appropriate
- Aim for 2-4 pages total depending on content length

STYLE: {style}

PIECE TITLE: {title}
GENRE: {genre}
TONE: {tone}

CONTENT:
{content}

Respond with a JSON array of pages. Each page has a "title" and "panels" array.
Each panel object has:
- "scene": visual scene description (string)
- "dialogue": array of {{"speaker": "Name", "text": "line"}} objects
- "narration": narrator caption text (string, can be empty)
- "sfx": sound effect text (string, can be empty)
- "emotion": emotional beat keyword (string)
- "transition": transition to next panel (string, can be empty)

Example format:
[
  {{
    "title": "The Discovery",
    "panels": [
      {{
        "scene": "Close-up of hands trembling over a keyboard, screen glow illuminating a dark room",
        "dialogue": [{{"speaker": "Daniel", "text": "This can't be real..."}}, {{"speaker": "MapRunner", "text": "Check the stash!"}}],
        "narration": "The numbers didn't lie. But they didn't make sense either.",
        "sfx": "",
        "emotion": "shock",
        "transition": "cut to"
      }},
      {{
        "scene": "Wide shot of Discord chat scrolling rapidly, avatars flashing",
        "dialogue": [{{"speaker": "GoldFarmer_BG", "text": "My gold is GONE"}}],
        "narration": "",
        "sfx": "TAP TAP TAP",
        "emotion": "panic",
        "transition": ""
      }}
    ]
  }}
]

Respond ONLY with the JSON array. No markdown fences, no explanation."""


def _parse_comic_json(response: str) -> list[dict]:
    """Extract JSON pages from LLM response.

    Handles responses wrapped in ```json fences or bare JSON.
    """
    # Try fenced JSON block first
    m = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try bare JSON array — find the outermost [ ... ]
    bracket_start = response.find('[')
    bracket_end = response.rfind(']')
    if bracket_start != -1 and bracket_end > bracket_start:
        try:
            return json.loads(response[bracket_start:bracket_end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse comic JSON from LLM response")
    return []


def _pages_from_json(data: list[dict]) -> list[ComicPage]:
    """Convert parsed JSON into ComicPage objects."""
    pages = []
    for i, page_data in enumerate(data):
        panels = []
        for j, panel_data in enumerate(page_data.get("panels", [])):
            dialogue_raw = panel_data.get("dialogue", [])
            # Normalize dialogue — handle both string and dict formats
            dialogue = []
            for d in dialogue_raw:
                if isinstance(d, dict):
                    dialogue.append({
                        "speaker": d.get("speaker", "?"),
                        "text": d.get("text", ""),
                    })
                elif isinstance(d, str):
                    dialogue.append({"speaker": "", "text": d})

            panels.append(ComicPanel(
                panel_number=j + 1,
                scene_description=panel_data.get("scene", ""),
                dialogue=dialogue,
                narration=panel_data.get("narration", ""),
                sound_effect=panel_data.get("sfx", ""),
                emotion=panel_data.get("emotion", ""),
                transition=panel_data.get("transition", ""),
            ))

        pages.append(ComicPage(
            page_number=i + 1,
            title=page_data.get("title", f"Page {i + 1}"),
            panels=panels,
        ))
    return pages


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

EMOTION_COLORS = {
    "tension": "#ff6b6b",
    "shock": "#ffd93d",
    "fear": "#c56cf0",
    "anger": "#ff4757",
    "sadness": "#74b9ff",
    "joy": "#2ed573",
    "calm": "#a8e6cf",
    "mystery": "#6c5ce7",
    "panic": "#fd79a8",
    "surprise": "#ffeaa7",
    "neutral": "#dfe6e9",
}

SFX_FONTS = {
    "boom": ("IMPACT", 2.5),
    "crash": ("IMPACT", 2.2),
    "bang": ("IMPACT", 2.3),
    "whoosh": ("cursive", 2.0),
    "tap": ("monospace", 1.2),
    "click": ("monospace", 1.1),
    "default": ("cursive", 1.6),
}


def _preprocess_panel(panel: ComicPanel, style: str) -> dict:
    """Convert a ComicPanel into a dict of precomputed template values."""
    emotion_color = EMOTION_COLORS.get(panel.emotion.lower() if panel.emotion else "", "#dfe6e9")

    # SFX font lookup
    sfx_font, sfx_size = "cursive", 1.6
    if panel.sound_effect:
        sfx_lower = panel.sound_effect.lower()
        sfx_key = next((k for k in SFX_FONTS if k in sfx_lower), "default")
        sfx_font, sfx_size = SFX_FONTS[sfx_key]

    # Panel CSS class
    panel_class = "panel"
    if style == "noir":
        panel_class += " noir"
    elif style == "manga":
        panel_class += " manga"

    return {
        "panel_number": panel.panel_number,
        "scene_description": panel.scene_description,
        "dialogue": panel.dialogue,
        "narration": panel.narration,
        "sound_effect": panel.sound_effect,
        "emotion": panel.emotion,
        "transition": panel.transition,
        "emotion_color": emotion_color,
        "sfx_font": sfx_font,
        "sfx_size": sfx_size,
        "panel_class": panel_class,
    }


_PANEL_TEMPLATE = _TEMPLATE_ENV.from_string(
    '<div class="{{ panel.panel_class }}" style="border-left-color: {{ panel.emotion_color }}">\n'
    '    <div class="panel-number">#{{ panel.panel_number }}</div>\n'
    '{% if panel.narration %}\n'
    '    <div class="narration">{{ panel.narration }}</div>\n'
    '{% endif %}\n'
    '    <div class="scene-desc">{{ panel.scene_description }}</div>\n'
    '{% if panel.dialogue %}\n'
    '    <div class="dialogue-area">\n'
    '{% for d in panel.dialogue %}\n'
    '        <div class="bubble">{% if d.speaker %}<span class="speaker">{{ d.speaker }}</span>{% endif %}<span class="bubble-text">{{ d.text }}</span></div>\n'
    '{% endfor %}\n'
    '    </div>\n'
    '{% endif %}\n'
    '{% if panel.sound_effect %}\n'
    '    <div class="sfx" style="font-family:{{ panel.sfx_font }};font-size:{{ panel.sfx_size }}em">{{ panel.sound_effect }}</div>\n'
    '{% endif %}\n'
    '{% if panel.transition %}\n'
    '    <div class="transition">▸ {{ panel.transition }}</div>\n'
    '{% endif %}\n'
    '</div>'
)


def _render_panel_html(panel: ComicPanel, style: str) -> str:
    """Render a single panel to HTML."""
    return _PANEL_TEMPLATE.render(panel=_preprocess_panel(panel, style))


def _render_comic_html(comic: ComicBook) -> str:
    """Render the full comic as a self-contained HTML page."""
    # Preprocess pages with grid classes and panel dicts
    pages = []
    for page in comic.pages:
        count = len(page.panels)
        grid_class = "page-panels"
        if count <= 2:
            grid_class += " grid-1x2"
        elif count <= 4:
            grid_class += " grid-2x2"
        elif count <= 6:
            grid_class += " grid-2x3"
        else:
            grid_class += " grid-3x3"

        pages.append({
            "title": page.title,
            "grid_class": grid_class,
            "panels": [_preprocess_panel(p, comic.style) for p in page.panels],
        })

    style_label = {
        "manga": "📖 Manga Style",
        "western": "🦸 Western Style",
        "noir": "🕵️ Noir Style",
    }.get(comic.style, "Comic")

    total_panels = sum(len(p.panels) for p in comic.pages)

    template = _TEMPLATE_ENV.get_template("comic.html")
    return template.render(
        title=comic.title,
        style_label=style_label,
        pages=pages,
        total_panels=total_panels,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_comic(piece: Piece, stage: str | None = None,
                   style: str = "manga", api_base: str | None = None,
                   api_key: str | None = None, model: str | None = None,
                   temperature: float = 0.7, max_tokens: int = 8192) -> ComicBook:
    """Generate a comic adaptation of a piece.

    Args:
        piece: The piece to adapt.
        stage: Which stage to use (default: current stage or latest with content).
        style: Comic style — "manga", "western", or "noir".
        api_base: LLM API base URL.
        api_key: LLM API key.
        model: LLM model name.
        temperature: LLM temperature.
        max_tokens: LLM max tokens.

    Returns:
        ComicBook with parsed pages and panels.

    Raises:
        ValueError: If no content found or LLM call fails.
    """
    # Find content to adapt
    stage_dir = piece.stage_dir()
    target_stage = stage or piece.current_stage

    # Try the target stage, then fall back to any stage with content
    content = ""
    for try_stage in [target_stage, "done", "polish", "humanize", "revise", "draft"]:
        stage_file = stage_dir / _stage_filename(try_stage)
        if stage_file.exists():
            text = stage_file.read_text(encoding="utf-8")
            m = _FRONTMATTER_RE.match(text)
            content = text[m.end():] if m else text
            if content.strip():
                break

    if not content.strip():
        raise ValueError("No content found to adapt into comic")

    # Truncate very long content to fit in LLM context
    max_chars = 30000
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[Content truncated for comic adaptation...]"

    # Load model config if not provided
    if not api_base or not model:
        from .agent import load_model_config
        cfg = load_model_config()
        api_base = api_base or cfg.get("api_base", "https://api.openai.com/v1")
        api_key = api_key or cfg.get("api_key", "")
        model = model or cfg.get("model", "gpt-4o")

    # Call LLM
    prompt = EXTRACTION_PROMPT.format(
        style=style,
        title=piece.title,
        genre=piece.genre or "general",
        tone=piece.tone or "neutral",
        content=content,
    )

    client = LLMClient(
        api_base=api_base,
        api_key=api_key or "",
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    response = client.chat(
        system="You are a comic book adaptation expert. Respond only with valid JSON.",
        user=prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # Parse response
    pages_data = _parse_comic_json(response)
    if not pages_data:
        raise ValueError("LLM did not return valid comic panel data")

    pages = _pages_from_json(pages_data)

    return ComicBook(
        title=piece.title,
        pages=pages,
        style=style,
        raw_response=response,
    )


def generate_comic_html(piece: Piece, stage: str | None = None,
                        style: str = "manga", **kwargs) -> str:
    """Generate comic and return self-contained HTML string."""
    import os
    api_key = kwargs.pop("api_key", None) or os.environ.get("QUILL_API_KEY", "")
    comic = generate_comic(piece, stage=stage, style=style, api_key=api_key, **kwargs)
    return _render_comic_html(comic)


def save_comic_html(piece: Piece, html: str) -> Path:
    """Save generated comic HTML to the piece's directory.

    Returns the path to the saved file.
    """
    output_dir = piece.stage_dir() / "comic"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "comic.html"
    output_file.write_text(html, encoding="utf-8")
    logger.info("Saved comic to %s", output_file)
    return output_file
