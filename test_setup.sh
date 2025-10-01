#!/bin/bash
# Test setup script - runs full proof of concept

set -e  # Exit on error

echo "============================================"
echo "ABDB V3.0 - Proof of Concept Test"
echo "============================================"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Check prerequisites
echo -e "${BLUE}Step 1: Checking prerequisites...${NC}"
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.9+"
    exit 1
fi
echo "✓ Python 3 found"

# Check if Server/DB exists
if [ ! -d "../Server/DB" ]; then
    echo "❌ ../Server/DB directory not found"
    echo "Please ensure you're in the V3.0 directory and Server/DB exists"
    exit 1
fi
echo "✓ Server/DB directory found"

# Count files
FILE_COUNT=$(ls -1 ../Server/DB/*.csv.gz 2>/dev/null | wc -l | tr -d ' ')
echo "✓ Found $FILE_COUNT CSV.gz files"
echo ""

# Step 2: Setup environment
echo -e "${BLUE}Step 2: Setting up environment...${NC}"
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "✓ Virtual environment activated"

echo "Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✓ Dependencies installed"
echo ""

# Step 3: Convert sample data
echo -e "${BLUE}Step 3: Converting sample data (10 files)...${NC}"
echo "This may take 30-60 seconds..."
python scripts/convert_to_parquet.py --input ../Server/DB --limit 10

if [ ! -d "data/parquet" ]; then
    echo "❌ Conversion failed - no parquet directory created"
    exit 1
fi

PARQUET_COUNT=$(find data/parquet -name "*.parquet" -not -name "metadata.parquet" | wc -l | tr -d ' ')
echo "✓ Converted $PARQUET_COUNT files to Parquet"
echo ""

# Step 4: Run quick validation
echo -e "${BLUE}Step 4: Validating conversion...${NC}"
python3 << EOF
import sys
sys.path.insert(0, 'src')
from search_engine import AntibodySearchEngine

try:
    engine = AntibodySearchEngine(data_dir="data/parquet")
    print(f"✓ Search engine initialized")
    print(f"✓ Total sequences loaded: {engine.total_sequences:,}")
    
    # Quick test search
    results_df, stats = engine.search(ighv="3-", full_results=False)
    print(f"✓ Test search successful: {stats['total_hits']:,} hits in {stats['search_time']}s")
    
    engine.close()
except Exception as e:
    print(f"❌ Validation failed: {e}")
    sys.exit(1)
EOF

if [ $? -ne 0 ]; then
    echo "❌ Validation failed"
    exit 1
fi
echo ""

# Step 5: Success message
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}✓ PROOF OF CONCEPT READY!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Next step: Launch the web interface"
echo ""
echo -e "${YELLOW}Run:${NC}"
echo "  streamlit run app.py"
echo ""
echo "Or test more files:"
echo "  python scripts/convert_to_parquet.py --input ../Server/DB --limit 50"
echo ""
echo "See GETTING_STARTED.md for more information"
echo ""

