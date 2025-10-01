# Getting Started with ABDB V3.0

## Quick Start (5 minutes)

### Step 1: Setup Environment

```bash
cd V3.0
./quickstart.sh
```

This will:
- Create a Python virtual environment
- Install all required dependencies

### Step 2: Convert Sample Data

Convert 10 sample files from your Server/DB directory:

```bash
source venv/bin/activate
python scripts/convert_to_parquet.py --input ../Server/DB --limit 10
```

**What this does:**
- Reads CSV.gz files
- Extracts metadata
- Converts to optimized Parquet format
- Creates partitioned structure by Isotype

**Expected output:**
```
✓ Registered 10 Parquet files
✓ Total sequences: 50,000-100,000 (varies by files)
✓ Compression: 2-5x better than gzip
```

### Step 3: Run the Web Interface

```bash
streamlit run app.py
```

Your browser will automatically open to http://localhost:8501

## Example Searches

### Search 1: Find IGHV3-23 sequences
```
IGHV: 3-23
IGHD: (leave empty)
IGHJ: (leave empty)
CDRH3 Length: (leave empty)
Motif: (leave empty)
```

### Search 2: Find sequences with specific motif
```
IGHV: 3-
IGHD: 2-
IGHJ: 4
CDRH3 Length: 15
Motif: YY.D.*G
```

### Search 3: Multiple genes
```
IGHV: 3-20|3-22
IGHD: 2-15|2-18
IGHJ: 4|5
```

## Understanding Results

### Statistics View (Default)
- **Fast**: Returns in seconds
- Shows hits per subject
- Includes percentages and per-million rates

### Full Results View
- **Slower**: May take minutes for large result sets
- Returns all matching sequences
- Includes all columns (v_call, d_call, j_call, junction_aa, etc.)
- Downloadable as CSV

## Performance Comparison

| Operation | V1.0 (Pandas) | V3.0 (DuckDB) | Speedup |
|-----------|---------------|---------------|---------|
| Search 1077 files | ~2-4 hours | ~30-60 seconds | **100-200x** |
| Statistics only | ~1-2 hours | ~5-10 seconds | **500-1000x** |
| Memory usage | 10-50 GB | 1-5 GB | **10x less** |

## Converting Full Database

Once you're satisfied with the proof-of-concept, convert all files:

```bash
# Convert all files (this will take 30-60 minutes)
python scripts/convert_to_parquet.py --input ../Server/DB

# Or run in background
nohup python scripts/convert_to_parquet.py --input ../Server/DB > conversion.log 2>&1 &
```

**Storage requirements:**
- Input: ~100 GB (gzipped CSV)
- Output: ~50 GB (Parquet)
- Peak disk: ~150 GB during conversion

## Docker Deployment

### Build Image
```bash
docker build -t abdb:v3.0 .
```

### Run Container
```bash
docker run -p 8501:8501 \
  -v $(pwd)/data:/app/data \
  abdb:v3.0
```

### Docker Compose (Recommended)
```bash
docker-compose up -d
```

## Troubleshooting

### Issue: "No Parquet files found"
**Solution:** Run the conversion script first:
```bash
python scripts/convert_to_parquet.py --input ../Server/DB --limit 10
```

### Issue: Out of memory
**Solution:** Reduce batch size or limit results:
- Use "Statistics Only" mode
- Set lower "Max Results" limit
- Close other applications

### Issue: Slow searches
**Possible causes:**
1. First search is slower (DuckDB warming up)
2. Using regex patterns (slower than exact matches)
3. Full results mode on large datasets

**Solutions:**
- Use statistics mode first
- Be more specific with search criteria
- Use exact matches when possible

## Next Steps

1. ✅ Test with sample data (10 files)
2. ⏭️ Validate results match V1.0
3. ⏭️ Convert full database
4. ⏭️ Run benchmarks
5. ⏭️ Deploy to production server

## Support

- **Issues:** Open a GitHub issue
- **Questions:** Contact tom.schlegel@uni-leipzig.de
- **Documentation:** See README.md

## Tips & Best Practices

### For Faster Searches:
1. **Be specific**: More criteria = faster search
2. **Use statistics mode** when you don't need sequences
3. **Avoid complex regex** patterns if possible
4. **Limit results** when using full mode

### For Better Results:
1. **Use partial matches**: "3-" finds all 3-* genes
2. **Combine criteria**: Multiple filters narrow results
3. **Check examples**: See successful searches in sidebar

### For Development:
1. **Test with sample data first**
2. **Validate against V1.0**
3. **Benchmark before full deployment**
4. **Monitor memory usage**

