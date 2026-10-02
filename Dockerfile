FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5250

WORKDIR /app

# Install system dependencies including gosu
RUN apt-get update && \
    apt-get install -y --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and config
COPY plex_playlist_sync ./plex_playlist_sync
COPY pyproject.toml README.md ./
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create data, music, and downloads directories and non-root app user
RUN useradd --create-home --uid 1000 appuser && \
    mkdir -p /data /music /downloads && \
    chown -R appuser:appuser /app /data /music /downloads

EXPOSE 5250

VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5250/api/health')" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "plex_playlist_sync"]