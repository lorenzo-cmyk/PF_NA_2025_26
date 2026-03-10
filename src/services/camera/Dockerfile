FROM python:3.12-slim

# System deps for OpenCV (headless) and ONNX Runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project metadata first for layer caching
COPY pyproject.toml .

# Install dependencies (no editable, no dev extras)
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy application source
COPY main.py .
COPY camera/ camera/
COPY model/ model/
COPY samples/ samples/

# Runtime directories (model and images are mounted/provided at runtime)
RUN mkdir -p data/images

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "main.py"]
