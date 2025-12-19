GoogleDoc: https://docs.google.com/document/d/1BVCAJVQurnfQZvjDsTJ6hv-I6SYsuBtdR76jlq3Z0-A/edit?tab=t.0

Dev-Server from IWE: http://172.22.180.238/

# ABHunter - Optimized Antibody Database Search

We introduce ABHUNTER, a database search tool that systematically analyzes antibody sequence and population repertoire data to identify individuals possessing the necessary gene segments and paratope features for bnAb development. By quantifying the accessibility of bnAb precursors, ABHUNTER facilitates the prioritization of bnAb lineages with high therapeutic and vaccine potential, enabling rational design of broadly effective germline-targeting interventions.

### For local execution w/o docker

#### Installation
```bash
# Only once for installation:
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# clone repository, go into the antibody_search directory
git clone https://github.com/VIIC12/antibody_search.git
cd antibody_search

# Download database files
...

# Install dependencies
pip install -r requirements.txt
```

#### Execution
```bash
export ABHUNTER_DB_PATH=./data
streamlit run app.py
```
then open the link in your browser

# Overview

## Architecture

High-performance antibody sequence search tool using DuckDB and Parquet
```
antibody_search/               # Self-contained antibody_search directory
├── app.py                     # Streamlit web interface (main entry)
├── pages/
│   ├── search.py              # Search page
│   └── imprint.py             # Imprint page
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container configuration
│
├── src/
│   └── search_engine.py       # DuckDB query engine
│
├── components/
│   └── search/                # Search components
│       ├── ... *.py           # Search components
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
└── venv/                      # Virtual environment (gitignored)
```

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Web Interface
```bash
streamlit run app.py
```

## Custom Database
### Download and convert OAS files to Parquet format
This will download the OAS files from the OAS server and convert them to Parquet format. Use --help to see all options.
```bash
python scripts/update_from_oas.py --help
```

## License

## Author