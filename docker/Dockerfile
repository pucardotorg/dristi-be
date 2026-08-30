# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim as base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY src/requirements /app/requirements
RUN pip install --no-cache-dir -r /app/requirements/production.txt

# Copy application code
COPY src /app

# Inject the Git commit SHA into the image (passed via --build-arg).
ARG GIT_COMMIT_SHA
RUN sed -i "s/^GIT_COMMIT_SHA = \"unknown\"/GIT_COMMIT_SHA = \"$GIT_COMMIT_SHA\"/" /app/config/settings/version.py

# Make entrypoint executable
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
