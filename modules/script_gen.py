"""
script_gen.py
-------------
Handles all communication with the Google Gemini API to produce:
  - trending topic suggestions (when the user wants inspiration), and
  - a full video script broken into narratable "scenes", each scene
    carrying both the voiceover text and an image-generation prompt.

The Gemini response is requested as strict JSON so downstream modules
(audio_gen, media_gen, video_editor) can consume it without any
fragile text-parsing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class ScriptGenerationError(Exception):
    """Raised when Gemini fails to return a usable script."""


@dataclass
class Scene:
    narration_chunk: str
    visual_prompt: str


@dataclass
class VideoScript:
    title: str
    script_text: str
    scenes: list[Scene] = field(default_factory=list)


# JSON schema Gemini must follow. Using an explicit schema (rather than
# hoping the model behaves) is what makes the "structured output" reliable.
_SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "script_text": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "narration_chunk": {"type": "string"},
                    "visual_prompt": {"type": "string"},
                },
                "required": ["narration_chunk", "visual_prompt"],
            },
        },
    },
    "required": ["title", "script_text", "scenes"],
}

_TREND_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["topics"],
}


def _get_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def fetch_trending_topics(
    api_key: str,
    model: str = "gemini-2.5-flash",
    niche: Optional[str] = None,
    count: int = 2,
) -> list[str]:
    """
    Ask Gemini to propose `count` trending short-video topic ideas.
    Since Gemini has no live internet trend feed, this is framed as an
    informed suggestion task, optionally scoped to a niche.
    """
    client = _get_client(api_key)

    niche_clause = f" within the '{niche}' niche" if niche else ""
    prompt = (
        f"Suggest {count} highly engaging, currently popular short-form "
        f"video topic ideas{niche_clause}, suitable for a 30-45 second "
        f"YouTube Shorts video. Each topic should be a single concise "
        f"sentence describing the concept/hook, not a full script."
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_TREND_SCHEMA,
            ),
        )
        data = json.loads(response.text)
        topics = data.get("topics", [])
        if not topics:
            raise ScriptGenerationError("Gemini returned no topics.")
        return topics
    except (json.JSONDecodeError, KeyError) as e:
        raise ScriptGenerationError(f"Could not parse trending topics: {e}") from e
    except Exception as e:  # network / API errors from the SDK
        raise ScriptGenerationError(f"Gemini request failed: {e}") from e


def generate_script(
    api_key: str,
    topic: str,
    model: str = "gemini-2.5-flash",
    language: str = "English",
    duration_seconds: int = 40,
    scene_count: int = 6,
    art_style: str = "3D animated cartoon movie style, vibrant colors, Pixar-like rendering",
) -> VideoScript:
    """
    Generate a complete video script + per-scene visual prompts for `topic`.

    The visual_prompt for each scene is explicitly requested in English
    and phrased for the Pollinations.AI FLUX model, regardless of the
    narration language, since FLUX responds far more reliably to
    English, art-directed prompts.

    `art_style` is appended to every single scene's visual_prompt so all
    scenes share one consistent look (same rendering style, same overall
    "world") even though each scene is generated as a separate image —
    this matters a lot for cartoon/comic content, where a style change
    between scenes reads as an obvious visual glitch to viewers.
    """
    client = _get_client(api_key)

    prompt = f"""
You are a professional short-form video scriptwriter and art director.

Write a {duration_seconds}-second voiceover script in {language} for a
YouTube Shorts video about: "{topic}"

Requirements:
- Break the narration into exactly {scene_count} scenes.
- Each scene's "narration_chunk" is the exact voiceover text for that
  scene, in {language}, natural and easy to read aloud.
- Each scene's "visual_prompt" must be written in English, describing a
  vivid visual for that moment, suitable for an AI image model (FLUX).
  Every visual_prompt MUST be in this consistent art style:
  "{art_style}". Describe character appearance consistently across
  scenes (same character design, same color palette) since each image
  is generated independently — repeat key character/setting details in
  every single scene's prompt rather than assuming continuity.
- The full "script_text" field should be the complete narration
  (all scenes concatenated) in {language}.
- Give the video a short, catchy "title".
- Keep pacing tight — every scene should earn its place.
""".strip()

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_SCRIPT_SCHEMA,
            ),
        )
        data = json.loads(response.text)
    except (json.JSONDecodeError, KeyError) as e:
        raise ScriptGenerationError(f"Could not parse Gemini script response: {e}") from e
    except Exception as e:
        raise ScriptGenerationError(f"Gemini request failed: {e}") from e

    scenes_raw = data.get("scenes", [])
    if not scenes_raw:
        raise ScriptGenerationError("Gemini returned a script with no scenes.")

    scenes = [
        Scene(
            narration_chunk=s.get("narration_chunk", "").strip(),
            visual_prompt=s.get("visual_prompt", "").strip(),
        )
        for s in scenes_raw
        if s.get("narration_chunk") and s.get("visual_prompt")
    ]

    if not scenes:
        raise ScriptGenerationError("All returned scenes were missing required fields.")

    return VideoScript(
        title=data.get("title", topic).strip(),
        script_text=data.get("script_text", "").strip(),
        scenes=scenes,
    )
