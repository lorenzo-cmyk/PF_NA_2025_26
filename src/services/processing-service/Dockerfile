FROM python:3.14.3-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies (cache-friendly layer)
COPY pyproject.toml README.md ./
RUN uv sync --no-install-project

# Copy application source and install the project
COPY processing_service/ processing_service/
RUN uv sync

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uv", "run", "processing-service"]
