# ABDB V3.0 - Optimized Antibody Database Search

High-performance antibody sequence search tool using DuckDB and Parquet for 100-1000x faster queries.

## Overview

This version replaces the pandas-based approach with:
- **DuckDB**: Lightning-fast analytical query engine
- **Parquet**: Columnar storage format (5-10x faster than CSV)
- **Streamlit**: Modern web interface
- **Docker**: Easy deployment

## Architecture

```
V3.0/                          # Self-contained V3.0 directory
├── app.py                     # Streamlit web interface (main entry)
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container configuration
│
├── src/
│   └── search_engine.py       # DuckDB query engine
│
├── scripts/
│   └── convert_to_parquet.py  # CSV.gz → Parquet converter
│
├── data/                      # All data contained here
│   └── parquet/               # Converted database files
│       ├── IGHM/              # Partitioned by isotype
│       │   ├── *.parquet      # Individual sequence files
│       └── metadata.parquet   # Subject and study metadata
│
├── tests/                     # Validation tests
│
├── docs/                      # Documentation
│   ├── START_HERE.md
│   ├── GETTING_STARTED.md
│   └── PROJECT_SUMMARY.md
│
└── venv/                      # Virtual environment (gitignored)
```

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Convert Sample Data
```bash
python scripts/convert_to_parquet.py --input ../Server/DB --limit 10
```

### 3. Run Web Interface
```bash
streamlit run app.py
```

### 4. Explore Data (Optional)
```bash
jupyter notebook explore_data.ipynb
```
Use this notebook to verify data conversion and explore Parquet files.

## Performance

| Metric | V1.0 (Pandas) | V3.0 (DuckDB) | Improvement |
|--------|---------------|---------------|-------------|
| Search Time | Hours | Seconds-Minutes | 100-1000x |
| Memory | 10-50 GB | 1-5 GB | 10x less |
| Storage | ~100 GB | ~50 GB | 2x smaller |

## Documentation

- **[START_HERE.md](START_HERE.md)** - Quick start guide ⭐ (read this first!)
- **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)** - Detailed walkthrough with examples
- **[docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md)** - Technical architecture and design
- **[docs/STRUCTURE.md](docs/STRUCTURE.md)** - Complete directory layout
- **[docs/TEST_RESULTS.md](docs/TEST_RESULTS.md)** - Validation and performance results
- **[docs/FINAL_STATUS.md](docs/FINAL_STATUS.md)** - Current status and next steps

## Development Status

- [x] Phase 1: Proof of Concept (Complete ✅)
- [ ] Phase 2: Full Database Conversion
- [ ] Phase 3: Production Web Interface
- [ ] Phase 4: AWS Deployment

## License

GNU GPLv3 (same as V1.0)

## Author

Tom U. Schlegel (tom.schlegel@uni-leipzig.de)

