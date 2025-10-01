# Data Workflow & Management

**Purpose:** This document explains how data flows through the ABDB V3.0 system and when/where conversion happens.

---

## 📊 Data Flow Overview

```
OAS Database (opig.stats.ox.ac.uk)
         ↓
   CSV.gz files (download)
         ↓
   Backend Conversion (one-time)
         ↓
   Parquet files (V3.0/data/parquet/)
         ↓
   DuckDB Search Engine
         ↓
   Web Interface (users)
```

---

## 🔄 Two Deployment Scenarios

### Scenario 1: Server Deployment (Production)

**Who converts:** Backend/Server (automated)  
**When:** New OAS files released or initial setup  
**Where:** Server's V3.0 directory

```bash
# On server (automated or cron job)
cd /server/path/ABDB/V3.0

# New OAS file detected
# → Automatically convert to Parquet
python scripts/convert_to_parquet.py \
  --input /path/to/new/OAS/files \
  --output data/parquet/

# Users access pre-converted data via web interface
# → Fast searches (no conversion needed)
```

**User Experience:**
- ✅ Opens website
- ✅ Instant searches (data already in Parquet)
- ✅ No setup needed
- ✅ Always up-to-date

---

### Scenario 2: Local Deployment (Self-Hosted)

**Who converts:** User (one-time setup)  
**When:** Initial database setup  
**Where:** User's local V3.0 directory

```bash
# User downloads OAS database files
# User's terminal:
cd ~/ABDB/V3.0

# Step 1: Download OAS files (user's responsibility)
# From: https://opig.stats.ox.ac.uk/webapps/oas/

# Step 2: Convert to Parquet (one-time)
python scripts/convert_to_parquet.py \
  --input ~/Downloads/OAS_files/ \
  --output data/parquet/

# Step 3: Run local web interface
streamlit run app.py
```

**User Experience:**
- ⏳ Initial setup: ~30-60 min (conversion)
- ✅ After setup: Fast searches
- ✅ Self-contained local copy
- 🔄 Manual updates when needed

---

## 🎯 Conversion Strategy

### Backend Conversion (Not User-Facing)

**Purpose:** Pre-process data for optimal search performance

**Why Backend?**
1. **One-time cost** - Conversion happens once, benefits all searches
2. **Server resources** - Use server CPU/RAM for heavy processing
3. **User experience** - Users get instant access to optimized data
4. **Consistency** - All users search same optimized format

**When to Convert:**
- ✅ Initial database setup
- ✅ New OAS files released
- ✅ Database updates
- ✅ Scheduled maintenance

**Not During:**
- ❌ User searches (already converted)
- ❌ Web interface usage (reads Parquet directly)
- ❌ Real-time queries (no conversion needed)

---

## 🔧 Backend Automation (Server)

### Option 1: Manual Conversion (Current)

```bash
# Server admin runs when new OAS data arrives
cd /server/ABDB/V3.0
python scripts/convert_to_parquet.py --input /path/to/new/files
```

### Option 2: Automated Cron Job (Future)

```bash
# /etc/cron.weekly/update-oas-database.sh
#!/bin/bash
cd /server/ABDB/V3.0

# Check OAS for new files
# Download new files
# Convert to Parquet
python scripts/convert_to_parquet.py --input /downloads/OAS/ 

# Restart web service if needed
systemctl restart abdb-streamlit
```

### Option 3: Triggered Pipeline (Advanced)

```yaml
# GitHub Actions, Jenkins, or similar
name: Update OAS Database
on:
  schedule:
    - cron: '0 0 * * 0'  # Weekly
  workflow_dispatch:     # Manual trigger

jobs:
  update-database:
    runs-on: server
    steps:
      - name: Check for new OAS files
      - name: Download new files
      - name: Convert to Parquet
      - name: Deploy updated database
      - name: Notify admin
```

---

## 📥 Data Sources

### Primary Source: OAS Database
- **URL:** https://opig.stats.ox.ac.uk/webapps/oas/
- **Format:** CSV.gz files
- **Size:** Individual files range from KB to GB
- **Total:** 1077+ files (and growing)
- **Update frequency:** Irregular (when new studies published)

### Current Test Data
- **Files:** 10 sample files
- **Sequences:** 648,609
- **Size:** 323 MB (CSV.gz) → 6.5 MB (Parquet)
- **Compression:** 49.6x

### Full Database (When Converted)
- **Files:** 1077+ files
- **Sequences:** ~1 billion
- **Size:** ~100 GB (CSV.gz) → ~50 GB (Parquet)
- **Estimated conversion time:** 30-60 minutes

---

## 🔄 Update Workflow

### When New OAS Data is Released

**Server Deployment:**
```
1. OAS releases new study
2. Server admin notified (email/alert)
3. Download new CSV.gz files
4. Run conversion script
5. New data available instantly
6. Users see updated data on next search
```

**Local Deployment:**
```
1. User checks OAS website
2. Downloads new files manually
3. Runs conversion script
4. Restarts local instance
5. New data available
```

---

## 💾 Storage Considerations

### Server Storage
```
/server/ABDB/V3.0/
├── data/parquet/          # ~50 GB (full database)
│   ├── IGHM/              # ~35 GB
│   ├── IGHG/              # ~10 GB
│   ├── IGHA/              # ~3 GB
│   └── ...
└── backups/               # Optional: Keep CSV.gz originals
```

**Recommendations:**
- Keep original CSV.gz files (backup)
- Parquet files are the "working" database
- Plan for 150 GB total (data + backups + overhead)

### Local Storage
```
User can choose:
- Full database: ~50 GB Parquet
- Subset: Custom selection
- Sample: 10 files (~7 MB)
```

---

## 🚀 Performance Benefits

### Why Pre-Convert (Backend)?

| Aspect | CSV.gz (Runtime) | Parquet (Pre-converted) |
|--------|------------------|-------------------------|
| **Search Time** | Hours | Seconds |
| **Memory Usage** | 10-50 GB | <500 MB |
| **I/O Operations** | Decompress each search | Direct read |
| **CPU Load** | High (decompression) | Low (optimized) |
| **User Experience** | ⏳ Wait hours | ✅ Instant results |

**Conversion Cost:**
- **Time:** 30-60 min (one-time)
- **Resources:** Server CPU/RAM during conversion
- **Benefit:** 180,000x faster searches forever

**ROI:** After just 2-3 searches, conversion pays for itself!

---

## 📋 Conversion Checklist

### Server Setup (One-Time)
- [ ] Download OAS database files
- [ ] Run conversion script
- [ ] Verify Parquet files created
- [ ] Test search functionality
- [ ] Setup update automation (optional)
- [ ] Configure backups

### Regular Updates
- [ ] Monitor OAS for new releases
- [ ] Download new files
- [ ] Run incremental conversion
- [ ] Verify data integrity
- [ ] Update metadata
- [ ] Test searches

### Local Setup (User)
- [ ] Download OAS files
- [ ] Install V3.0 dependencies
- [ ] Run conversion script
- [ ] Verify conversion success
- [ ] Launch Streamlit app
- [ ] Test searches

---

## 🔍 Monitoring & Maintenance

### What to Monitor (Server)
1. **OAS website** - New data releases
2. **Disk space** - Ensure room for growth
3. **Conversion logs** - Check for errors
4. **Search performance** - Ensure speed maintained

### Maintenance Tasks
- **Weekly:** Check for OAS updates
- **Monthly:** Verify data integrity
- **Quarterly:** Clean old backups
- **Yearly:** Full database refresh

---

## 🛠️ Troubleshooting

### "New OAS file won't convert"
```bash
# Check file format
gzcat newfile.csv.gz | head -5

# Test conversion on single file
python scripts/convert_to_parquet.py --input newfile.csv.gz --limit 1

# Check logs
cat conversion.log
```

### "Conversion takes too long"
- Normal for full database (30-60 min)
- Can be done in background
- Use `nohup` or run in tmux/screen session

### "Users seeing old data"
- Check Parquet files timestamp
- Verify new files in data/parquet/
- Restart Streamlit if caching old data

---

## 📝 Summary

### Key Points

✅ **Conversion is backend/one-time** - Not done during user searches  
✅ **Users query Parquet** - Pre-optimized data  
✅ **Server handles updates** - Users get instant access  
✅ **Local users convert once** - Then use optimized data  

### User Flow

**Server Users:**
```
Open website → Search immediately (data pre-converted)
```

**Local Users:**
```
Download OAS → Convert (30-60 min) → Search forever (instant)
```

---

## 🎯 Future Enhancements

### Planned Improvements
1. **Auto-update system** - Detect and convert new OAS files
2. **Incremental updates** - Only convert new files
3. **Download manager** - Built-in OAS file downloader
4. **Delta updates** - Download only changed files
5. **Conversion API** - Trigger conversions remotely

### Advanced Features
- CDN for Parquet files (fast distribution)
- Pre-converted database hosting (skip user conversion)
- Streaming conversion (process while downloading)
- Parallel conversion (faster for large datasets)

---

**Document Version:** 1.0  
**Last Updated:** October 1, 2024  
**Author:** Tom U. Schlegel

