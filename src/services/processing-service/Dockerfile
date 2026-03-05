FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cache-friendly layer)
COPY pyproject.toml ./
RUN uv sync --no-install-project

# Copy application code
COPY processing_service/ processing_service/
COPY README.md ./
RUN uv sync

EXPOSE 8000

CMD ["uv", "run", "processing-service"]
