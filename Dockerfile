FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Dependencies first so source edits do not bust the install layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend ./backend
COPY mock_logistics_data.csv ./

RUN uv sync --frozen --no-dev

# PORT is read at container start, not build time - Railway (and most PaaS
# hosts) assign it dynamically, so the CMD must expand it rather than bake in
# a fixed value. The default keeps `docker run` and docker-compose working
# unchanged when nothing overrides it.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uv run --no-dev uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
