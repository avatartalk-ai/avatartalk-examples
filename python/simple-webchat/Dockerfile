FROM python:3.12-slim

ENV UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE="copy" \
    PATH="/app/.venv/bin:$PATH" \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    APP_DEBUG=false

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY ./src /app/src
COPY ./templates /app/templates

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

EXPOSE 8000

CMD ["simple-webchat"]
