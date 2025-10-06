GoogleDoc: https://docs.google.com/document/d/1BVCAJVQurnfQZvjDsTJ6hv-I6SYsuBtdR76jlq3Z0-A/edit?tab=t.0

Dev-Server: http://172.22.180.238/

### For local start w/o docker:

```bash
source venv/bin/activate
export ABHUNTER_DB_PATH=./data
streamlit run app.py
```



# ABHunter - Optimized Antibody Database Search

High-performance antibody sequence search tool using DuckDB and Parquet

## Overview

## Architecture

```
antibody_search/               # Self-contained antibody_search directory
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
python scripts/convert_to_parquet.py --input ../Server/DB
```

### 3. Run Web Interface
```bash
streamlit run app.py
```

## License

## Author