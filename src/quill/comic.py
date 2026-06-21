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

import yaml

from .llm import LLMClient
from .piece import Piece, _FRONTMATTER_RE

logger = logging.getLogger(__name__)


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


def _render_panel_html(panel: ComicPanel, style: str) -> str:
    """Render a single panel to HTML."""
    emotion_color = EMOTION_COLORS.get(panel.emotion.lower() if panel.emotion else "", "#dfe6e9")

    # Scene description
    scene_html = f'<div class="scene-desc">{panel.scene_description}</div>'

    # Narration box
    narration_html = ""
    if panel.narration:
        narration_html = f'<div class="narration">{panel.narration}</div>'

    # Sound effect
    sfx_html = ""
    if panel.sound_effect:
        sfx_lower = panel.sound_effect.lower()
        sfx_key = next((k for k in SFX_FONTS if k in sfx_lower), "default")
        font_family, size = SFX_FONTS[sfx_key]
        sfx_html = f'<div class="sfx" style="font-family:{font_family};font-size:{size}em">{panel.sound_effect}</div>'

    # Dialogue bubbles
    dialogue_html = ""
    if panel.dialogue:
        bubbles = []
        for d in panel.dialogue:
            speaker = d.get("speaker", "")
            text = d.get("text", "")
            speaker_tag = f'<span class="speaker">{speaker}</span>' if speaker else ""
            bubbles.append(f'<div class="bubble">{speaker_tag}<span class="bubble-text">{text}</span></div>')
        dialogue_html = '<div class="dialogue-area">' + "".join(bubbles) + '</div>'

    # Transition hint
    transition_html = ""
    if panel.transition:
        transition_html = f'<div class="transition">▸ {panel.transition}</div>'

    # Style variants
    panel_class = "panel"
    if style == "noir":
        panel_class += " noir"
    elif style == "manga":
        panel_class += " manga"

    return f'''<div class="{panel_class}" style="border-left-color: {emotion_color}">
    <div class="panel-number">#{panel.panel_number}</div>
    {narration_html}
    {scene_html}
    {dialogue_html}
    {sfx_html}
    {transition_html}
</div>'''


def _render_comic_html(comic: ComicBook) -> str:
    """Render the full comic as a self-contained HTML page."""
    pages_html = ""
    for page in comic.pages:
        panels_html = "\n".join(_render_panel_html(p, comic.style) for p in page.panels)
        grid_class = "page-panels"
        # Adjust grid based on panel count
        count = len(page.panels)
        if count <= 2:
            grid_class += " grid-1x2"
        elif count <= 4:
            grid_class += " grid-2x2"
        elif count <= 6:
            grid_class += " grid-2x3"
        else:
            grid_class += " grid-3x3"

        pages_html += f'''
<div class="comic-page">
    <div class="page-title">— {page.title} —</div>
    <div class="{grid_class}">
        {panels_html}
    </div>
</div>'''

    style_label = {"manga": "📖 Manga Style", "western": "🦸 Western Style", "noir": "🕵️ Noir Style"}.get(comic.style, "Comic")

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{comic.title} — Comic Adaptation</title>
<style>
:root {{
    --bg: #1a1a2e;
    --panel-bg: #16213e;
    --border: #0f3460;
    --text: #e8e8e8;
    --text-muted: #8899aa;
    --accent: #e94560;
    --bubble-bg: #ffffff;
    --bubble-text: #1a1a2e;
    --narration-bg: #0f3460;
    --narration-text: #e8e8e8;
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    padding: 20px;
    max-width: 1100px;
    margin: 0 auto;
}}

.comic-header {{
    text-align: center;
    padding: 30px 0;
    border-bottom: 2px solid var(--border);
    margin-bottom: 30px;
}}
.comic-header h1 {{
    font-size: 2em;
    color: var(--accent);
    margin-bottom: 8px;
    text-transform: uppercase;
    letter-spacing: 2px;
}}
.comic-header .subtitle {{
    color: var(--text-muted);
    font-size: 0.9em;
}}

.comic-page {{
    margin-bottom: 40px;
    border: 2px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    background: rgba(15, 52, 96, 0.2);
}}
.page-title {{
    text-align: center;
    color: var(--text-muted);
    font-size: 0.85em;
    margin-bottom: 16px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

/* Grid layouts */
.page-panels {{
    display: grid;
    gap: 12px;
}}
.grid-1x2 {{ grid-template-columns: 1fr; }}
.grid-2x2 {{ grid-template-columns: 1fr 1fr; }}
.grid-2x3 {{ grid-template-columns: 1fr 1fr; }}
.grid-3x3 {{ grid-template-columns: 1fr 1fr 1fr; }}

@media (max-width: 700px) {{
    .grid-2x2, .grid-2x3, .grid-3x3 {{ grid-template-columns: 1fr; }}
}}

/* Panel */
.panel {{
    background: var(--panel-bg);
    border: 2px solid var(--border);
    border-left: 4px solid var(--accent);
    border-radius: 8px;
    padding: 14px;
    position: relative;
    min-height: 120px;
    overflow: hidden;
}}
.panel.noir {{
    background: #0a0a0a;
    border-color: #333;
    color: #ccc;
}}
.panel.manga {{
    background: #fff;
    border-color: #000;
    color: #000;
    --bubble-bg: #fff;
    --bubble-text: #000;
    --narration-bg: #f0f0f0;
    --narration-text: #333;
}}

.panel-number {{
    position: absolute;
    top: 4px;
    left: 8px;
    font-size: 0.7em;
    color: var(--text-muted);
    opacity: 0.6;
}}

.scene-desc {{
    font-style: italic;
    color: var(--text-muted);
    font-size: 0.85em;
    margin-bottom: 10px;
    line-height: 1.4;
    padding-left: 20px;
}}

.narration {{
    background: var(--narration-bg);
    color: var(--narration-text);
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 0.85em;
    font-style: italic;
    margin-bottom: 10px;
    border-left: 3px solid var(--accent);
    line-height: 1.5;
}}

.dialogue-area {{
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 8px;
}}
.bubble {{
    background: var(--bubble-bg);
    color: var(--bubble-text);
    padding: 8px 12px;
    border-radius: 12px;
    border-bottom-left-radius: 4px;
    max-width: 85%;
    font-size: 0.9em;
    line-height: 1.4;
    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
}}
.bubble:nth-child(even) {{
    align-self: flex-end;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 4px;
}}
.speaker {{
    font-weight: bold;
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: block;
    margin-bottom: 2px;
    color: var(--accent);
}}
.bubble-text {{ }}

.sfx {{
    text-align: center;
    color: var(--accent);
    font-weight: bold;
    text-transform: uppercase;
    margin: 8px 0;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
    letter-spacing: 3px;
}}

.transition {{
    font-size: 0.7em;
    color: var(--text-muted);
    text-align: right;
    margin-top: 6px;
    font-style: italic;
}}

.footer {{
    text-align: center;
    padding: 20px 0;
    color: var(--text-muted);
    font-size: 0.8em;
    border-top: 1px solid var(--border);
    margin-top: 20px;
}}

/* Print styles */
@media print {{
    body {{ background: #fff; color: #000; padding: 10px; }}
    .panel {{ border-color: #000; background: #fff; color: #000; break-inside: avoid; }}
    .comic-page {{ border-color: #000; break-after: page; }}
    .bubble {{ box-shadow: none; border: 1px solid #000; }}
}}
</style>
</head>
<body>

<div class="comic-header">
    <h1>{comic.title}</h1>
    <div class="subtitle">{style_label} Adaptation • {len(comic.pages)} page{"s" if len(comic.pages) != 1 else ""} • {sum(len(p.panels) for p in comic.pages)} panels</div>
</div>

{pages_html}

<div class="footer">
    Generated by Quill Comic Engine • <a href="javascript:window.print()" style="color:var(--accent)">🖨️ Print / Save as PDF</a>
</div>

</body>
</html>'''


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
        stage_file = stage_dir / f"{try_stage}.md"
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
