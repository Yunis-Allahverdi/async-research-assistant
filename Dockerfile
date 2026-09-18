# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Don't write .pyc files; flush logs straight to the console.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so this layer is cached unless requirements change.
COPY requirements-ai.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-ai.txt -r requirements.txt

# Copy the rest of the project (see .dockerignore for what is excluded).
COPY . .

# Default: run the offline demo end-to-end — no API keys, no network needed.
CMD ["python", "demo_ai.py", "--offline"]