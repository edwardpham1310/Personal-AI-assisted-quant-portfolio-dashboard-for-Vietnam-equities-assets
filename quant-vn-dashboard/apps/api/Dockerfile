FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install runtime deps first for better layer caching.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e .

# Copy source.
COPY src ./src
COPY tests ./tests

EXPOSE 8000

# Production command. For dev, override with `--reload`.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
