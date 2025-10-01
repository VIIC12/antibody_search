# When to Reindex - The Truth About metadata.parquet

## 🔍 **The Real Story**

After testing, here's what actually happens:

### **Total Sequence Count**
✅ **Automatically updates** - No reindex needed!

**How:**
- DuckDB uses wildcard: `read_parquet('data/parquet/*/*.parquet')`
- Scans directory for ALL .parquet files
- Reads built-in file metadata (row counts)
- Sums them up
- **New files automatically included!**
- **Deleted files automatically excluded!**

### **What metadata.parquet Actually Does**
⚠️ Only used for **per-subject statistics**

**Specifically:**
- Per-subject percentage calculations
- "Hits per million" rates by subject
- Subject-level breakdowns in search results

**NOT used for:**
- ❌ Total sequence count
- ❌ Finding files
- ❌ Basic searches

---

## 🔄 **When You Need to Reindex**

### ✅ **You DON'T Need to Reindex For:**

**1. Just viewing total count**
```bash
# Add/remove Parquet files
# Click "🔄 Reload Database" button
# → Count updates automatically!
```

**2. Basic searches**
```bash
# Search for genes
# DuckDB reads files directly
# → Works fine without reindex
```

**3. Adding Parquet files manually**
```bash
# Copy file to data/parquet/IGHM/
# Click "🔄 Reload Database"
# → File is found and counted!
```

---

### ⚠️ **You DO Need to Reindex For:**

**1. Accurate per-subject percentages**
```python
# In search results, when you see:
Subject    Hits    Total    Percentage
H1         1000    10000    10.0%      ← This uses metadata.parquet!
```

Without reindex, percentages might be wrong or show as 0%.

**2. New files (from conversion)**
```bash
# When converting CSV.gz → Parquet
python scripts/convert_to_parquet.py --input new_file.csv.gz
# → This automatically updates metadata.parquet ✓
# → No manual reindex needed ✓
```

**3. Manually added Parquet files**
```bash
# If you copy Parquet files manually (not via conversion script)
cp external_file.parquet data/parquet/IGHM/
python scripts/reindex_metadata.py --reindex  # Need this!
# → Updates subject statistics
```

**4. Database verification**
```bash
# Health check
python scripts/reindex_metadata.py --verify
# → Ensures metadata.parquet matches actual files
```

---

## 🎯 **Simplified Workflows**

### **Workflow 1: Convert New OAS Files (Normal)**
```bash
# Convert (this updates metadata.parquet automatically)
python scripts/convert_to_parquet.py --input new_oas_file.csv.gz

# Reload in browser
Click "🔄 Reload Database" button

# ✅ Done! Everything updates correctly.
```

**Reindex needed?** ❌ No! Conversion script handles it.

---

### **Workflow 2: Manually Add Parquet File**
```bash
# Copy pre-converted Parquet file
cp some_file.parquet data/parquet/IGHM/

# Reindex (update subject statistics)
python scripts/reindex_metadata.py --reindex

# Reload in browser
Click "🔄 Reload Database" button

# ✅ Done! Counts and percentages correct.
```

**Reindex needed?** ✅ Yes! (for subject statistics)

---

### **Workflow 3: Delete Files**
```bash
# Delete Parquet file
rm data/parquet/IGHM/old_file.parquet

# Option A: Just reload (if you don't care about subject stats)
Click "🔄 Reload Database" button
# → Total count updates ✓
# → Subject percentages might be wrong ✗

# Option B: Reindex first (recommended)
python scripts/reindex_metadata.py --reindex
Click "🔄 Reload Database" button
# → Total count updates ✓
# → Subject percentages correct ✓
```

**Reindex needed?** ⚠️ Optional (recommended for accuracy)

---

## 📊 **What Gets Updated When**

| Action | Total Count | Subject Stats | Reindex Needed? |
|--------|-------------|---------------|-----------------|
| Convert CSV.gz | ✅ Auto | ✅ Auto | ❌ No |
| Add Parquet manually | ✅ Auto | ❌ Stale | ✅ Yes |
| Delete Parquet | ✅ Auto | ❌ Stale | ✅ Yes (optional) |
| Just viewing | ✅ Current | ✅ Current | ❌ No |

---

## 💡 **Key Insights**

### **DuckDB is Smart!**
- Uses wildcard patterns to find files
- Auto-detects new/deleted files
- Reads metadata from file headers
- No manual indexing needed for basic operations

### **metadata.parquet is Optional!**
- Enhances subject statistics
- Not required for basic functionality
- Nice to have, not essential
- Conversion script maintains it automatically

### **Reindex Script is:**
- 🔧 **Maintenance tool** - For health checks
- 🔧 **Fix tool** - When metadata gets out of sync
- 🔧 **Verification tool** - Ensure data integrity
- ❌ **Not required** - For normal operations with conversion script

---

## 🎯 **Recommendation**

### **For Normal Operations:**
```bash
# Convert new files
python scripts/convert_to_parquet.py --input new_files/
# → metadata.parquet updated automatically

# Reload in browser
Click "🔄 Reload Database"
# → Everything works perfectly
```

**Skip reindex!** The conversion script handles everything.

---

### **For Manual File Operations:**
```bash
# If you manually move/copy Parquet files
python scripts/reindex_metadata.py --reindex
# → Keeps subject statistics accurate

# Then reload
Click "🔄 Reload Database"
```

**Use reindex** to keep statistics accurate.

---

### **For Verification:**
```bash
# Periodic health check (weekly/monthly)
python scripts/reindex_metadata.py --verify
# → Ensures everything is in sync
```

**Good practice** for database maintenance.

---

## 📝 **Updated Best Practices**

### **Do This (Most Common):**
```bash
python scripts/convert_to_parquet.py --input ../Server/DB
# ↓ Automatically updates everything
# ↓ Just click reload button
```

### **Sometimes Do This (Manual Operations):**
```bash
# Only if you manually added/removed Parquet files
python scripts/reindex_metadata.py --reindex
```

### **Rarely Do This (Troubleshooting):**
```bash
# Only if subject statistics seem wrong
python scripts/reindex_metadata.py --verify  # Check
python scripts/reindex_metadata.py --reindex # Fix
```

---

## ✅ **Conclusion**

**Keep the reindex script?** ✅ **YES!**

**Why:**
- Useful for manual file operations
- Good for verification
- Maintains subject statistics accuracy
- Helpful for troubleshooting

**But:**
- Not needed for daily operations
- Conversion script handles 90% of cases
- More of a maintenance/admin tool

**Updated understanding:**
- DuckDB is smarter than we thought
- Total counts auto-update
- metadata.parquet is for enhanced statistics
- Reindex is optional but useful

---

**I'll now update all the main documentation to reflect this accurate understanding.**

