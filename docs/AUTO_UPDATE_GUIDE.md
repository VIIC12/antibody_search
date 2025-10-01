# Automated OAS Database Updates

## 🔄 **The Update Challenge**

### **The Problem:**

From [OAS unpaired search](https://opig.stats.ox.ac.uk/webapps/oas/oas_unpaired/):
1. You select criteria (Species, BSource, Chain, Isotype, etc.)
2. OAS generates a dynamic download link: `blob:https://opig.stats.ox.ac.uk/...`
3. This link is **temporary** and **session-specific**
4. You can't use it for automated updates

### **The Solution:**

Use your **existing download scripts** (like `Server/full.sh`) as the "source of truth":
- Lists all OAS file URLs
- Compare with your current database
- Download only missing files
- Automated and repeatable

---

## 🚀 **Automated Update System**

I created: `scripts/update_from_oas.py`

### **How It Works:**

```
1. Scan your current database
   ↓ "Which files do I have?"
   
2. Read download script (full.sh)
   ↓ "Which files should I have?"
   
3. Compare the two
   ↓ "Which files am I missing?"
   
4. Download missing files only
   ↓ wget from OAS
   
5. Convert to Parquet
   ↓ Ready for searches!
   
6. Clean up CSV.gz files
   ↓ Save disk space
```

---

## 📋 **Usage**

### **Basic Update (Recommended):**

```bash
cd /Users/tomschlegel/ABDB/V3.0

# Check what's new without downloading
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh \
  --dry-run

# If new files found, download and convert them
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh
```

**What happens:**
```
Found 1077 files in download script
Found 10 existing files in database
📥 Need to download 1067 new files

Downloading files...
[1/1067] ERR2843395_Heavy_IGHM.csv.gz
  ✓ Downloaded (27.0 MB)
[2/1067] ERR2843396_Heavy_IGHM.csv.gz
...

Converting to Parquet...
  ✓ Converted ERR2843395_Heavy_IGHM.csv.gz

✅ Update complete!
New files added: 1067
```

---

### **Test with Limit:**

```bash
# Download only first 10 new files (testing)
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh \
  --max-new-files 10
```

---

### **Keep Original Files:**

```bash
# Keep CSV.gz files after conversion (backup)
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh \
  --keep-downloads
```

---

## 🔄 **Regular Update Workflow**

### **Weekly Manual Check:**

```bash
cd /Users/tomschlegel/ABDB/V3.0

# 1. Check for updates
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh \
  --dry-run

# If new files found:

# 2. Download and convert
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh

# 3. Reload in Streamlit
# Click "🔄 Reload Database" button
```

---

## ⏰ **Automated Updates (Cron Job)**

### **Setup on Server:**

```bash
# Edit crontab
crontab -e

# Add weekly update (every Sunday at 2 AM)
0 2 * * 0 cd /server/ABDB/V3.0 && /server/ABDB/V3.0/venv/bin/python scripts/update_from_oas.py --download-script ../Server/full.sh >> logs/updates.log 2>&1

# Or monthly (first day of month)
0 2 1 * * cd /server/ABDB/V3.0 && /server/ABDB/V3.0/venv/bin/python scripts/update_from_oas.py --download-script ../Server/full.sh >> logs/updates.log 2>&1
```

**What this does:**
- Runs automatically on schedule
- Downloads new files
- Converts to Parquet
- Logs everything
- No manual intervention needed

**Users see:**
- Database grows over time
- No downtime
- Just need to reload to see new data

---

## 📝 **Updating Your Download Script**

### **When OAS Releases New Data:**

**Option 1: Manual Update (Current)**
1. Go to [OAS website](https://opig.stats.ox.ac.uk/webapps/oas/oas_unpaired/)
2. Select your criteria (Species: Human, Chain: Heavy, etc.)
3. Click "Search"
4. Download the `.sh` script
5. Replace `Server/full.sh` with new version
6. Run update script

**Option 2: Append New Files**
```bash
# If you know the new file URL
echo "wget http://opig.stats.ox.ac.uk/.../NEW_FILE.csv.gz" >> ../Server/full.sh

# Then run update
python scripts/update_from_oas.py --download-script ../Server/full.sh
```

---

## 🎯 **Smart Update Strategy**

### **Incremental Downloads:**

The script is smart:
- Only downloads files you don't have
- Skips existing files (saves time and bandwidth)
- Can run repeatedly (idempotent)

**Example:**
```
First run:  0 files → downloads all 1077 files (hours)
Second run: 1077 files → "Database up-to-date!" (instant)
Third run:  New OAS data → downloads only new files (minutes)
```

---

## 🔧 **Advanced Options**

### **Custom Download Directory:**

```bash
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh \
  --download-dir /mnt/storage/oas_downloads/ \
  --parquet-dir data/parquet/
```

### **Parallel Downloads (Future Enhancement):**

```python
# Could add threading for faster downloads
# Download 10 files simultaneously
# Would reduce total time significantly
```

---

## 📊 **Monitoring & Notifications**

### **Email Notification (Optional):**

```bash
#!/bin/bash
# update_with_notification.sh

cd /server/ABDB/V3.0

# Run update
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh \
  > /tmp/update_log.txt 2>&1

# Check if new files were added
if grep -q "New files added:" /tmp/update_log.txt; then
    # Send email notification
    mail -s "ABDB Updated - New Sequences Available" \
         admin@yourdomain.com < /tmp/update_log.txt
fi
```

---

## 🛡️ **Error Handling**

### **What If Download Fails?**

The script continues with other files:
```
[1/10] File1.csv.gz ✓ Downloaded
[2/10] File2.csv.gz ✗ Failed (timeout)
[3/10] File3.csv.gz ✓ Downloaded
...

Result: 8/10 files downloaded successfully
→ Converts the 8 that worked
→ You can retry failed files later
```

### **What If Conversion Fails?**

```
Downloaded: 10 files
Converting File1 ✓
Converting File2 ✗ (corrupted data)
Converting File3 ✓
...

Result: 8/10 converted successfully
→ Log shows which files failed
→ You can investigate and retry
```

---

## 🎯 **Complete Update Workflow**

### **Initial Setup (One-Time):**

```bash
# 1. Get your OAS download script
# Go to OAS website, select criteria, download .sh script

# 2. Save it
cp ~/Downloads/bulk_download.sh Server/full.sh

# 3. Run full update
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh

# This downloads all 1077 files (takes hours)
# But you only do it once!
```

---

### **Regular Updates (Weekly/Monthly):**

```bash
# Option A: Manual check
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh \
  --dry-run
# → Shows if new files available

# If new files found:
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh
# → Downloads and converts only new files

# Option B: Automated (cron)
# Set up cron job (see above)
# → Runs automatically, no manual intervention
```

---

## 📝 **Keeping Download Script Updated**

### **Method 1: Replace Entire Script (Recommended)**

When OAS has major updates:
```bash
# 1. Go to OAS website
# 2. Select same criteria as before
# 3. Download new bulk_download.sh
# 4. Replace old script
cp ~/Downloads/bulk_download.sh ../Server/full.sh

# 5. Run update (downloads only new files)
python scripts/update_from_oas.py --download-script ../Server/full.sh
```

### **Method 2: Append Individual Files**

When you know specific new files:
```bash
# Add new file URL to script
echo "wget http://opig.stats.ox.ac.uk/webapps/ngsdb/.../NEW_FILE.csv.gz" >> ../Server/full.sh

# Run update
python scripts/update_from_oas.py --download-script ../Server/full.sh
```

### **Method 3: API/Scraping (Advanced - Future)**

Could automate checking OAS for new files:
```python
# Scrape OAS website to detect new studies
# Compare with local database
# Generate download URLs automatically
# Fully automated updates
```

---

## 🎯 **Recommended Schedule**

### **For Production Server:**

```
Weekly:   Check for updates (dry-run)
Monthly:  Download new files if available
Yearly:   Full database refresh/verification
```

### **For Development:**

```
As needed: Download sample files for testing
Before deployment: Ensure latest data
```

---

## 💡 **Best Practices**

### **1. Keep Download Scripts**
```
Server/
├── full.sh          # All files (1077+)
├── medium.sh        # Subset (100 files)
├── short.sh         # Test (3 files)
└── archive/
    ├── full_2024-01.sh    # Historical snapshots
    └── full_2024-10.sh
```

### **2. Test Before Full Update**
```bash
# Test with one new file first
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh \
  --max-new-files 1

# If works, download all
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh
```

### **3. Monitor Disk Space**
```bash
# Check before large updates
df -h /path/to/ABDB/V3.0/data/

# Full database: ~50 GB needed
# Downloads: ~100 GB temporarily
# Total: ~150 GB free space recommended
```

---

## 📊 **Example Update Session**

```bash
$ python scripts/update_from_oas.py --download-script ../Server/full.sh --dry-run

Found 10 existing files in database
Found 1077 files in download script
📥 Need to download 1067 new files

DRY RUN - Would download:
  - ERR2843395_Heavy_IGHM.csv.gz
  - ERR2843396_Heavy_IGHM.csv.gz
  ... and 1065 more

$ python scripts/update_from_oas.py --download-script ../Server/full.sh --max-new-files 5

[1/5] ERR2843395_Heavy_IGHM.csv.gz
  ✓ Downloaded (13.6 MB)
[2/5] ERR2843396_Heavy_IGHM.csv.gz
  ✓ Downloaded (17.8 MB)
...

Converting to Parquet...
  ✓ Converted ERR2843395_Heavy_IGHM.csv.gz
  ✓ Converted ERR2843396_Heavy_IGHM.csv.gz
...

✅ Update complete!
New files added: 5
Total files in database: 15
```

---

## 🔐 **Security & Reliability**

### **File Verification:**
- Downloads from official OAS URLs only
- Validates file format (.csv.gz)
- Checks conversion success
- Logs all operations

### **Failure Recovery:**
- Individual file failures don't stop process
- Can retry failed files
- Logs show exactly what failed
- Idempotent (safe to run multiple times)

---

## 📝 **Summary**

### **The Update System:**

✅ **Automated** - Script handles everything  
✅ **Incremental** - Only downloads new files  
✅ **Safe** - Can run repeatedly  
✅ **Logged** - Complete audit trail  
✅ **Flexible** - Manual or cron-based  

### **Your Workflow:**

```bash
# Weekly check
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh \
  --dry-run

# Download if needed
python scripts/update_from_oas.py \
  --download-script ../Server/full.sh

# Users reload browser
# → New data available!
```

---

**No need to manually track what's new - the script figures it out!** 🎯

