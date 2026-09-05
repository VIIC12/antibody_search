# ABDB V3.0 - Docker Configuration
FROM python:3.11-slim

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
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p data/parquet

# Expose Streamlit port
EXPOSE 8501

# Health check
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Run Streamlit with development-friendly defaults
CMD ["streamlit", "run", "app.py"]

