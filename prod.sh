#!/bin/bash
# Production script for Antibody Search Database

echo "🔬 Starting Antibody Search Database Production Environment"
echo "=========================================================="

# Check if Docker Compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose not found. Please install Docker Compose."
    exit 1
fi

# Start production services
docker-compose up --build -d

echo ""
echo "✅ Production environment started!"
echo "   Use 'docker-compose logs -f' to view logs"
echo "   Use 'docker-compose down' to stop services"
