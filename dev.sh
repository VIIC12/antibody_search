#!/bin/bash
# Development script for Antibody Search Database

echo "🔬 Starting Antibody Search Database Development Environment"
echo "=========================================================="

# Check if Docker Compose is available
if ! command -v docker compose &> /dev/null; then
    echo "❌ docker compose not found. Please install Docker Compose."
    exit 1
fi

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Please create one with ABHUNTER_DB_PATH pointing to the directory containing the databases." 
fi

echo ""
echo "🚀 Starting development services..."
echo "   - Production app: http://172.22.180.238 or http://antibody.localhost"
echo "   - Development app: http://172.22.180.238/dev or http://antibody.localhost/dev"
echo ""

# Start development services with Docker Watch
docker compose --profile dev up -d antibody-search-dev --build

