"""
media_gen.py
------------
Downloads one image per scene from Pollinations.AI's free, prompt-based
image API (FLUX model). No API key required.

Note on reliability: Pollinations is a free shared service, so it can
be slow or occasionally time out under load. Every request is retried
a few times with backoff before giving up on that scene.
"""

from __future__ import annotations

import logging
import os
import random
import time
import urllib.parse

import requests

logger = logging.getLogger(__name__)

POLLINATIONS_BASE_URL = "https://image.pollinations.ai/prompt"

_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2
_REQUEST_TIMEOUT_SECONDS = 60


class MediaGenerationError(Exception):
    """Raised when an image cannot be generated/downloaded after retries."""


def _build_url(prompt: str, width: int, height: int, seed: int) -> str:
    encoded_prompt = urllib.parse.quote(prompt)
    params = f"?width={width}&height={height}&model=flux&seed={seed}&nologo=true"
    return f"{POLLINATIONS_BASE_URL}/{encoded_prompt}{params}"


def generate_scene_image(
    prompt: str,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
    seed: int | None = None,
) -> str:
    """
    Download a single AI-generated image for `prompt` and save it to
    `output_path`. Returns output_path on success.
    """
    if seed is None:
        seed = random.randint(0, 2_147_483_647)

    url = _build_url(prompt, width, height, seed)
    last_error: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "image" not in content_type or len(response.content) < 1024:
                raise MediaGenerationError(
                    f"Unexpected response for image prompt (content-type={content_type!r}, "
                    f"size={len(response.content)}B)"
                )

            with open(output_path, "wb") as f:
                f.write(response.content)
            return output_path

        except (requests.RequestException, MediaGenerationError) as e:
            last_error = e
            logger.warning(
                "Image generation attempt %d/%d failed for prompt %r: %s",
                attempt, _MAX_RETRIES, prompt[:60], e,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    raise MediaGenerationError(
        f"Failed to generate image after {_MAX_RETRIES} attempts: {last_error}"
    )


def generate_scene_images(
    visual_prompts: list[str],
    temp_dir: str,
    width: int = 1080,
    height: int = 1920,
    style_suffix: str = "",
) -> list[str]:
    """
    Generate one image per prompt, sequentially (Pollinations' free tier
    handles sequential load more reliably than a burst of concurrent
    requests). Returns file paths in the same order as visual_prompts.

    `style_suffix`, if given, is appended to every prompt (e.g.
    ", 3D animated cartoon style, vibrant colors"). This is a second
    safety net for visual consistency on top of the style already baked
    into each prompt by script_gen — cheap insurance since each image is
    generated independently and Pollinations has no memory between calls.
    """
    os.makedirs(temp_dir, exist_ok=True)
    paths = []

    for i, prompt in enumerate(visual_prompts):
        full_prompt = f"{prompt}, {style_suffix}" if style_suffix else prompt
        output_path = os.path.join(temp_dir, f"scene_{i:02d}.jpg")
        try:
            generate_scene_image(full_prompt, output_path, width=width, height=height)
            paths.append(output_path)
        except MediaGenerationError as e:
            raise MediaGenerationError(f"Scene {i} image failed: {e}") from e

    return paths
