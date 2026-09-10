# Docker deployment: Render's native Python environment doesn't allow
# apt-get (read-only filesystem, no root), but this app needs ffmpeg
# (MoviePy encoding) and imagemagick (caption text rendering) at the
# system level, not just Python packages. Docker is the only Render
# deploy path that allows installing OS packages.

FROM python:3.11-slim

# Install system dependencies: ffmpeg for video/audio encoding,
# imagemagick for MoviePy's TextClip (captions).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    imagemagick \
    && rm -rf /var/lib/apt/lists/*

# ImageMagick's default policy blocks "text" and other operations
# MoviePy needs (a common source of silent caption failures). Relax
# the policy so TextClip can actually render.
RUN sed -i 's/rights="none" pattern="@\*"/rights="read|write" pattern="@*"/' \
    /etc/ImageMagick-6/policy.xml || true
RUN sed -i 's/<policy domain="path" rights="none" pattern="@\*"\/>//' \
    /etc/ImageMagick-6/policy.xml || true

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render provides $PORT at runtime; Streamlit must bind to it and to
# 0.0.0.0 (not localhost) to be reachable from outside the container.
EXPOSE 8501

CMD streamlit run app.py --server.port $PORT --server.address 0.0.0.0
