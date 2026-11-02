# Hugging Face Space for Sketchbridge.
# Copy this file and README.md (from this folder) into a new Docker Space.
# At build time it downloads the app from GitHub, so the Space needs only these two files.
# To pick up new commits on GitHub: Space Settings -> "Factory rebuild".

FROM python:3.11-slim

# Hugging Face runs the app as user 1000; give it a home and a writable app folder.
RUN useradd -m -u 1000 user
WORKDIR /app

# Download the latest code from GitHub's main branch (no git needed).
ADD https://github.com/Rasika-Deodhar/sketchbridge/archive/refs/heads/main.tar.gz /tmp/src.tar.gz
RUN tar -xzf /tmp/src.tar.gz --strip-components=1 -C /app && rm /tmp/src.tar.gz \
    && pip install --no-cache-dir -r requirements.txt \
    && chown -R user:user /app

USER user
ENV PYTHONUNBUFFERED=1
EXPOSE 7860

# One worker: the cost limits are counted in memory.
# META_API_KEY comes from the Space's secrets (Settings -> Variables and secrets).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
