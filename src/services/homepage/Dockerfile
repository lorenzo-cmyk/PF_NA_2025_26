FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cache-friendly layer)
COPY pyproject.toml ./
RUN uv sync --no-install-project

# Copy application code
COPY homepage/ homepage/
COPY README.md ./
RUN uv sync

EXPOSE 8090

CMD ["uv", "run", "homepage"]
