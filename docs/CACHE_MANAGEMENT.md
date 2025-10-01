# Cache Management in ABDB V3.0

## 🔄 Understanding Streamlit Caching

### The Issue

Streamlit caches the search engine to avoid reloading on every page interaction:

```python
@st.cache_resource
def init_search_engine():
    engine = AntibodySearchEngine(data_dir="data/parquet")
    return engine  # This gets cached!
```

**Problem:**
- You delete/add Parquet files
- Run `reindex_metadata.py` 
- Metadata updates correctly
- **But Streamlit still shows old count** (cached engine!)

---

## ✅ Solution: Reload Database Button

Use the **"🔄 Reload Database"** button in the sidebar.

**How to use:**

1. Delete/add Parquet files
2. Run: `python scripts/reindex_metadata.py --reindex`
3. Go to Streamlit app in browser
4. **Click "🔄 Reload Database"** button in sidebar
5. ✅ Updated count appears!

**Note:** Simple browser refresh (F5) won't work - you need to click the reload button or restart Streamlit.

---

## 🛠️ Complete Workflow

### When You Delete Files

```bash
# 1. Delete file(s)
rm data/parquet/IGHM/some_file.parquet

# 2. Reload in browser
#    Click "🔄 Reload Database" button
#    → Total count updates automatically! ✓

# 3. Optional: Reindex for accurate subject statistics
python scripts/reindex_metadata.py --reindex
#    → Subject percentages updated ✓
```

**Note:** DuckDB automatically detects file changes, so total count updates without reindexing!

### When You Add Files

```bash
# 1. Convert new file (this updates metadata.parquet automatically)
python scripts/convert_to_parquet.py --input new_file.csv.gz

# 2. Reload in browser
#    Click "🔄 Reload Database" button
#    → Everything updates automatically! ✓

# No manual reindex needed! Conversion script handles it.
```

**Note:** If you manually copy a Parquet file (not using conversion script), then run reindex.

---

## 🔍 How the Reload Button Works

**When you click "🔄 Reload Database":**

```python
if st.button("🔄 Reload Database"):
    st.cache_resource.clear()  # Clear cache
    st.rerun()                 # Restart app
```

1. Clears Streamlit's resource cache
2. Restarts the application
3. Re-initializes search engine
4. Re-reads Parquet files
5. Shows updated count

**Note:** Simple browser refresh (F5) won't clear `@st.cache_resource` - you need the button or restart Streamlit.

---

## 💡 Why Caching Exists

### Without Caching (Bad)
```
User opens page → Load database (slow!)
User changes input → Reload database (slow!)
User clicks search → Reload database (slow!)
```
❌ Every interaction reloads everything

### With Caching (Good)
```
User opens page → Load database once → Cache it
User changes input → Use cached database (instant!)
User clicks search → Use cached database (instant!)
```
✅ Load once, use many times

### Trade-off
- ✅ Fast page interactions
- ⚠️  Need manual reload when data changes
- ✅ We added the reload button to fix this!

---

## 🎯 Automatic Reload Options

### Option 1: Monitor File Changes (Advanced)

You could modify the app to auto-detect file changes:

```python
import os
from pathlib import Path

@st.cache_resource
def init_search_engine():
    # Get modification time of data directory
    data_dir = Path("data/parquet")
    mod_time = max(f.stat().st_mtime for f in data_dir.rglob("*.parquet"))
    
    # If mod_time changed, cache is invalidated automatically
    engine = AntibodySearchEngine(data_dir=str(data_dir))
    return engine, mod_time
```

**Benefit:** Auto-reloads when files change  
**Drawback:** Checks filesystem on every page load (slight overhead)

---

### Option 2: Time-based Cache (Simple)

```python
from datetime import datetime, timedelta

@st.cache_resource(ttl=timedelta(hours=1))
def init_search_engine():
    # Cache expires after 1 hour
    engine = AntibodySearchEngine()
    return engine
```

**Benefit:** Auto-refreshes periodically  
**Drawback:** Might show stale data for up to 1 hour

---

### Option 3: Manual Button (Current - Best for Your Use Case)

**Why this is best:**
- ✅ Database rarely changes (admin task)
- ✅ Users don't need auto-reload
- ✅ Admin clicks reload after updates
- ✅ No performance overhead
- ✅ Simple and explicit

---

## 📋 Complete Update Workflow (Server Admin)

### Scenario: New OAS Files Released

**Step-by-step:**

```bash
# 1. SSH to server
ssh user@your-server.com
cd /server/ABDB/V3.0

# 2. Download new OAS files
# (manual or automated script)

# 3. Convert to Parquet
python scripts/convert_to_parquet.py --input /downloads/new_oas_files/
# → Creates new .parquet files
# → Updates metadata.parquet automatically

# 4. Verify metadata
python scripts/reindex_metadata.py --verify
# → Checks everything is correct

# 5. In browser (if Streamlit already running):
#    Click "🔄 Reload Database" button
#    → Users see new data immediately

# OR restart Streamlit (also clears cache)
# systemctl restart abdb-streamlit
```

---

## 🔧 Troubleshooting

### "I reindexed but count still wrong in Streamlit"

**Solution:**
1. Check you clicked **"🔄 Reload Database"** button
2. If button doesn't work, restart Streamlit:
   ```bash
   # Stop Streamlit (Ctrl+C in terminal)
   # Restart
   streamlit run app.py
   ```

### "Reload button clicked but nothing changed"

**Possible causes:**
1. Metadata not actually reindexed - run:
   ```bash
   python scripts/reindex_metadata.py --verify
   ```
2. Browser cache - try hard refresh (Cmd+Shift+R)
3. Streamlit session issue - restart Streamlit

### "Count shows 0 after reload"

**Likely issue:** No Parquet files found

**Check:**
```bash
ls -la data/parquet/IGHM/
# Should show .parquet files

# If empty, reconvert
python scripts/convert_to_parquet.py --input ../Server/DB --limit 10
```

---

## 🎯 Best Practices

### For Server Admins

**After any file operations:**
```bash
# Always run these two commands:
python scripts/reindex_metadata.py --reindex  # Fix metadata
# Then click reload button in web interface
```

**Before important changes:**
```bash
# Verify everything is correct first
python scripts/reindex_metadata.py --verify
```

**Automated updates:**
```bash
# In your update script, add:
python scripts/convert_to_parquet.py --input /new/files/
python scripts/reindex_metadata.py --reindex
# Note: Users need to click reload or restart browser
```

---

### For Users

**If counts seem wrong:**
1. Ask admin to reindex
2. Click "🔄 Reload Database" in sidebar
3. Refresh browser if needed

**Normal usage:**
- No need to worry about caching
- Reload button only needed after database updates

---

## 📝 Summary

### The Problem
- ✅ Streamlit caches search engine for performance
- ❌ Cache doesn't auto-update when files change
- ❌ Shows old sequence counts

### The Solution
- ✅ Added "🔄 Reload Database" button in sidebar
- ✅ Clears cache and reloads engine
- ✅ Shows current counts immediately

### The Workflow
```
1. Delete/add Parquet files
2. Run: reindex_metadata.py --reindex
3. Click: "🔄 Reload Database" button
4. ✅ Updated count appears!
```

### Alternative (If Button Doesn't Work)
```bash
# Just restart Streamlit
# Ctrl+C (stop)
streamlit run app.py  # (restart)
```

---

**Quick Fix:** I added the reload button to the sidebar. Try it now! 🔄

