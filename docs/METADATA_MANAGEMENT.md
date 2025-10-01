# Metadata Management in ABDB V3.0

## 📊 Understanding Metadata

### Two Types of Metadata

#### **1. Parquet File Metadata (Built-in, Automatic)**
- **Location:** Inside each `.parquet` file
- **Created:** Automatically during conversion
- **Updated:** Never (immutable)
- **Size:** Few KB per file
- **Purpose:** Query optimization

#### **2. OAS Metadata Table (`metadata.parquet`)**
- **Location:** `data/parquet/metadata.parquet`
- **Created:** By conversion script after batch
- **Updated:** When you convert files or manually reindex
- **Size:** ~6 KB (for current data)
- **Purpose:** Subject statistics, study info

---

## 🔄 When Metadata Gets Created/Updated

### Initial Database Setup
```bash
# Convert 10 files
python scripts/convert_to_parquet.py --input ../Server/DB --limit 10
```

**What happens:**
1. **For each CSV.gz:**
   - Converts to Parquet
   - Parquet library automatically writes file metadata (row count, stats, schema)

2. **After all conversions:**
   - Script creates `metadata.parquet` summary table
   - Contains: filename, subject, rows, isotype, etc.

---

## ✏️ Manually Reindexing

### When to Reindex

**Important Discovery:** Reindexing is **optional** for most operations!

**You MUST reindex when:**
- ✅ You manually copy Parquet files (not via conversion script)
- ✅ Subject statistics seem incorrect
- ✅ You want accurate per-subject percentages

**You DON'T need to reindex when:**
- ❌ Using conversion script (handles metadata automatically)
- ❌ Just viewing total counts (DuckDB auto-detects files)
- ❌ Deleting files (total count auto-updates)

**Optional but good practice:**
- 🔍 Periodic verification (`--verify`)
- 🔍 After major database changes
- 🔍 Troubleshooting accuracy issues

### How to Reindex

**Option 1: Verify First (Recommended)**
```bash
cd /Users/tomschlegel/ABDB/V3.0
python scripts/reindex_metadata.py --verify
```

**Output:**
```
Actual count (from Parquet files): 648,609
Metadata count (from metadata.parquet): 648,609
✅ Counts match - metadata is accurate
```

**Option 2: Force Reindex**
```bash
python scripts/reindex_metadata.py --reindex
```

**What it does:**
1. Scans all `.parquet` files in `data/parquet/`
2. Reads each file's built-in metadata (fast - just headers)
3. Collects: filename, rows, subject, isotype
4. Creates new `metadata.parquet` table
5. Verifies counts match

**Time:** ~1 second per 100 files (very fast!)

---

## 🔍 What Metadata Contains

### Built-in Parquet Metadata (Automatic)

Every `.parquet` file has:

```
File: ERR1760498_Heavy_IGHM.csv.parquet

Header Metadata:
├── Schema
│   ├── v_call: string
│   ├── d_call: string
│   ├── j_call: string
│   ├── junction_aa: string
│   └── junction_aa_length: int64
│
├── Row Count: 461,489
│
├── Column Statistics (per column)
│   ├── v_call:
│   │   ├── null_count: 0
│   │   ├── min_value: "IGHV1-2*01"
│   │   └── max_value: "IGHV7-4-1*02"
│   ├── junction_aa_length:
│   │   ├── min: 5
│   │   └── max: 50
│   └── ...
│
└── Row Groups (data chunks)
    ├── Chunk 1: rows 0-10000 (with stats)
    ├── Chunk 2: rows 10001-20000 (with stats)
    └── ...
```

**DuckDB uses this for:**
- Fast counting (reads row_count, not data)
- Skipping files (checks min/max values)
- Skipping chunks (checks row group stats)

---

### metadata.parquet Table (Custom)

**Structure:**
```sql
filename                              | subject | rows    | isotype | file_size_mb
ERR1760498_Heavy_IGHM.csv.parquet    | H1      | 461,489 | IGHM    | 4.7
ERR2843386_Heavy_IGHM.csv.parquet    | C9      | 49,659  | IGHM    | 0.4
ERR2843388_Heavy_IGHM.csv.parquet    | C8      | 26,451  | IGHM    | 0.2
...
```

**Used for:**
- Subject aggregation statistics
- Display database size
- Show breakdown by isotype
- Track which files are in database

---

## 💡 Key Concepts

### The Total Sequence Count

**Two ways to count:**

#### Method 1: DuckDB Query (What We Use)
```python
# Fast - reads Parquet file metadata only
result = conn.execute("SELECT COUNT(*) FROM antibodies").fetchone()
total = result[0]  # 648,609
```

**How it works:**
- DuckDB reads each `.parquet` file's header
- Gets row count from metadata (not data!)
- Sums them up
- **Time:** Milliseconds

#### Method 2: metadata.parquet Table (Redundant Check)
```python
# Also fast - reads our summary table
df = pd.read_parquet('data/parquet/metadata.parquet')
total = df['rows'].sum()  # 648,609
```

**How it works:**
- Reads our pre-computed summary
- Sums the 'rows' column
- **Time:** Milliseconds

---

## 🛠️ Practical Scenarios

### Scenario 1: You Delete a File

```bash
# Accidentally delete a file
rm data/parquet/IGHM/ERR2843386_Heavy_IGHM.csv.parquet
```

**What happens:**
- ❌ `metadata.parquet` still lists deleted file
- ❌ Counts won't match
- ⚠️  Searches might show warnings

**Fix:**
```bash
# Reindex to update metadata.parquet
python scripts/reindex_metadata.py --reindex
```

**Result:**
- ✅ metadata.parquet updated
- ✅ Total count corrected
- ✅ Searches work normally

---

### Scenario 2: You Add New Files

**Manual addition:**
```bash
# Convert new file manually
python scripts/convert_to_parquet.py --input new_file.csv.gz

# This creates the .parquet file BUT overwrites metadata.parquet
# So it's actually fine!
```

**Better approach:**
```bash
# Convert new file
python scripts/convert_to_parquet.py --input new_file.csv.gz

# Reindex to ensure metadata is complete
python scripts/reindex_metadata.py --reindex
```

---

### Scenario 3: Verify Data Integrity

**Check if everything is correct:**
```bash
python scripts/reindex_metadata.py --verify
```

**Output if OK:**
```
✅ Counts match - metadata is accurate
```

**Output if problem:**
```
⚠️  Counts don't match! Difference: 461,489
Run with --reindex to fix
```

---

## 🎯 Best Practices

### During Normal Operation
- ✅ **Don't touch** Parquet files manually
- ✅ **Don't edit** metadata.parquet manually
- ✅ Use conversion script for updates

### After File Operations
- ✅ **Always reindex** after deleting files
- ✅ **Verify counts** periodically
- ✅ Run `--verify` before important searches

### Database Maintenance
```bash
# Weekly check (good practice)
cd /server/ABDB/V3.0
python scripts/reindex_metadata.py --verify

# If any issues found
python scripts/reindex_metadata.py --reindex
```

---

## 🚀 Performance Notes

### Reindexing is Fast!

**Why?**
- Only reads Parquet file **headers** (not data)
- Each file: ~1-10ms to read metadata
- 1000 files: ~10 seconds total

**Not reading:**
- ❌ Sequence data
- ❌ All the columns
- ❌ Decompressing everything

**Just reading:**
- ✅ File headers (KB, not GB)
- ✅ Row counts
- ✅ Schema info

---

## 📋 Reindexing Commands Reference

### Basic Commands
```bash
# Verify metadata is correct
python scripts/reindex_metadata.py --verify

# Force reindex
python scripts/reindex_metadata.py --reindex

# Specify custom data directory
python scripts/reindex_metadata.py --data-dir /path/to/parquet --reindex
```

### Expected Output
```
Files indexed: 10
Total sequences: 648,609
Total size: 6.5 MB
Metadata file: data/parquet/metadata.parquet

Sequences by subject:
  H1: 461,489
  C9: 49,659
  C8: 26,451
  ...

✅ Counts match - metadata is accurate
```

---

## ❓ Common Questions

### Q: Do I need to reindex after every search?
**A:** No! Metadata is only updated when files change (add/delete).

### Q: Will searches work without metadata.parquet?
**A:** Yes! DuckDB can count from Parquet files directly. metadata.parquet is for **enhanced statistics** (subject totals, percentages).

### Q: What if I delete metadata.parquet?
**A:** Searches still work, but subject statistics might be incomplete. Just run:
```bash
python scripts/reindex_metadata.py --reindex
```

### Q: Is reindexing safe to run anytime?
**A:** Yes! It only reads files, doesn't modify them. Safe to run as often as needed.

### Q: Can I run reindex while users are searching?
**A:** Yes! It briefly writes new metadata.parquet, but DuckDB handles this gracefully.

---

## 🔧 Troubleshooting

### "Counts don't match"
```bash
# Reindex will fix this
python scripts/reindex_metadata.py --reindex
```

### "metadata.parquet missing"
```bash
# Recreate it
python scripts/reindex_metadata.py --reindex
```

### "Wrong total shown in app"
```bash
# Reindex and restart Streamlit
python scripts/reindex_metadata.py --reindex
# Restart: streamlit run app.py
```

---

## 📝 Summary

### Key Points

✅ **Two metadata types:**
   - Parquet built-in (automatic, immutable)
   - metadata.parquet table (custom, updatable)

✅ **Reindexing is fast:**
   - Reads headers only
   - ~1 second per 100 files

✅ **Safe to run anytime:**
   - Only reads files
   - Recreates summary table
   - Doesn't modify data

✅ **When to reindex:**
   - After deleting files
   - After adding files
   - When counts seem wrong
   - Periodic verification

### Commands to Remember

```bash
# Check if metadata is correct
python scripts/reindex_metadata.py --verify

# Fix metadata if needed
python scripts/reindex_metadata.py --reindex
```

**That's it!** Metadata management is simple and fast. 🚀

---

**Last Updated:** October 1, 2024  
**Author:** Tom U. Schlegel

