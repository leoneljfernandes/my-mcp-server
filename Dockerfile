# syntax=docker/dockerfile:1.7

# ---- Stage 1: Sync skills + install locked Python dependencies with uv ----
FROM ghcr.io/astral-sh/uv:0.6-python3.14-bookworm-slim AS builder

WORKDIR /app

# git is needed only at build time to clone superpowers and my_skills
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock* ./
COPY src ./src
COPY scripts ./scripts
COPY config ./config

RUN uv sync --no-dev --frozen || uv sync --no-dev

# Bake synced skills into the image for fast serverless cold starts (Cloud Run / Render / HF)
RUN --mount=type=secret,id=github_token,required=false \
    sh -c 'if [ -f /run/secrets/github_token ]; then export GITHUB_TOKEN="$(cat /run/secrets/github_token)"; fi; python3 scripts/sync_skills.py --skills-dir /app/skills_store'


# ---- Stage 2: Minimal non-root runtime image (read-only skills, no git, no Node.js) ----
FROM python:3.14-slim-bookworm AS runtime

WORKDIR /app

RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --create-home --home-dir /home/appuser appuser

COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appgroup /app/src /app/src
COPY --from=builder --chown=appuser:appgroup /app/config /app/config
COPY --from=builder --chown=appuser:appgroup /app/skills_store /app/skills_store

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    PORT=8000 \
    MCP_PATH=/mcp \
    SKILLS_DIR=/app/skills_store \
    ROLES_CONFIG_PATH=/app/config/roles.yaml

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=3)"

CMD ["devteam-skills-mcp"]
