FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for pdf2image
RUN apt-get update && apt-get install -y \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Default port (Railway provides PORT env var)
ENV PORT=8000
EXPOSE ${PORT}

# Default: start the API server (overridden per-service via railway config)
CMD sh -c 'python -m scripts.startup && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'
