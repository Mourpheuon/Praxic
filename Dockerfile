# Build: docker build -t praxic .
FROM python:3.12-slim
LABEL org.opencontainers.image.title="Praxic"
ARG PRAXIC_VERSION=0.2.0
LABEL org.opencontainers.image.version=$PRAXIC_VERSION
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Same declared runtime dependencies as desktop builds.
COPY pyproject.toml README.md config.toml.example ./
COPY praxic/ ./praxic/
RUN pip install --no-cache-dir ".[desktop]"

RUN useradd --create-home --shell /bin/bash praxic \
    && mkdir -p /app/data /app/workspace /app/logs \
    && chown -R praxic:praxic /app
USER praxic
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/setup/status || exit 1
CMD ["python", "-m", "uvicorn", "praxic.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
