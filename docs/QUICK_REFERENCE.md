# ABDB V3.0 - Quick Reference Card

## 🚀 Common Commands

### Launch Application
```bash
cd /Users/tomschlegel/ABDB/V3.0
source venv/bin/activate
streamlit run app.py
```
Opens at: http://localhost:8501

---

## 🔧 Database Management

### Convert New Files
```bash
# Convert specific files
python scripts/convert_to_parquet.py --input /path/to/new_files.csv.gz

# Convert directory with limit
python scripts/convert_to_parquet.py --input ../Server/DB --limit 10

# Convert full database
python scripts/convert_to_parquet.py --input ../Server/DB
```

### After Adding/Removing Files

**If you used conversion script:**
```bash
python scripts/convert_to_parquet.py --input new_file.csv.gz
# → Click "🔄 Reload Database" button (done!)
```

**If you manually copied/deleted Parquet files:**
```bash
# 1. Reindex (for subject statistics)
python scripts/reindex_metadata.py --reindex

# 2. Click "🔄 Reload Database" button
```

**Note:** Total count updates automatically, but subject percentages need reindex.

### Verify Data Integrity
```bash
python scripts/reindex_metadata.py --verify
```

---

## 🔄 Updating Sequence Counts

### Problem: Count Not Updating in Streamlit

**Cause:** Streamlit caches the database with `@st.cache_resource`

**Solution:**
```bash
# Step 1: Reindex (terminal)
python scripts/reindex_metadata.py --reindex

# Step 2: Reload (browser)
Click "🔄 Reload Database" button in sidebar

# Alternative: Restart Streamlit
Ctrl+C (stop), then: streamlit run app.py
```

---

## 🔍 Example Searches

### Simple Gene Search
```
IGHV: 3-23
IGHD: (empty)
IGHJ: (empty)
→ Returns all sequences with IGHV3-23
```

### Multiple Genes
```
IGHV: 3-20|3-22
IGHD: 2-15|2-18
IGHJ: 4|5
→ Returns combinations of these genes
```

### Specific CDRH3 Length
```
IGHV: 3-
CDRH3 Length: 15
→ Returns IGHV3-* with CDRH3 length = 15
```

### With Motif Pattern
```
IGHV: 3-
CDRH3 Motif: YY.D.*G
→ Returns IGHV3-* matching motif pattern
```

### Full Sequences
```
IGHV: 3-23
☑️ Return Full Sequences (checked)
Max Results: 1000
→ Downloads actual sequence data
```

---

## 📊 Understanding Results

### Statistics Mode (Default)
- Fast (< 1 second)
- Shows hits per subject
- Includes percentages
- Downloadable as CSV

### Full Results Mode
- Slower (seconds to minutes)
- Complete sequence data
- All columns included
- Use "Max Results" to limit

---

## 🐛 Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| "No Parquet files found" | Run conversion script first |
| "Count not updating" | Click "🔄 Reload Database" button |
| "Out of memory" | Use statistics mode or reduce max results |
| "Slow searches" | First search is slower (warmup) |
| "ModuleNotFoundError" | `source venv/bin/activate` |

---

## 📁 Key Files & Locations

```
V3.0/
├── app.py                          # Main app
├── data/parquet/                   # Your data
│   ├── IGHM/*.parquet             # Sequence files
│   └── metadata.parquet           # Summary table
├── scripts/
│   ├── convert_to_parquet.py      # Data converter
│   └── reindex_metadata.py        # Metadata fixer
└── docs/                          # Documentation
```

---

## ⚡ Performance Tips

### For Faster Searches
1. Use statistics mode (don't check "Full Sequences")
2. Be specific with gene criteria
3. Avoid very broad searches without filters
4. Use exact matches when possible

### For Large Results
1. Set reasonable "Max Results" limit
2. Use CSV export for big datasets
3. Consider multiple smaller searches

---

## 🔄 Daily Operations

### Server Admin Workflow
```bash
# Morning: Check for OAS updates
# If new files available:

1. Download new files
2. python scripts/convert_to_parquet.py --input /new/files/
3. python scripts/reindex_metadata.py --verify
4. Notify users to click reload button
```

### User Workflow
```bash
# Just use the web interface!
# If admin notifies of update:
1. Click "🔄 Reload Database" button
2. Continue searching with new data
```

---

## 📞 Need Help?

- **Quick issues**: See troubleshooting table above
- **Detailed guide**: `docs/GETTING_STARTED.md`
- **Cache issues**: `docs/CACHE_MANAGEMENT.md`
- **Metadata issues**: `docs/METADATA_MANAGEMENT.md`
- **Contact**: tom.schlegel@uni-leipzig.de

---

## 🎯 Most Common Tasks

### 1. Launch App
```bash
streamlit run app.py
```

### 2. Add New Data
```bash
python scripts/convert_to_parquet.py --input /new/data/
python scripts/reindex_metadata.py --reindex
# Click reload button in app
```

### 3. Verify Database
```bash
python scripts/reindex_metadata.py --verify
```

### 4. Fix Metadata
```bash
python scripts/reindex_metadata.py --reindex
```

---

**Remember:** After any data changes → Reindex → Click Reload! 🔄

