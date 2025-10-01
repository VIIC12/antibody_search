# ABDB V3.0 Documentation

Complete documentation for the high-performance antibody database search system.

## 📚 Documentation Index

### Quick Start
- **[../START_HERE.md](../START_HERE.md)** ⭐ - **Start here!** Quick 5-minute setup guide
- **[GETTING_STARTED.md](GETTING_STARTED.md)** - Detailed walkthrough with examples and troubleshooting

### Technical Documentation
- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - Architecture, design decisions, and technical details
- **[STRUCTURE.md](STRUCTURE.md)** - Complete directory layout and organization
- **[TEST_RESULTS.md](TEST_RESULTS.md)** - Performance validation and test results
- **[FINAL_STATUS.md](FINAL_STATUS.md)** - Current project status and roadmap

### Development
- **[../README.md](../README.md)** - Project overview and quick reference

## 🎯 Where to Start

### First Time User?
1. Read **[START_HERE.md](../START_HERE.md)** (5 minutes)
2. Run `./quickstart.sh` or `./test_setup.sh`
3. Launch: `streamlit run app.py`

### Want Details?
- **How it works**: [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)
- **Step-by-step guide**: [GETTING_STARTED.md](GETTING_STARTED.md)
- **Directory structure**: [STRUCTURE.md](STRUCTURE.md)

### Need Validation?
- **Test results**: [TEST_RESULTS.md](TEST_RESULTS.md)
- **Performance benchmarks**: [FINAL_STATUS.md](FINAL_STATUS.md)

## 📖 Documentation by Topic

### Setup & Installation
- [GETTING_STARTED.md](GETTING_STARTED.md#quick-start-5-minutes)
- [FINAL_STATUS.md](FINAL_STATUS.md#ready-to-use)

### Usage & Examples
- [GETTING_STARTED.md](GETTING_STARTED.md#example-searches)
- [START_HERE.md](../START_HERE.md#try-this-first-search)

### Architecture & Design
- [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md#architecture)
- [STRUCTURE.md](STRUCTURE.md#key-features)

### Performance & Testing
- [TEST_RESULTS.md](TEST_RESULTS.md)
- [FINAL_STATUS.md](FINAL_STATUS.md#performance-verified)

### Deployment
- [GETTING_STARTED.md](GETTING_STARTED.md#docker-deployment)
- [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md#docker-deployment)

### Troubleshooting
- [GETTING_STARTED.md](GETTING_STARTED.md#troubleshooting)
- [FINAL_STATUS.md](FINAL_STATUS.md#support--resources)

## 🔍 Quick Reference

### Commands
```bash
# Setup
./quickstart.sh

# Convert data (10 files)
python scripts/convert_to_parquet.py --input ../Server/DB --limit 10

# Run app
streamlit run app.py

# Convert full database
python scripts/convert_to_parquet.py --input ../Server/DB
```

### File Locations
- **Main app**: `app.py`
- **Search engine**: `src/search_engine.py`
- **Data**: `data/parquet/`
- **Scripts**: `scripts/`
- **Tests**: `tests/` (TBD)

### Key Metrics
- **Speed**: 100-1000x faster than V1.0
- **Memory**: <500 MB (vs 10-50 GB)
- **Storage**: 49.6x compression
- **Current data**: 648,609 sequences (10 sample files)

## 📝 Contributing

When adding new documentation:
1. Place detailed docs in `docs/`
2. Keep only essential docs in root (README, START_HERE)
3. Update this index
4. Use markdown for consistency
5. Include code examples where relevant

## 🆘 Need Help?

- **Quick questions**: See [START_HERE.md](../START_HERE.md)
- **Detailed issues**: See [GETTING_STARTED.md](GETTING_STARTED.md#troubleshooting)
- **Technical details**: See [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)
- **Contact**: tom.schlegel@uni-leipzig.de

---

**Last Updated**: October 1, 2024  
**Version**: 3.0.0 (Proof of Concept)

