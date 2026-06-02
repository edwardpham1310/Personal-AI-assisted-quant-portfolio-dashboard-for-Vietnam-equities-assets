FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy source BEFORE editable install: pyproject.toml's
# ``[tool.setuptools] package-dir = { "" = "src" }`` makes setuptools
# read src/ during ``pip install -e .``, so the directory must exist
# in the image layer at that point.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e .

# Tests copied separately for parity with dev tree (kept out of the
# pip-install layer to keep test-only churn from rebusting deps).
COPY tests ./tests

EXPOSE 8000

# Production command. For dev, override with `--reload`.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
