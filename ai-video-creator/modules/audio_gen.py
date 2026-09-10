"""
audio_gen.py
------------
Turns narration text into natural-sounding speech using edge-tts
(Microsoft's free, no-API-key text-to-speech engine).

Provides both a "whole script" narration function and a per-scene
narration function — the per-scene version is what video_editor.py
actually uses, since each scene's clip duration needs to be synced to
its own audio chunk.
"""

from __future__ import annotations

import asyncio
import logging
import os

import edge_tts

logger = logging.getLogger(__name__)


class AudioGenerationError(Exception):
    """Raised when TTS synthesis fails for a piece of text."""


# A handful of good-quality voices worth exposing in the UI.
# Full list: `edge-tts --list-voices`
AVAILABLE_VOICES = {
    "Uzbek (Madina, Female)": "uz-UZ-MadinaNeural",
    "Uzbek (Sardor, Male)": "uz-UZ-SardorNeural",
    "English US (Christopher, Male)": "en-US-ChristopherNeural",
    "English US (Jenny, Female)": "en-US-JennyNeural",
    "Russian (Dmitry, Male)": "ru-RU-DmitryNeural",
    "Russian (Svetlana, Female)": "ru-RU-SvetlanaNeural",
}


async def _synthesize(text: str, voice: str, output_path: str) -> None:
    if not text.strip():
        raise AudioGenerationError("Cannot synthesize empty text.")
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
    except Exception as e:
        raise AudioGenerationError(f"edge-tts failed for voice '{voice}': {e}") from e

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise AudioGenerationError(
            f"edge-tts produced an empty file for text: {text[:60]!r}"
        )


def synthesize_speech(text: str, voice: str, output_path: str) -> str:
    """
    Synchronous wrapper around edge-tts for a single block of text.
    Returns the output_path on success.
    """
    asyncio.run(_synthesize(text, voice, output_path))
    return output_path


async def synthesize_scenes_async(
    narration_chunks: list[str],
    voice: str,
    temp_dir: str,
) -> list[str]:
    """
    Synthesize one MP3 per scene, concurrently, into temp_dir.
    Returns the list of file paths in the same order as narration_chunks.
    """
    os.makedirs(temp_dir, exist_ok=True)
    paths = [os.path.join(temp_dir, f"scene_{i:02d}.mp3") for i in range(len(narration_chunks))]

    tasks = [
        _synthesize(text, voice, path)
        for text, path in zip(narration_chunks, paths)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            raise AudioGenerationError(
                f"Scene {i} audio synthesis failed: {result}"
            ) from result

    return paths


def synthesize_scenes(
    narration_chunks: list[str],
    voice: str,
    temp_dir: str,
) -> list[str]:
    """Synchronous wrapper — used from Streamlit's non-async context."""
    return asyncio.run(synthesize_scenes_async(narration_chunks, voice, temp_dir))
