# The public dashboard: its read-only API and first-run setup page. Built from the repository
# root (the shared code lives beside this project): docker build -f dashboard/Dockerfile .

FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # No .pyc files, so the image runs with a read-only root filesystem.
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app
COPY core/pyproject.toml core/pyproject.toml
COPY core/src core/src
COPY dashboard/api/pyproject.toml dashboard/api/pyproject.toml
COPY dashboard/api/src dashboard/api/src
RUN pip install ./core ./dashboard/api

# Unprivileged, so dashboard.yaml in the mounted data directory belongs to a real account.
RUN mkdir -p /data && chown -R 1000:1000 /data
USER 1000:1000

EXPOSE 2553

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-m", "ecowitt.dashboard.healthcheck"]

CMD ["python", "-m", "ecowitt.dashboard"]
