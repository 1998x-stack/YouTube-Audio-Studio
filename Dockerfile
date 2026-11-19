FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DENO_INSTALL=/opt/deno PATH=/opt/deno/bin:$PATH \
    STUDIO_ROOT=/data STUDIO_SCRATCH=/scratch STUDIO_HOST=0.0.0.0
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip ffmpeg && rm -rf /var/lib/apt/lists/*
# yt-dlp's YouTube challenge support uses an external JS runtime (Deno).
RUN curl -fsSL https://deno.land/install.sh | sh
WORKDIR /app
COPY pyproject.toml /app/
COPY studio/ /app/studio/
COPY app.py /app/
RUN pip install --no-cache-dir .
EXPOSE 7860
CMD ["python", "app.py"]
