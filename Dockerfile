# Nexe Server Dockerfile
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NEXE_ENV=production \
    PYTHONPATH=/app

# Install system dependencies
# curl/git for downloading models/tools if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create storage directory and set permissions
RUN mkdir -p /app/storage/qdrant && \
    chmod -R 777 /app/storage

# Expose port
EXPOSE 9119

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9119/health || exit 1

# Run the server
CMD ["python", "-m", "core.cli", "go"]
