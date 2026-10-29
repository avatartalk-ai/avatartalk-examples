FROM python:3.12-slim

ENV UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE="copy" \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install requirements
RUN apt-get update && apt-get install --no-install-recommends -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY ./src /app/src
COPY ./static /app/static
COPY ./templates /app/templates
COPY ./data /app/data
COPY ./run.sh /app/run.sh

CMD ["./run.sh"]
