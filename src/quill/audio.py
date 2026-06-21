"""Audio version generator — text-to-speech for Quill pieces.

Uses edge-tts (Microsoft Edge TTS) to generate high-quality speech
from piece content. Audio files are stored in the piece's directory
under audio/.

Requires: edge-tts (pip install edge-tts)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voice presets — popular voices grouped by language
# ---------------------------------------------------------------------------

VOICE_PRESETS: dict[str, list[dict[str, str]]] = {
    "en": [
        {"id": "en-US-AriaNeural", "name": "Aria (US, Female)", "gender": "Female"},
        {"id": "en-US-GuyNeural", "name": "Guy (US, Male)", "gender": "Male"},
        {"id": "en-US-JennyNeural", "name": "Jenny (US, Female)", "gender": "Female"},
        {"id": "en-GB-SoniaNeural", "name": "Sonia (UK, Female)", "gender": "Female"},
        {"id": "en-GB-RyanNeural", "name": "Ryan (UK, Male)", "gender": "Male"},
        {"id": "en-AU-NatashaNeural", "name": "Natasha (AU, Female)", "gender": "Female"},
    ],
    "bg": [
        {"id": "bg-BG-KalinaNeural", "name": "Kalina (BG, Female)", "gender": "Female"},
        {"id": "bg-BG-BorislavNeural", "name": "Borislav (BG, Male)", "gender": "Male"},
    ],
    "de": [
        {"id": "de-DE-KatjaNeural", "name": "Katja (DE, Female)", "gender": "Female"},
        {"id": "de-DE-ConradNeural", "name": "Conrad (DE, Male)", "gender": "Male"},
    ],
    "fr": [
        {"id": "fr-FR-DeniseNeural", "name": "Denise (FR, Female)", "gender": "Female"},
        {"id": "fr-FR-HenriNeural", "name": "Henri (FR, Male)", "gender": "Male"},
    ],
    "es": [
        {"id": "es-ES-ElviraNeural", "name": "Elvira (ES, Female)", "gender": "Female"},
        {"id": "es-ES-AlvaroNeural", "name": "Alvaro (ES, Male)", "gender": "Male"},
    ],
}

# Default voice per language
DEFAULT_VOICES = {
    "en": "en-US-AriaNeural",
    "bg": "bg-BG-KalinaNeural",
    "de": "de-DE-KatjaNeural",
    "fr": "fr-FR-DeniseNeural",
    "es": "es-ES-ElviraNeural",
}


@dataclass
class AudioOptions:
    """Configuration for audio generation."""

    voice: str = ""  # edge-tts voice ID (empty = auto-detect from piece language)
    rate: str = "+0%"  # Speech rate: -50% to +100%
    pitch: str = "+0Hz"  # Pitch adjustment: -50Hz to +50Hz
    volume: str = "+0%"  # Volume: -50% to +100%
    language: str = ""  # Language hint (en, bg, de, etc.)

    def resolve_voice(self) -> str:
        """Pick a voice ID, auto-detecting from language if needed."""
        if self.voice:
            return self.voice
        lang = (self.language or "en").split("-")[0].split("_")[0].lower()
        return DEFAULT_VOICES.get(lang, DEFAULT_VOICES["en"])


@dataclass
class AudioResult:
    """Result of an audio generation run."""

    path: str  # Absolute path to the generated MP3
    filename: str
    voice: str
    duration_ms: int = 0
    size_bytes: int = 0
    created: str = ""


def _clean_text_for_speech(text: str) -> str:
    """Strip markdown formatting for cleaner TTS output.

    Removes: frontmatter, headers markup, bold/italic markers,
    code blocks, links (keeps link text), images, HTML tags.
    """
    # Remove YAML frontmatter
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    # Remove code blocks
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # Remove inline code
    text = re.sub(r"`([^`]*)`", r"\1", text)
    # Remove images ![alt](url)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Remove links but keep text [text](url)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Remove heading markers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    # Remove strikethrough
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    # Remove blockquote markers
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    # Remove horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _generate_audio(
    text: str, output_path: Path, options: AudioOptions
) -> AudioResult:
    """Generate audio from text using edge-tts."""
    import edge_tts

    voice = options.resolve_voice()
    logger.info("Generating audio with voice=%s, rate=%s", voice, options.rate)

    communicate = edge_tts.Communicate(
        text,
        voice=voice,
        rate=options.rate,
        pitch=options.pitch,
        volume=options.volume,
    )

    await communicate.save(str(output_path))

    stat = output_path.stat()
    return AudioResult(
        path=str(output_path),
        filename=output_path.name,
        voice=voice,
        size_bytes=stat.st_size,
        created=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )


def generate_audio(
    text: str,
    output_dir: Path,
    filename: str = "audio.mp3",
    options: AudioOptions | None = None,
) -> AudioResult:
    """Generate an MP3 audio file from text content.

    Args:
        text: The text to synthesize (markdown is auto-cleaned).
        output_dir: Directory to write the MP3 file.
        filename: Output filename (default: audio.mp3).
        options: TTS configuration (voice, rate, pitch, volume).

    Returns:
        AudioResult with path and metadata.

    Raises:
        RuntimeError: If TTS generation fails.
    """
    if options is None:
        options = AudioOptions()

    cleaned = _clean_text_for_speech(text)
    if not cleaned:
        raise ValueError("No text content to generate audio from")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    try:
        result = asyncio.run(_generate_audio(cleaned, output_path, options))
        logger.info(
            "Audio generated: %s (%d bytes, voice=%s)",
            result.path,
            result.size_bytes,
            result.voice,
        )
        return result
    except Exception as e:
        logger.exception("Audio generation failed")
        raise RuntimeError(f"Audio generation failed: {e}") from e


def list_audio_files(piece_dir: Path) -> list[dict]:
    """List all audio files for a piece.

    Args:
        piece_dir: The piece's directory (output/<piece-id>/).

    Returns:
        List of dicts with filename, path, size, created.
    """
    audio_dir = piece_dir / "audio"
    if not audio_dir.exists():
        return []

    files = []
    for f in sorted(audio_dir.glob("*.mp3"), reverse=True):
        stat = f.stat()
        files.append({
            "filename": f.name,
            "path": str(f),
            "size_bytes": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        })
    return files


async def list_voices(language: str = "") -> list[dict]:
    """List available edge-tts voices, optionally filtered by language.

    Args:
        language: Language code to filter (e.g., 'en', 'bg', 'de').

    Returns:
        List of voice dicts with id, name, gender, language.
    """
    import edge_tts

    voices = await edge_tts.list_voices()
    if language:
        lang = language.lower()
        voices = [v for v in voices if v["Locale"].lower().startswith(lang)]

    return [
        {
            "id": v["ShortName"],
            "name": v["FriendlyName"],
            "gender": v["Gender"],
            "language": v["Locale"],
        }
        for v in voices
    ]
