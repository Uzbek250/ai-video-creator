"""
video_editor.py
----------------
Assembles the per-scene images + per-scene audio narration into a
single final .mp4, with:
  - each image shown for exactly as long as its narration audio lasts
  - a subtle Ken Burns (slow pan/zoom) effect on every image, so static
    images don't feel dead on screen
  - optional open captions burned into the video
  - a combined audio track (all scene narrations concatenated)

Output is 1080x1920 (9:16, Shorts) by default, or 1920x1080 (16:9).
"""

from __future__ import annotations

import logging
import os

from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    concatenate_audioclips,
    concatenate_videoclips,
)

logger = logging.getLogger(__name__)


class VideoAssemblyError(Exception):
    """Raised when the final video cannot be assembled."""


RATIO_DIMENSIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


def _ken_burns_clip(image_path: str, duration: float, size: tuple[int, int]) -> ImageClip:
    """
    Apply a slow zoom-in effect to a static image over `duration` seconds.
    A slight zoom (1.0 -> 1.08) reads as gentle motion without looking
    like a mistake or distracting from the narration.
    """
    clip = ImageClip(image_path).with_duration(duration)
    clip = clip.resized(size)

    zoom_start, zoom_end = 1.0, 1.08

    def _resize_over_time(t: float) -> float:
        progress = t / duration if duration > 0 else 0
        return zoom_start + (zoom_end - zoom_start) * progress

    clip = clip.resized(_resize_over_time)
    clip = clip.with_position(("center", "center"))
    return clip


def _caption_clip(text: str, duration: float, video_size: tuple[int, int]) -> TextClip | None:
    """
    Build a simple bottom-third open caption. Returns None (and logs a
    warning) if ImageMagick — which TextClip depends on — isn't
    available in this environment, so caption failure never blocks the
    rest of the render.
    """
    width, _ = video_size
    try:
        txt_clip = TextClip(
            text=text,
            font_size=int(width * 0.06),
            color="white",
            stroke_color="black",
            stroke_width=2,
            method="caption",
            size=(int(width * 0.9), None),
            text_align="center",
        )
        txt_clip = txt_clip.with_duration(duration)
        txt_clip = txt_clip.with_position(("center", "bottom"))
        return txt_clip
    except Exception as e:
        logger.warning("Caption rendering unavailable, skipping captions: %s", e)
        return None


def assemble_video(
    image_paths: list[str],
    audio_paths: list[str],
    narration_texts: list[str],
    output_path: str,
    ratio: str = "9:16",
    add_captions: bool = True,
    fps: int = 30,
) -> str:
    """
    Combine per-scene images and audio into a single final video file.

    image_paths, audio_paths, and narration_texts must all be the same
    length and in matching scene order.
    """
    if not (len(image_paths) == len(audio_paths) == len(narration_texts)):
        raise VideoAssemblyError(
            "image_paths, audio_paths, and narration_texts must have equal length "
            f"(got {len(image_paths)}, {len(audio_paths)}, {len(narration_texts)})"
        )
    if not image_paths:
        raise VideoAssemblyError("No scenes to assemble.")

    size = RATIO_DIMENSIONS.get(ratio, RATIO_DIMENSIONS["9:16"])

    scene_clips = []
    audio_clips = []

    try:
        for img_path, audio_path, text in zip(image_paths, audio_paths, narration_texts):
            audio_clip = AudioFileClip(audio_path)
            duration = audio_clip.duration
            audio_clips.append(audio_clip)

            visual = _ken_burns_clip(img_path, duration, size)

            layers = [visual]
            if add_captions:
                caption = _caption_clip(text, duration, size)
                if caption is not None:
                    layers.append(caption)

            scene = CompositeVideoClip(layers, size=size).with_duration(duration)
            scene_clips.append(scene)

        final_video = concatenate_videoclips(scene_clips, method="compose")
        final_audio = concatenate_audioclips(audio_clips)
        final_video = final_video.with_audio(final_audio)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        final_video.write_videofile(
            output_path,
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4,
            logger=None,  # silence moviepy's own progress bar; Streamlit shows ours
        )

        return output_path

    except Exception as e:
        raise VideoAssemblyError(f"Video assembly failed: {e}") from e

    finally:
        # Always release file handles, even on failure, so temp files
        # can be cleaned up afterward without "file in use" errors.
        for clip in scene_clips:
            try:
                clip.close()
            except Exception:
                pass
        for clip in audio_clips:
            try:
                clip.close()
            except Exception:
                pass
