FROM python:3.11-slim

WORKDIR /app

# System dependencies (ffmpeg for audio extraction, curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY media-dl/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY media-dl/src/ ./src/

# Create downloads directory
RUN mkdir -p /app/data/downloads

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
