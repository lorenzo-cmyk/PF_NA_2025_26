FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cache-friendly layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy application code
COPY camera_emulator/ camera_emulator/
COPY scenes.json README.md ./
RUN uv sync --frozen

EXPOSE 8080

CMD ["uv", "run", "camera-emulator"]
