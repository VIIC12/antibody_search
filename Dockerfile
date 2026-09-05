# ABHunter - Docker Configuration
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies (including Chromium for Plotly/Kaleido image export,
# and pigz for the parallel-gzip tar archives built by components/search/download_utils.py)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    chromium \
    pigz \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Copy application code
COPY . .

# Create mount points for the volumes docker-compose.yml binds at runtime
RUN mkdir -p /app/data/abhunter /app/downloads /app/logs

# Expose Streamlit port
EXPOSE 8501

# Health check
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Run Streamlit with development-friendly defaults
CMD ["streamlit", "run", "app.py"]

