FROM python:3.14.3-slim

# System deps for OpenCV (headless) and ONNX Runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies (cache-friendly layer)
COPY pyproject.toml README.md ./
RUN uv sync --no-install-project

# Copy application source and install the project
COPY main.py .
COPY camera/ camera/
COPY model/ model/
COPY samples/ samples/
RUN uv sync

# Runtime directories (images are written here at runtime)
RUN mkdir -p data/images

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uv", "run", "camera"]
