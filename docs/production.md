# Production Deployment Guide

This document describes how to deploy Dristi in a production environment using Docker Compose.

## Overview

The production stack (`docker/docker-compose.prod.yml`) runs:

- **web**: Gunicorn serving the Django API (2 replicas by default)
- **worker**: Dramatiq background workers (2 replicas by default)
- **db**: PostgreSQL
- **redis**: Redis for cache and the Dramatiq queue
- **rustfs**: S3-compatible object store for media uploads (MinIO by default)
- **nginx**: Reverse proxy and static file server

Images are built and pushed to `ghcr.io/<owner>/dristi` automatically on every push to `main` via `.github/workflows/docker-publish.yml`.

## Prerequisites

- A host with Docker and Docker Compose installed
- Exported production environment variables (see `.env.prod.example`)
- Network access to pull the image from GitHub Container Registry (or build locally)

## Required environment variables

At minimum, export the following on the target host:

```bash
export SECRET_KEY="<generate-a-long-random-secret>"
export ALLOWED_HOSTS="api.example.com"
export CSRF_TRUSTED_ORIGINS="https://api.example.com"
export CORS_ALLOWED_ORIGINS="https://app.example.com"
export DB_PASSWORD="<secure-postgres-password>"
export S3_API_ENDPOINT="http://rustfs:9000"
export S3_BUCKET="dristi-media"
export S3_ACCESS_KEY="<s3-access-key>"
export S3_SECRET_KEY="<s3-secret-key>"
```

See `.env.prod.example` for the full list of supported variables.

## Deploy

1. Pull or build the production image:

   ```bash
   # Pull the latest image from GHCR (requires docker login ghcr.io)
   docker pull ghcr.io/<owner>/dristi:main

   # Or build locally
   docker build -f docker/Dockerfile -t dristi:latest .
   ```

2. Start the stack:

   ```bash
   docker compose -f docker/docker-compose.prod.yml up -d
   ```

3. Run migrations:

   ```bash
   docker compose -f docker/docker-compose.prod.yml exec web python manage.py migrate
   ```

4. Create the first superuser:

   ```bash
   docker compose -f docker/docker-compose.prod.yml exec web python manage.py createsuperuser
   ```

5. Verify the deployment:

   - API health: `https://api.example.com/api/v1/health/`
   - System health: `https://api.example.com/health/`

## Notes

- The production image runs as a non-root user (`appuser`).
- Static files are collected into the `staticfiles` shared volume on container startup.
- Media uploads are stored in the S3-compatible `rustfs` object store by default. You can point the `s3_*` variables at an external S3-compatible service if preferred.
- HTTPS is enforced via Django security settings. Ensure Nginx or your load balancer terminates TLS and forwards the `X-Forwarded-Proto` header.
