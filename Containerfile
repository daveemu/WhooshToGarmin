# Container image for the myWhoosh -> Garmin Connect sync service.
# Build with: podman build -t whooshtogarmin:latest .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    WHOOSH2GARMIN_DATA_DIR=/data

WORKDIR /app

# Install the package, then the Chromium browser plus its system dependencies.
COPY pyproject.toml README.md ./
COPY whooshtogarmin ./whooshtogarmin
RUN pip install . \
    && playwright install --with-deps chromium

# Persistent state: session.json, garmin_tokens/, state.json, downloads/
VOLUME ["/data"]

# Default command runs the polling loop; override with `--once` for a one-shot.
ENTRYPOINT ["whooshtogarmin"]
