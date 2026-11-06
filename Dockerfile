# claude-rotate in a container. See deploy/compose.yaml for how to run it.
#
#   /config  config.json and the token files, mounted read-only
#   /data    state.json, usage files and audit.jsonl, mounted read-write
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLAUDE_ROTATE_CONFIG=/config/config.json \
    CLAUDE_ROTATE_STATE=/data/state.json \
    CLAUDE_ROTATE_AUDIT=/data/audit.jsonl \
    CLAUDE_ROTATE_BIND=0.0.0.0

WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.lock

# --chmod: a checkout made under a strict umask must still be readable by the
# unprivileged user below.
COPY --chmod=0644 rotator.py oai_compat.py LICENSE ./
RUN useradd --system --uid 10001 --no-create-home claude-rotate \
 && mkdir /data \
 && chown 10001:10001 /data
USER 10001

EXPOSE 8484
# Exec form, so Python is PID 1 and receives SIGHUP (reload) and SIGTERM (stop).
CMD ["python", "rotator.py"]
