# ────────────────────────────────────────────────────────
# Server Nexe — Docker image
# Local AI server with persistent memory. Zero cloud.
# https://server-nexe.org
# ────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies (cross-platform only, no macOS deps)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY core/ core/
COPY plugins/ plugins/
COPY memory/ memory/
COPY personality/ personality/
COPY knowledge/ knowledge/
COPY installer/ installer/
COPY pyproject.toml conftest.py install_nexe.py ./

# Qdrant embedded binary (linux)
ARG QDRANT_VERSION=v1.17.0
ARG TARGETARCH=amd64
RUN QDRANT_ARCH=$([ "$TARGETARCH" = "arm64" ] && echo "aarch64-unknown-linux-gnu" || echo "x86_64-unknown-linux-gnu") && \
    curl -sL "https://github.com/qdrant/qdrant/releases/download/${QDRANT_VERSION}/qdrant-${QDRANT_ARCH}.tar.gz" \
    | tar xz -C /app/ && \
    chmod +x /app/qdrant

# Storage directories
RUN mkdir -p /app/storage/qdrant /app/storage/logs /app/storage/sessions

# Non-root user
RUN useradd -m -s /bin/bash nexe && chown -R nexe:nexe /app
USER nexe

# Ports: Nexe API (9119) + Qdrant (6333)
EXPOSE 9119 6333

# Entrypoint
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
