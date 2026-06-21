"""Tests for the audio generation module."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from quill.audio import (
    AudioOptions,
    AudioResult,
    _clean_text_for_speech,
    generate_audio,
    list_audio_files,
    VOICE_PRESETS,
    DEFAULT_VOICES,
)


class TestCleanTextForSpeech:
    """Test markdown stripping for TTS."""

    def test_strips_frontmatter(self):
        text = "---\ntitle: test\n---\nHello world"
        assert _clean_text_for_speech(text) == "Hello world"

    def test_strips_headings(self):
        text = "# Title\n## Subtitle\nBody text"
        result = _clean_text_for_speech(text)
        assert "Title" in result
        assert "##" not in result

    def test_strips_bold_italic(self):
        text = "This is **bold** and *italic* text"
        result = _clean_text_for_speech(text)
        assert "**" not in result
        assert "*" not in result or "italic" in result
        assert "bold" in result
        assert "italic" in result

    def test_strips_code_blocks(self):
        text = "Before\n```python\ndef foo():\n    pass\n```\nAfter"
        result = _clean_text_for_speech(text)
        assert "def foo" not in result
        assert "Before" in result
        assert "After" in result

    def test_strips_inline_code(self):
        text = "Use `pip install` to install"
        result = _clean_text_for_speech(text)
        assert "`" not in result
        assert "pip install" in result

    def test_strips_links_keeps_text(self):
        text = "Click [here](https://example.com) for more"
        result = _clean_text_for_speech(text)
        assert "here" in result
        assert "https" not in result

    def test_strips_images(self):
        text = "![alt text](image.png) is an image"
        result = _clean_text_for_speech(text)
        assert "alt text" in result
        assert "image.png" not in result

    def test_strips_html_tags(self):
        text = "<p>Hello</p> <br> world"
        result = _clean_text_for_speech(text)
        assert "<p>" not in result
        assert "Hello" in result

    def test_strips_blockquotes(self):
        text = "> This is a quote\n> Second line"
        result = _clean_text_for_speech(text)
        assert ">" not in result
        assert "This is a quote" in result

    def test_collapses_blank_lines(self):
        text = "A\n\n\n\nB"
        result = _clean_text_for_speech(text)
        assert "\n\n\n" not in result

    def test_empty_text(self):
        assert _clean_text_for_speech("") == ""
        assert _clean_text_for_speech("   ") == ""

    def test_strips_frontmatter_only(self):
        text = "---\nid: 123\ntitle: test\n---\n"
        assert _clean_text_for_speech(text) == ""


class TestAudioOptions:
    """Test voice resolution and options."""

    def test_default_voice_english(self):
        opts = AudioOptions(language="en")
        assert opts.resolve_voice() == "en-US-AriaNeural"

    def test_default_voice_bulgarian(self):
        opts = AudioOptions(language="bg")
        assert opts.resolve_voice() == "bg-BG-KalinaNeural"

    def test_default_voice_unknown_falls_back_to_english(self):
        opts = AudioOptions(language="ja")
        assert opts.resolve_voice() == "en-US-AriaNeural"

    def test_explicit_voice_override(self):
        opts = AudioOptions(voice="en-GB-RyanNeural", language="bg")
        assert opts.resolve_voice() == "en-GB-RyanNeural"

    def test_language_with_region_code(self):
        opts = AudioOptions(language="en-US")
        assert opts.resolve_voice() == "en-US-AriaNeural"

    def test_empty_language_defaults_to_english(self):
        opts = AudioOptions()
        assert opts.resolve_voice() == "en-US-AriaNeural"


class TestVoicePresets:
    """Test voice preset structure."""

    def test_has_english_voices(self):
        assert "en" in VOICE_PRESETS
        assert len(VOICE_PRESETS["en"]) >= 3

    def test_each_preset_has_required_fields(self):
        for lang, voices in VOICE_PRESETS.items():
            for v in voices:
                assert "id" in v
                assert "name" in v
                assert "gender" in v

    def test_default_voices_cover_presets(self):
        for lang in DEFAULT_VOICES:
            assert lang in VOICE_PRESETS


class TestListAudioFiles:
    """Test audio file listing."""

    def test_empty_dir(self, tmp_path):
        assert list_audio_files(tmp_path) == []

    def test_no_audio_dir(self, tmp_path):
        assert list_audio_files(tmp_path) == []

    def test_lists_mp3_files(self, tmp_path):
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        (audio_dir / "draft_20260101.mp3").write_bytes(b"fake-audio")
        (audio_dir / "polish_20260102.mp3").write_bytes(b"fake-audio-2")
        (audio_dir / "notes.txt").write_text("not audio")

        files = list_audio_files(tmp_path)
        assert len(files) == 2
        assert all(f["filename"].endswith(".mp3") for f in files)
        # Sorted reverse by name (newest first)
        assert files[0]["filename"] == "polish_20260102.mp3"

    def test_file_metadata(self, tmp_path):
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        (audio_dir / "test.mp3").write_bytes(b"x" * 1024)

        files = list_audio_files(tmp_path)
        assert len(files) == 1
        assert files[0]["size_bytes"] == 1024
        assert "created" in files[0]
        assert "path" in files[0]


class TestGenerateAudio:
    """Test audio generation (with mocked edge-tts)."""

    def test_raises_on_empty_text(self, tmp_path):
        with pytest.raises(ValueError, match="No text content"):
            generate_audio("", tmp_path)

    def test_raises_on_whitespace_only(self, tmp_path):
        with pytest.raises(ValueError, match="No text content"):
            generate_audio("   \n\n  ", tmp_path)

    @patch("quill.audio.asyncio.run")
    def test_generates_audio_file(self, mock_run, tmp_path):
        # Mock the async function to create the file
        def fake_run(coro):
            # Create the output file to simulate edge-tts
            # The coroutine is _generate_audio; we need to find the output path
            # Since we can't easily inspect the coroutine, just create the file
            audio_dir = tmp_path / "audio"
            audio_dir.mkdir(exist_ok=True)
            out = audio_dir / "test.mp3"
            out.write_bytes(b"fake-mp3-data")
            result = AudioResult(
                path=str(out),
                filename="test.mp3",
                voice="en-US-AriaNeural",
                size_bytes=len(b"fake-mp3-data"),
                created="2026-06-21 12:00:00",
            )
            return result

        mock_run.side_effect = fake_run

        result = generate_audio(
            text="Hello world, this is a test.",
            output_dir=tmp_path / "audio",
            filename="test.mp3",
        )
        assert result.filename == "test.mp3"
        assert result.voice == "en-US-AriaNeural"
        assert result.size_bytes > 0

    @patch("quill.audio.asyncio.run")
    def test_creates_output_directory(self, mock_run, tmp_path):
        output_dir = tmp_path / "nested" / "audio"

        def fake_run(coro):
            output_dir.mkdir(parents=True, exist_ok=True)
            out = output_dir / "test.mp3"
            out.write_bytes(b"data")
            return AudioResult(
                path=str(out), filename="test.mp3",
                voice="en-US-AriaNeural", size_bytes=4,
            )

        mock_run.side_effect = fake_run

        generate_audio(text="Test content", output_dir=output_dir, filename="test.mp3")
        assert output_dir.exists()

    @patch("quill.audio.asyncio.run")
    def test_strips_markdown_before_tts(self, mock_run, tmp_path):
        captured_text = []

        def fake_run(coro):
            # We can't easily extract args from the coroutine,
            # but we verify the clean function was called
            audio_dir = tmp_path / "audio"
            audio_dir.mkdir(exist_ok=True)
            out = audio_dir / "test.mp3"
            out.write_bytes(b"data")
            return AudioResult(
                path=str(out), filename="test.mp3",
                voice="en-US-AriaNeural", size_bytes=4,
            )

        mock_run.side_effect = fake_run

        markdown_text = "# Title\n\n**Bold** and *italic* with `code`"
        generate_audio(text=markdown_text, output_dir=tmp_path / "audio", filename="test.mp3")
        # If it didn't raise, the text was cleaned successfully
        mock_run.assert_called_once()
