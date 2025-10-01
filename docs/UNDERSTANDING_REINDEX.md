# Understanding Reindex - What It Really Does

## 🎯 **TL;DR - Do I Need Reindex?**

### **Short Answer:**
**Usually NO!** The conversion script and reload button handle 90% of cases.

### **Quick Decision Tree:**

```
Did you use convert_to_parquet.py?
├─ YES → Just click "🔄 Reload Database" ✓ (done!)
└─ NO  → Did you manually add/delete Parquet files?
    ├─ YES → Run reindex for subject stats
    └─ NO  → No reindex needed
```

---

## 🔬 **What We Discovered**

### **The Surprise:**
Total sequence count **automatically updates** without reindexing!

### **How This Works:**

**DuckDB's wildcard pattern:**
```python
# In search_engine.py
parquet_pattern = str(self.data_dir / "*/*.parquet")
self.conn.execute(f"SELECT * FROM read_parquet('{parquet_pattern}')")
```

This means:
- 🔍 Scans directory for `*/*.parquet` files
- 🆕 Finds new files automatically
- 🗑️ Ignores deleted files automatically
- 📊 Counts rows from file metadata (built-in)
- ⚡ Updates on every reload

**Result:** Total count is **always current** when you click reload!

---

## 📊 **What metadata.parquet Actually Does**

### **Used For (Lines 169-192 in search_engine.py):**

```python
# Only used during searches for per-subject statistics
metadata_query = """
    SELECT subject, SUM(total_sequences) as total
    FROM read_parquet('metadata.parquet')
    GROUP BY subject
"""
```

**Provides:**
- Per-subject total sequence counts (from OAS data)
- Used to calculate hit percentages
- Used for "per million" statistics

**Example output:**
```
Subject    Hits    Total       Percentage    Per Million
H1         1000    100000      1.0%          10000
C9         500     50000       1.0%          10000
```
↑ The "Total" and "Percentage" columns use metadata.parquet

---

## 🔄 **When Reindex Actually Matters**

### **Scenario 1: You Convert Files (Normal)**
```bash
python scripts/convert_to_parquet.py --input new_file.csv.gz
```

**What happens:**
- ✅ Creates .parquet file
- ✅ Updates metadata.parquet automatically (line 147 in script)
- ✅ Subject statistics accurate

**Reindex needed?** ❌ No!

---

### **Scenario 2: You Manually Copy Parquet File**
```bash
cp external.parquet data/parquet/IGHM/
```

**What happens:**
- ✅ File exists, DuckDB finds it
- ✅ Total count updates (when you reload)
- ❌ metadata.parquet doesn't know about it
- ❌ Subject statistics missing/wrong

**Reindex needed?** ✅ Yes (for subject stats)

---

### **Scenario 3: You Delete Parquet File**
```bash
rm data/parquet/IGHM/old.parquet
```

**What happens:**
- ✅ DuckDB doesn't find it anymore
- ✅ Total count decreases (when you reload)
- ❌ metadata.parquet still lists it
- ❌ Subject totals inflated

**Reindex needed?** ⚠️ Optional (for accurate percentages)

---

## 💡 **Key Insights**

### **Two Counting Systems:**

**1. DuckDB Direct Count (Dynamic)**
- Scans files with wildcard pattern
- Always current
- Used for: Total sequence display
- Updated: Every reload (automatic)

**2. metadata.parquet (Static)**
- Pre-computed subject totals
- Needs manual update
- Used for: Subject percentages
- Updated: By conversion script or reindex

---

## 🎯 **Simplified Best Practices**

### **Normal Operations (90% of time):**
```bash
# Add new data
python scripts/convert_to_parquet.py --input new_data/

# Update in browser
Click "🔄 Reload Database"

# ✅ Done! Everything correct.
```

### **Manual File Operations (10% of time):**
```bash
# If you manually moved/copied Parquet files
python scripts/reindex_metadata.py --reindex

# Then reload
Click "🔄 Reload Database"

# ✅ Subject statistics now accurate
```

### **Periodic Maintenance (monthly):**
```bash
# Health check
python scripts/reindex_metadata.py --verify

# Fix if needed
python scripts/reindex_metadata.py --reindex
```

---

## ✅ **Keep or Remove Reindex Script?**

### **KEEP IT! Here's Why:**

**Essential for:**
1. 📊 Accurate subject statistics (percentages, per-million rates)
2. 🔧 Manual Parquet file operations
3. 🔍 Database verification and health checks
4. 🐛 Troubleshooting data inconsistencies

**Not needed for:**
- ❌ Converting files (script handles it)
- ❌ Total counts (DuckDB handles it)
- ❌ Basic operations (reload button enough)

**Verdict:** It's a **useful maintenance tool**, not a daily requirement.

---

## 📝 **Updated Understanding**

| What | How It Updates | Manual Action Needed? |
|------|----------------|----------------------|
| **Total Count** | DuckDB wildcard scan | ❌ No (auto on reload) |
| **File Detection** | DuckDB directory scan | ❌ No (auto on reload) |
| **Subject Statistics** | metadata.parquet | ✅ Yes (if manual files) |
| **Percentages** | metadata.parquet | ✅ Yes (if manual files) |

---

## 🚀 **Recommended Workflow**

### **For Server Admins:**

**Daily/Weekly (New OAS data):**
```bash
# 1. Download new OAS files
# 2. Convert
python scripts/convert_to_parquet.py --input /downloads/new/

# 3. Done! (metadata.parquet updated automatically)
# Users just click reload button
```

**Monthly (Health Check):**
```bash
python scripts/reindex_metadata.py --verify
# If any issues, fix with --reindex
```

---

### **For Advanced Users:**

**If you're moving files around manually:**
```bash
python scripts/reindex_metadata.py --reindex
```

**Otherwise:**
```bash
# Just use the conversion script - it handles everything!
```

---

## 🎓 **What We Learned**

1. **DuckDB is smarter than expected**
   - Auto-detects new/deleted files
   - Counts directly from file metadata
   - No manual indexing needed

2. **metadata.parquet has a specific purpose**
   - Subject-level statistics
   - Not for total counts
   - Updated by conversion script

3. **Reindex script is a maintenance tool**
   - Useful but not always necessary
   - Essential for manual operations
   - Good for verification

4. **The reload button is powerful**
   - Clears cache
   - Re-scans files
   - Updates everything except subject stats

---

## 📌 **Final Recommendation**

**Keep the reindex script** - It's valuable for:
- Manual file operations
- Database verification
- Maintaining accurate subject statistics
- Troubleshooting

**But know you don't always need it** - Normal workflow is:
```bash
convert → reload → done! ✓
```

---

**Updated:** October 1, 2024  
**Status:** Fully understood and documented!

