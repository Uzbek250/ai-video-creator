# AI Video Creator

End-to-end tool that turns a topic into a finished YouTube Shorts video:
**Topic → Script (Gemini) → Voiceover (edge-tts) → Visuals (Pollinations.AI) → Final .mp4 (MoviePy)**

## Local setup

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # then paste your Gemini key into .env
```

You also need **ffmpeg** and **imagemagick** installed on your machine
(MoviePy needs ffmpeg for encoding; captions need imagemagick for text
rendering):

```bash
# Debian/Ubuntu
sudo apt-get install ffmpeg imagemagick

# macOS
brew install ffmpeg imagemagick
```

Run it:

```bash
streamlit run app.py
```

Get a free Gemini API key at https://aistudio.google.com/apikey

## Deploying to Render (free tier)

1. Push this repo to GitHub.
2. On [Render](https://render.com), click **New +** → **Blueprint**, and point it at this repo (`render.yaml` is already set up).
3. When prompted, set the `GEMINI_API_KEY` environment variable.
4. Deploy.

**Free-tier caveats to know before you rely on this:**
- The free instance spins down after 15 minutes of inactivity, so the
  first request after idle time will be slow (cold start).
- Free tier has limited RAM/CPU. MoviePy rendering is CPU-heavy —
  longer videos (more scenes, higher resolution) may time out or run
  out of memory. Start with fewer scenes (4-6) and 9:16 @ 1080x1920
  before pushing further.
- The filesystem is **ephemeral** — anything written to `temp/` or
  `output/` is lost on restart/redeploy. This is fine for a
  generate-then-download flow, but don't rely on Render to store your
  videos long-term.
- Pollinations.AI is a free shared image service — expect occasional
  slowness or failures under load; `media_gen.py` retries automatically
  but can still fail on a bad run.

## Project structure

```
app.py                 # Streamlit UI — orchestrates the full pipeline
modules/
  script_gen.py         # Gemini: topic ideas + structured script + visual prompts
  audio_gen.py           # edge-tts: per-scene narration audio
  media_gen.py            # Pollinations.AI: per-scene images
  video_editor.py           # MoviePy: Ken Burns effect, captions, final render
```
