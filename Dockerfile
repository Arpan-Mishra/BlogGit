FROM python:3.12-slim

WORKDIR /app

# Install system deps required by cryptography + uvicorn
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer-cached when requirements unchanged)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY prompts/ ./prompts/

# Expose the API port
# Non-root user for security
RUN useradd --create-home appuser
USER appuser

CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
