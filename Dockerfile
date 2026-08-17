# ABHunter - publication image
FROM python:3.12.13-slim-bookworm AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements-server.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements-server.txt

FROM python:3.12.13-slim-bookworm

WORKDIR /app

# Chromium is required for Plotly/Kaleido image export
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        chromium \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --create-home --home-dir /home/app app && \
    mkdir -p /app/data/abhunter /app/downloads /app/logs /app/igblast && \
    chown -R app:app /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    ABHUNTER_DB_PATH=/app/data/abhunter \
    ABHUNTER_DOWNLOAD_DIR=/app/downloads \
    ABHUNTER_IGBLAST_PATH=/app/igblast \
    CHROME_BIN=/usr/bin/chromium \
    CHROMIUM_FLAGS=--no-sandbox

USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
