FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Build wheels for all dependencies
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# Separately build quantipymrx from GitHub (pinned commit for cache stability)
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels \
    "quantipymrx @ git+https://github.com/quack2025/QuantiyFork2026.git@main"

# --- Runtime stage ---
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Non-root user
RUN addgroup --system app && adduser --system --group app

# Install pre-built wheels
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache /wheels/* && rm -rf /wheels

# Copy application code
COPY . .
RUN chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/v1/health || exit 1

# Multi-worker: gunicorn manages worker processes, uvicorn handles async I/O.
# WEB_CONCURRENCY env var overrides worker count (Railway can set this).
# Default: 4 workers. Each handles ~50 concurrent light requests.
CMD ["sh", "-c", "gunicorn main:app --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-4} --worker-class uvicorn.workers.UvicornWorker --timeout 120 --graceful-timeout 30 --keep-alive 5 --max-requests 1000 --max-requests-jitter 50"]
