# The public dashboard: its pages, its read-only API and its first-run setup page. Built from the
# repository root (the shared code lives beside this project): docker build -f dashboard/Dockerfile .

# The pages, built once; only the result goes into the image.
FROM node:24-alpine AS web
WORKDIR /web
COPY dashboard/web/package.json dashboard/web/package-lock.json dashboard/web/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY dashboard/web/ ./
RUN npm run build

FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # No .pyc files, so the image runs with a read-only root filesystem.
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    WEB_DIR=/app/web

WORKDIR /app
COPY core/pyproject.toml core/pyproject.toml
COPY core/src core/src
COPY dashboard/api/pyproject.toml dashboard/api/pyproject.toml
COPY dashboard/api/src dashboard/api/src
RUN pip install ./core ./dashboard/api
COPY --from=web /web/dist /app/web

# Unprivileged, so dashboard.yaml in the mounted data directory belongs to a real account.
RUN mkdir -p /data && chown -R 1000:1000 /data
USER 1000:1000

EXPOSE 2553

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-m", "ecowitt.dashboard.healthcheck"]

CMD ["python", "-m", "ecowitt.dashboard"]
