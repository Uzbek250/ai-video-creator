"""
app.py
------
Streamlit front-end tying together script_gen -> audio_gen -> media_gen
-> video_editor into one interactive, end-to-end AI video creation flow.
"""

from __future__ import annotations

import os
import shutil
import time

import streamlit as st
from dotenv import load_dotenv

from modules.audio_gen import AVAILABLE_VOICES, AudioGenerationError, synthesize_scenes
from modules.media_gen import MediaGenerationError, generate_scene_images
from modules.script_gen import ScriptGenerationError, VideoScript, fetch_trending_topics, generate_script
from modules.video_editor import RATIO_DIMENSIONS, VideoAssemblyError, assemble_video

load_dotenv()

TEMP_DIR = "temp"
OUTPUT_DIR = "output"

st.set_page_config(page_title="AI Video Creator", page_icon="🎬", layout="wide")


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _init_state() -> None:
    defaults = {
        "script": None,          # VideoScript
        "trending_topics": [],
        "image_paths": [],
        "audio_paths": [],
        "final_video_path": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset_pipeline_outputs() -> None:
    """Clear everything downstream of the script when a new script is made."""
    st.session_state.image_paths = []
    st.session_state.audio_paths = []
    st.session_state.final_video_path = None


def _clean_temp_dir() -> None:
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR, exist_ok=True)


_init_state()
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Sidebar — configuration
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Configuration")

    api_key = st.text_input(
        "Gemini API Key",
        value=os.getenv("GEMINI_API_KEY", ""),
        type="password",
        help="Get a free key at https://aistudio.google.com/apikey",
    )
    gemini_model = st.selectbox(
        "Gemini model",
        options=["gemini-2.5-flash", "gemini-2.5-pro"],
        index=0,
    )

    st.divider()

    ratio = st.radio("Video ratio", options=list(RATIO_DIMENSIONS.keys()), index=0)
    voice_label = st.selectbox("Voice", options=list(AVAILABLE_VOICES.keys()), index=0)
    voice_code = AVAILABLE_VOICES[voice_label]
    add_captions = st.checkbox("Burn in captions", value=True)

    st.divider()
    scene_count = st.slider("Number of scenes", min_value=3, max_value=10, value=6)
    duration_seconds = st.slider("Target duration (seconds)", min_value=15, max_value=60, value=40)

    st.divider()
    ART_STYLES = {
        "3D Cartoon (Pixar-like)": "3D animated cartoon movie style, vibrant colors, Pixar-like rendering, soft lighting",
        "2D Flat Comic": "flat 2D comic book illustration style, bold outlines, bright flat colors, clean vector art",
        "Anime": "Japanese anime style, cel-shaded, expressive characters, dynamic lighting",
        "Storybook Watercolor": "children's storybook watercolor illustration, soft pastel colors, hand-painted texture",
        "Photorealistic": "photorealistic, cinematic lighting, high detail, realistic photography",
        "Custom": None,
    }
    style_label = st.selectbox("Art style", options=list(ART_STYLES.keys()), index=0)
    if style_label == "Custom":
        art_style = st.text_input("Describe your custom style", value="")
    else:
        art_style = ART_STYLES[style_label]


st.title("🎬 AI Video Creator")
st.caption("Topic → Script → Voice → Visuals → Final Shorts video, end to end.")

if not api_key:
    st.warning("Enter your Gemini API key in the sidebar to get started.")
    st.stop()


# ---------------------------------------------------------------------------
# Step 1 — Topic input (trending or custom)
# ---------------------------------------------------------------------------

st.subheader("1. Choose a topic")

col_a, col_b = st.columns([1, 2])

with col_a:
    niche = st.text_input("Niche (optional)", placeholder="e.g. cooking, tech facts, history")
    if st.button("🔥 Suggest trending topics"):
        with st.spinner("Asking Gemini for topic ideas..."):
            try:
                st.session_state.trending_topics = fetch_trending_topics(
                    api_key=api_key, model=gemini_model, niche=niche or None
                )
            except ScriptGenerationError as e:
                st.error(f"Could not fetch topics: {e}")

with col_b:
    custom_topic = st.text_input("Or type your own topic", placeholder="e.g. 5 surprising facts about octopuses")

if st.session_state.trending_topics:
    st.write("Suggested topics:")
    for i, topic in enumerate(st.session_state.trending_topics):
        if st.button(f"Use: {topic}", key=f"topic_{i}"):
            custom_topic = topic

chosen_topic = custom_topic

if st.button("📝 Generate script", type="primary", disabled=not chosen_topic):
    with st.spinner("Writing script with Gemini..."):
        try:
            script = generate_script(
                api_key=api_key,
                topic=chosen_topic,
                model=gemini_model,
                duration_seconds=duration_seconds,
                scene_count=scene_count,
                art_style=art_style or "3D animated cartoon movie style, vibrant colors",
            )
            st.session_state.script = script
            _reset_pipeline_outputs()
        except ScriptGenerationError as e:
            st.error(f"Script generation failed: {e}")


# ---------------------------------------------------------------------------
# Step 2 — Review / edit script
# ---------------------------------------------------------------------------

script: VideoScript | None = st.session_state.script

if script:
    st.subheader("2. Review & edit script")

    new_title = st.text_input("Title", value=script.title)
    script.title = new_title

    with st.expander(f"Scenes ({len(script.scenes)})", expanded=True):
        for i, scene in enumerate(script.scenes):
            st.markdown(f"**Scene {i + 1}**")
            c1, c2 = st.columns(2)
            with c1:
                scene.narration_chunk = st.text_area(
                    "Narration", value=scene.narration_chunk, key=f"narr_{i}", height=90
                )
            with c2:
                scene.visual_prompt = st.text_area(
                    "Visual prompt (English)", value=scene.visual_prompt, key=f"visual_{i}", height=90
                )

    # -----------------------------------------------------------------
    # Step 3 — Build
    # -----------------------------------------------------------------

    st.subheader("3. Build the video")

    if st.button("🚀 Build final video", type="primary"):
        _clean_temp_dir()
        progress = st.progress(0, text="Starting...")

        narration_chunks = [s.narration_chunk for s in script.scenes]
        visual_prompts = [s.visual_prompt for s in script.scenes]

        try:
            progress.progress(10, text="Generating narration audio...")
            audio_paths = synthesize_scenes(narration_chunks, voice_code, TEMP_DIR)
            st.session_state.audio_paths = audio_paths

            progress.progress(40, text="Generating scene visuals (this can take a minute)...")
            width, height = RATIO_DIMENSIONS[ratio]
            image_paths = generate_scene_images(
                visual_prompts, TEMP_DIR, width=width, height=height,
                style_suffix=art_style or "",
            )
            st.session_state.image_paths = image_paths

            progress.progress(75, text="Assembling final video...")
            output_path = os.path.join(OUTPUT_DIR, f"output_video_{int(time.time())}.mp4")
            assemble_video(
                image_paths=image_paths,
                audio_paths=audio_paths,
                narration_texts=narration_chunks,
                output_path=output_path,
                ratio=ratio,
                add_captions=add_captions,
            )
            st.session_state.final_video_path = output_path

            progress.progress(100, text="Done!")
            st.success("Video created successfully!")

        except AudioGenerationError as e:
            st.error(f"Audio generation failed: {e}")
        except MediaGenerationError as e:
            st.error(f"Image generation failed: {e}")
        except VideoAssemblyError as e:
            st.error(f"Video assembly failed: {e}")

    # Preview generated assets as they exist, even before final assembly
    if st.session_state.image_paths:
        with st.expander("Preview generated scene images"):
            cols = st.columns(3)
            for i, path in enumerate(st.session_state.image_paths):
                with cols[i % 3]:
                    st.image(path, caption=f"Scene {i + 1}", use_column_width=True)

    if st.session_state.final_video_path and os.path.exists(st.session_state.final_video_path):
        st.subheader("4. Final video")
        st.video(st.session_state.final_video_path)
        with open(st.session_state.final_video_path, "rb") as f:
            st.download_button(
                "⬇️ Download video",
                data=f,
                file_name=os.path.basename(st.session_state.final_video_path),
                mime="video/mp4",
            )
