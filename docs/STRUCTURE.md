# V3.0 Directory Structure

**Status:** ✅ Self-contained and portable

## Complete Directory Layout

```
V3.0/                                    # Root directory (self-contained)
│
├── 📄 Essential Files (Root)
│   ├── README.md                        # Project overview
│   ├── START_HERE.md                    # Quick start guide ⭐
│   ├── app.py                           # Main Streamlit web interface
│   ├── requirements.txt                 # Python dependencies
│   ├── Dockerfile                       # Container configuration
│   ├── .dockerignore                    # Docker ignore patterns
│   ├── .gitignore                       # Git ignore patterns
│   ├── quickstart.sh                    # One-command setup
│   └── test_setup.sh                    # Automated testing
│
├── 📚 Documentation
│   └── docs/
│       ├── README.md                    # Documentation index
│       ├── GETTING_STARTED.md           # Detailed walkthrough
│       ├── PROJECT_SUMMARY.md           # Technical architecture
│       ├── STRUCTURE.md                 # This file
│       ├── TEST_RESULTS.md              # Test validation results
│       └── FINAL_STATUS.md              # Current status & roadmap
│
├── 💾 Data (Self-contained)
│   └── data/
│       └── parquet/                     # Converted database
│           ├── IGHM/                    # Isotype partition
│           │   ├── ERR1760498_Heavy_IGHM.csv.parquet
│           │   ├── ERR2843386_Heavy_IGHM.csv.parquet
│           │   └── ... (10 files total)
│           └── metadata.parquet         # Subject metadata
│
├── 🔬 Source Code
│   └── src/
│       └── search_engine.py             # DuckDB search engine
│
├── 🛠️ Scripts
│   └── scripts/
│       └── convert_to_parquet.py        # Data converter
│
├── 🧪 Tests
│   └── tests/
│       └── README.md                    # Test plan & status
│
└── 🐍 Virtual Environment
    └── venv/                            # Python virtual env (gitignored)
        ├── bin/
        ├── lib/
        └── ...

```

## Key Features

### ✅ Self-Contained
- **All data in V3.0/data/** - No external dependencies
- **All code in V3.0/** - Complete application
- **Portable** - Can copy entire V3.0/ folder anywhere

### ✅ Organized
- Clear separation: code / data / docs / scripts
- Partitioned data: Organized by isotype
- Clean structure: Easy to navigate

### ✅ Git-Ready
- .gitignore excludes:
  - venv/
  - __pycache__/
  - *.pyc
  - data/ (optional - can commit sample data)

## File Sizes

```
V3.0/                           Total: ~6.5 MB (data) + ~50 MB (venv)
├── data/parquet/              ~6.5 MB (10 sample files)
│   ├── IGHM/*.parquet         ~6.5 MB
│   └── metadata.parquet       ~6 KB
├── src/                       ~10 KB
├── scripts/                   ~8 KB
├── docs/                      ~30 KB
└── venv/                      ~50 MB (dependencies)
```

## Data Partitioning

The Parquet files are organized by **Isotype** for efficient querying:

```
data/parquet/
├── IGHM/          # IgM sequences
│   └── *.parquet
├── IGHG/          # IgG sequences (when converted)
│   └── *.parquet
├── IGHA/          # IgA sequences (when converted)
│   └── *.parquet
└── metadata.parquet
```

This allows DuckDB to:
- Skip entire isotype directories when filtering
- Optimize query performance
- Scale to full database efficiently

## Path Resolution

All paths are **relative to V3.0/** root:

| Component | Path | Resolved To |
|-----------|------|-------------|
| App | `app.py` | `/Users/tomschlegel/ABDB/V3.0/app.py` |
| Engine | `src/search_engine.py` | `/Users/tomschlegel/ABDB/V3.0/src/search_engine.py` |
| Data | `data/parquet/` | `/Users/tomschlegel/ABDB/V3.0/data/parquet/` |
| Scripts | `scripts/*.py` | `/Users/tomschlegel/ABDB/V3.0/scripts/*.py` |

## Moving V3.0

The entire V3.0 directory is **portable**. To move it:

```bash
# Option 1: Copy to new location
cp -r V3.0/ /new/location/

# Option 2: Create tarball
tar -czf abdb-v3.0.tar.gz V3.0/

# Option 3: ZIP archive
zip -r abdb-v3.0.zip V3.0/ -x "*.pyc" "__pycache__/*" "venv/*"
```

After moving, just reinstall dependencies:
```bash
cd /new/location/V3.0
./quickstart.sh
```

## Docker Deployment

When building Docker image, the entire V3.0/ directory is copied:

```dockerfile
WORKDIR /app
COPY . .                    # Copies all of V3.0/
```

The data is included in the image, making it completely self-contained.

## Scaling to Full Database

When converting all 1077 files:

```
V3.0/data/parquet/          Estimated: ~50 GB
├── IGHM/                   ~35 GB (majority of sequences)
├── IGHG/                   ~10 GB
├── IGHA/                   ~3 GB
├── IGHD/                   ~1 GB
├── IGHE/                   ~500 MB
├── Bulk/                   ~500 MB
└── metadata.parquet        ~100 KB
```

## Benefits of This Structure

1. **Portability** - Copy entire folder anywhere
2. **Clarity** - Obvious where everything is
3. **Scalability** - Easy to add more data
4. **Maintainability** - Clean separation of concerns
5. **Docker-ready** - Self-contained for containerization
6. **Git-friendly** - Proper ignore patterns

## Related Files

- **Development**: See `GETTING_STARTED.md`
- **Architecture**: See `PROJECT_SUMMARY.md`
- **Quick Start**: See `START_HERE.md`
- **Test Results**: See `TEST_RESULTS.md`

