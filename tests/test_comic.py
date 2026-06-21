"""Tests for comic generation module."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from quill.comic import (
    ComicPanel, ComicPage, ComicBook,
    _parse_comic_json, _pages_from_json, _render_panel_html, _render_comic_html,
    generate_comic, generate_comic_html, save_comic_html,
)
from quill.piece import load_piece


# ---------------------------------------------------------------------------
# JSON parsing tests
# ---------------------------------------------------------------------------


class TestParseComicJson:
    """Tests for _parse_comic_json."""

    def test_parse_fenced_json(self):
        response = '''```json
[
  {
    "title": "Page 1",
    "panels": [
      {"scene": "A dark room", "dialogue": [], "narration": "It was dark.", "sfx": "", "emotion": "mystery", "transition": ""}
    ]
  }
]
```'''
        result = _parse_comic_json(response)
        assert len(result) == 1
        assert result[0]["title"] == "Page 1"
        assert len(result[0]["panels"]) == 1

    def test_parse_bare_json(self):
        response = '''[
  {"title": "The Beginning", "panels": [
    {"scene": "Wide shot of city", "dialogue": [{"speaker": "Hero", "text": "Let's go"}], "narration": "", "sfx": "WHOOSH", "emotion": "excitement", "transition": "cut to"}
  ]}
]'''
        result = _parse_comic_json(response)
        assert len(result) == 1
        assert result[0]["panels"][0]["dialogue"][0]["speaker"] == "Hero"

    def test_parse_invalid_returns_empty(self):
        result = _parse_comic_json("This is not JSON at all.")
        assert result == []

    def test_parse_json_with_extra_text(self):
        response = '''Here is the comic adaptation:
[
  {"title": "P1", "panels": [
    {"scene": "Test", "dialogue": [], "narration": "", "sfx": "", "emotion": "", "transition": ""}
  ]}
]
Hope this helps!'''
        result = _parse_comic_json(response)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Page model tests
# ---------------------------------------------------------------------------


class TestPagesFromJson:
    """Tests for _pages_from_json."""

    def test_basic_conversion(self):
        data = [
            {
                "title": "The Chase",
                "panels": [
                    {
                        "scene": "Runner sprinting through alley",
                        "dialogue": [{"speaker": "Runner", "text": "Almost there!"}],
                        "narration": "The chase had gone on for hours.",
                        "sfx": "THUD THUD",
                        "emotion": "tension",
                        "transition": "cut to",
                    },
                    {
                        "scene": "Dead end wall",
                        "dialogue": [],
                        "narration": "",
                        "sfx": "",
                        "emotion": "shock",
                        "transition": "",
                    },
                ],
            }
        ]
        pages = _pages_from_json(data)
        assert len(pages) == 1
        assert pages[0].title == "The Chase"
        assert len(pages[0].panels) == 2

        p1 = pages[0].panels[0]
        assert p1.panel_number == 1
        assert "Runner" in p1.scene_description
        assert len(p1.dialogue) == 1
        assert p1.dialogue[0]["speaker"] == "Runner"
        assert p1.narration == "The chase had gone on for hours."
        assert p1.sound_effect == "THUD THUD"
        assert p1.emotion == "tension"
        assert p1.transition == "cut to"

        p2 = pages[0].panels[1]
        assert p2.panel_number == 2
        assert p2.emotion == "shock"

    def test_string_dialogue_normalized(self):
        data = [
            {
                "title": "P1",
                "panels": [
                    {
                        "scene": "Test",
                        "dialogue": ["Just a string"],
                        "narration": "",
                        "sfx": "",
                        "emotion": "",
                        "transition": "",
                    }
                ],
            }
        ]
        pages = _pages_from_json(data)
        assert pages[0].panels[0].dialogue[0]["speaker"] == ""
        assert pages[0].panels[0].dialogue[0]["text"] == "Just a string"

    def test_empty_pages(self):
        pages = _pages_from_json([])
        assert pages == []


# ---------------------------------------------------------------------------
# HTML rendering tests
# ---------------------------------------------------------------------------


class TestHtmlRendering:
    """Tests for HTML generation."""

    def test_panel_html_contains_scene(self):
        panel = ComicPanel(
            panel_number=1,
            scene_description="A character stands in doorway",
            dialogue=[{"speaker": "Hero", "text": "Hello"}],
            narration="The moment of truth.",
            sound_effect="CREAK",
            emotion="tension",
            transition="cut to",
        )
        html = _render_panel_html(panel, "manga")
        assert "A character stands in doorway" in html
        assert "Hero" in html
        assert "Hello" in html
        assert "The moment of truth." in html
        assert "CREAK" in html
        assert "#ff6b6b" in html  # tension color

    def test_panel_html_manga_class(self):
        panel = ComicPanel(panel_number=1, scene_description="test")
        html = _render_panel_html(panel, "manga")
        assert "manga" in html

    def test_panel_html_noir_class(self):
        panel = ComicPanel(panel_number=1, scene_description="test")
        html = _render_panel_html(panel, "noir")
        assert "noir" in html

    def test_panel_html_western_no_special_class(self):
        panel = ComicPanel(panel_number=1, scene_description="test")
        html = _render_panel_html(panel, "western")
        assert "manga" not in html
        assert "noir" not in html

    def test_full_comic_html(self):
        comic = ComicBook(
            title="Test Comic",
            pages=[
                ComicPage(
                    page_number=1,
                    title="Opening",
                    panels=[
                        ComicPanel(panel_number=1, scene_description="Dark alley", emotion="mystery"),
                        ComicPanel(panel_number=2, scene_description="Close-up of eyes", emotion="tension"),
                    ],
                ),
            ],
            style="noir",
        )
        html = _render_comic_html(comic)
        assert "Test Comic" in html
        assert "Opening" in html
        assert "Dark alley" in html
        assert "Close-up of eyes" in html
        assert "Noir Style" in html
        assert "1 page" in html
        assert "2 panels" in html
        assert "<!DOCTYPE html>" in html

    def test_comic_html_multiple_pages(self):
        comic = ComicBook(
            title="Multi-page",
            pages=[
                ComicPage(page_number=1, title="P1", panels=[
                    ComicPanel(panel_number=1, scene_description="Scene 1"),
                ]),
                ComicPage(page_number=2, title="P2", panels=[
                    ComicPanel(panel_number=1, scene_description="Scene 2"),
                ]),
            ],
            style="manga",
        )
        html = _render_comic_html(comic)
        assert "2 pages" in html
        assert "P1" in html
        assert "P2" in html

    def test_grid_class_selection(self):
        """Grid class should adapt to panel count."""
        comic = ComicBook(
            title="Test",
            pages=[
                ComicPage(page_number=1, title="2 panels", panels=[
                    ComicPanel(panel_number=1, scene_description="A"),
                    ComicPanel(panel_number=2, scene_description="B"),
                ]),
            ],
            style="western",
        )
        html = _render_comic_html(comic)
        assert "grid-1x2" in html  # 2 panels → 1x2 grid

    def test_empty_dialogue_panel(self):
        """Panel with no dialogue should not have dialogue-area div."""
        panel = ComicPanel(panel_number=1, scene_description="Silent scene")
        html = _render_panel_html(panel, "western")
        assert "dialogue-area" not in html
        assert "bubble" not in html

    def test_print_css_included(self):
        comic = ComicBook(
            title="Print Test",
            pages=[ComicPage(page_number=1, title="P1", panels=[])],
            style="manga",
        )
        html = _render_comic_html(comic)
        assert "@media print" in html
        assert "window.print()" in html


# ---------------------------------------------------------------------------
# generate_comic tests (with mocked LLM)
# ---------------------------------------------------------------------------


class TestGenerateComic:
    """Tests for generate_comic with mocked LLM."""

    MOCK_LLM_RESPONSE = json.dumps([
        {
            "title": "The Discovery",
            "panels": [
                {
                    "scene": "Person at computer screen, face illuminated",
                    "dialogue": [{"speaker": "Alex", "text": "This changes everything."}],
                    "narration": "It started with a single message.",
                    "sfx": "",
                    "emotion": "shock",
                    "transition": "meanwhile",
                },
                {
                    "scene": "Chat window scrolling rapidly",
                    "dialogue": [{"speaker": "Bot", "text": "Gold is gone."}],
                    "narration": "",
                    "sfx": "TAP TAP",
                    "emotion": "panic",
                    "transition": "",
                },
            ],
        }
    ])

    def test_generate_comic_from_piece(self, sample_piece, tmp_agents):
        """Test comic generation with mocked LLM."""
        piece = load_piece(sample_piece)

        mock_response = self.MOCK_LLM_RESPONSE

        with patch("quill.comic.LLMClient") as MockClient:
            instance = MockClient.return_value
            instance.chat.return_value = mock_response

            comic = generate_comic(
                piece,
                stage="draft",
                style="manga",
                api_base="http://localhost:9999/v1",
                api_key="test",
                model="test-model",
            )

        assert comic.title == "Test Piece"
        assert comic.style == "manga"
        assert len(comic.pages) == 1
        assert len(comic.pages[0].panels) == 2
        assert comic.pages[0].panels[0].emotion == "shock"
        assert comic.pages[0].panels[1].sound_effect == "TAP TAP"

    def test_generate_comic_no_content_raises(self, tmp_output, tmp_agents):
        """Comic generation with empty piece should raise ValueError."""
        piece_dir = tmp_output / "empty-piece"
        piece_dir.mkdir()
        (piece_dir / "meta.yaml").write_text("id: empty\ncurrent_stage: brief\n")
        # Proper frontmatter with genuinely empty body
        (piece_dir / "brief.md").write_text("---\nid: empty\ntitle: Empty\ncurrent_stage: brief\n---\n\n")

        piece = load_piece(piece_dir)

        with pytest.raises(ValueError, match="No content found"):
            generate_comic(piece, api_base="http://localhost:9999/v1", api_key="test")

    def test_generate_comic_llm_returns_invalid_json(self, sample_piece, tmp_agents):
        """LLM returning garbage should raise ValueError."""
        piece = load_piece(sample_piece)

        with patch("quill.comic.LLMClient") as MockClient:
            MockClient.return_value.chat.return_value = "Sorry, I can't do that."

            with pytest.raises(ValueError, match="did not return valid"):
                generate_comic(
                    piece,
                    stage="draft",
                    api_base="http://localhost:9999/v1",
                    api_key="test",
                )

    def test_save_comic_html(self, sample_piece):
        """Test saving comic HTML to piece directory."""
        piece = load_piece(sample_piece)
        html = "<html><body>Test comic</body></html>"
        path = save_comic_html(piece, html)

        assert path.exists()
        assert path.name == "comic.html"
        assert "comic" in str(path)
        assert path.read_text(encoding="utf-8") == html

    def test_comic_saved_in_subdirectory(self, sample_piece):
        """Comic should be saved in a comic/ subdirectory."""
        piece = load_piece(sample_piece)
        path = save_comic_html(piece, "<html></html>")
        assert path.parent.name == "comic"
        assert str(piece.stage_dir()) in str(path)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestComicEdgeCases:
    """Edge case tests."""

    def test_panel_with_many_dialogue_bubbles(self):
        panel = ComicPanel(
            panel_number=1,
            scene_description="Crowded bar",
            dialogue=[
                {"speaker": "A", "text": "Hey"},
                {"speaker": "B", "text": "What"},
                {"speaker": "C", "text": "Listen"},
                {"speaker": "A", "text": "No"},
            ],
        )
        html = _render_panel_html(panel, "western")
        assert html.count("bubble") >= 4

    def test_special_characters_in_text(self):
        """HTML special chars should be in output (they're in divs, not attributes)."""
        panel = ComicPanel(
            panel_number=1,
            scene_description='He said "hello" & <goodbye>',
            dialogue=[{"speaker": "X", "text": "Tom & Jerry"}],
        )
        html = _render_panel_html(panel, "manga")
        # The text appears in divs — browser handles escaping via textContent
        assert "hello" in html
        assert "Tom" in html

    def test_very_long_narration(self):
        long_text = "word " * 500
        panel = ComicPanel(panel_number=1, scene_description="test", narration=long_text)
        html = _render_panel_html(panel, "western")
        assert long_text in html

    def test_comic_styles_all_render(self):
        for style in ("manga", "western", "noir"):
            comic = ComicBook(
                title="Style Test",
                pages=[ComicPage(page_number=1, title="P1", panels=[
                    ComicPanel(panel_number=1, scene_description="test")
                ])],
                style=style,
            )
            html = _render_comic_html(comic)
            assert "<!DOCTYPE html>" in html
            assert "Style Test" in html
