# The application as one image: both listeners, the parser and the writer.
#
# One container rather than two because the admin listener renders what the ingest listener
# has just received, which is in-process state.

FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # No .pyc files, so the image runs with a read-only root filesystem: the interpreter
    # would otherwise try to write __pycache__ beside the installed package on first import.
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/src ./src
RUN pip install .

# Runs as an unprivileged user so that everything written into the mounted data directory is
# owned by a real account on the host rather than by root.
RUN mkdir -p /data && chown -R 1000:1000 /data
USER 1000:1000

# 8000 is the ingest listener, which a station reaches; 8001 is the admin listener, which
# belongs behind a reverse proxy. Publishing them differently is what keeps the second one off
# the internet -- see the README.
EXPOSE 8000 8001

# An HTTP probe rather than a port check: it reports both listeners, and one of the two
# failing to bind while the other serves would otherwise look healthy while every report the
# station sent went nowhere.
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-m", "ecowitt.healthcheck"]

CMD ["python", "-m", "ecowitt"]
