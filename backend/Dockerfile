FROM node:24-bookworm-slim AS a03
WORKDIR /agent
COPY agents/a03/package.json agents/a03/package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY --from=a03 /usr/local/bin/node /usr/local/bin/node
COPY --from=a03 /agent/node_modules ./agents/a03/node_modules
COPY agents/a03/src ./agents/a03/src
COPY agents/a03/resources ./agents/a03/resources
COPY agents/a03/package-lock.json ./agents/a03/package-lock.json
RUN uv sync --locked --no-dev
RUN useradd --create-home --uid 10001 cheeta
USER cheeta
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
