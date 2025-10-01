#!/bin/bash
# Quick start script for ABDB V3.0

echo "=================================="
echo "ABDB V3.0 - Quick Start"
echo "=================================="
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo ""
echo "✓ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Convert sample data:"
echo "   python scripts/convert_to_parquet.py --input ../Server/DB --limit 10"
echo ""
echo "2. Run the web interface:"
echo "   streamlit run app.py"
echo ""

