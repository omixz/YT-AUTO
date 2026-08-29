# ClipAI / Peakcut - Multi-stage Dockerfile
# Stage 1: Base with system dependencies
FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser

# Stage 2: Build - Install Python dependencies
FROM base AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 3: Runtime
FROM base AS runtime

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application code
COPY --chown=appuser:appuser . .

# Create directories
RUN mkdir -p /app/jobs /app/voices /app/logs && \
    chown -R appuser:appuser /app

# Warm Whisper model (tiny for low memory)
ENV WHISPER_MODEL=tiny
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8')" || true

# Warm Piper voices
ENV PIPER_VOICES_DIR=/app/voices
RUN mkdir -p /app/voices && \
    python3 -m piper.download_voices --download-dir /app/voices es_ES-carlfm-x_low 2>/dev/null || true && \
    python3 -m piper.download_voices --download-dir /app/voices fr_FR-siwis-low 2>/dev/null || true && \
    python3 -m piper.download_voices --download-dir /app/voices pt_BR-faber-medium 2>/dev/null || true

# Go offline for HF after warming
ENV HF_HUB_OFFLINE=1

# Switch to non-root user
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "clipai_app:app", "--host", "0.0.0.0", "--port", "8000"]


# Stage 4: Local Worker (optional - for local hardware fallback)
FROM runtime AS local-worker

USER root
# Install additional packages for local worker
RUN apt-get update && apt-get install -y --no-install-recommends \
    psutil \
    && rm -rf /var/lib/apt/lists/*

USER appuser

# Local worker entrypoint
CMD ["python", "clipai_local_worker.py"]