# Using Jupyter Notebook with V3.0

## ✅ Setup Complete!

I've registered the V3.0 virtual environment as a Jupyter kernel named **"ABDB V3.0"**.

---

## 🚀 How to Use

### Step 1: Launch Jupyter

```bash
cd /Users/tomschlegel/ABDB/V3.0
jupyter notebook explore_data.ipynb
```

Or use JupyterLab:
```bash
jupyter lab explore_data.ipynb
```

### Step 2: Select the Correct Kernel

When the notebook opens:

1. Click **Kernel** menu → **Change Kernel**
2. Select **"ABDB V3.0"** from the list
3. ✅ You're now using the V3.0 environment!

**Or:**
- Look in top-right corner for kernel name
- Click it to change
- Select "ABDB V3.0"

---

## 📓 What the Notebook Does

`explore_data.ipynb` provides:

1. **List Parquet files** - See what's in your database
2. **Read metadata** - Fast check (no data loading)
3. **Display sequences** - Look at actual data
4. **Test searches** - Verify queries work
5. **Check integrity** - Ensure counts match

---

## 🔧 Kernel Management

### View Available Kernels
```bash
jupyter kernelspec list
```

You should see:
```
abdb-v3    /Users/tomschlegel/Library/Jupyter/kernels/abdb-v3
```

### If You Need to Reinstall
```bash
cd /Users/tomschlegel/ABDB/V3.0
source venv/bin/activate
python -m ipykernel install --user --name=abdb-v3 --display-name="ABDB V3.0"
```

### Remove the Kernel (If Needed)
```bash
jupyter kernelspec uninstall abdb-v3
```

---

## 💡 Tips

### Using the Notebook

1. **Run cells in order** - Each cell depends on previous ones
2. **Check outputs** - Verify data looks correct
3. **Modify queries** - Try different search parameters
4. **Explore data** - Look at different files

### Common Tasks

**Check total sequences:**
```python
engine.total_sequences
```

**List all subjects:**
```python
metadata_df['subject'].unique()
```

**Count by isotype:**
```python
metadata_df.groupby('isotype')['rows'].sum()
```

---

## 🎯 Quick Verification Workflow

```bash
# 1. Launch notebook
jupyter notebook explore_data.ipynb

# 2. Select "ABDB V3.0" kernel

# 3. Run all cells (Cell menu → Run All)

# 4. Check final output:
#    ✅ All counts match - data is consistent!
```

---

## 🆘 Troubleshooting

### "Kernel not found"
```bash
# Reinstall kernel
cd /Users/tomschlegel/ABDB/V3.0
source venv/bin/activate
python -m ipykernel install --user --name=abdb-v3 --display-name="ABDB V3.0"
```

### "ModuleNotFoundError"
- Make sure you selected "ABDB V3.0" kernel (not base/other)
- Check kernel in top-right corner

### "No module named 'duckdb'"
- You're using wrong kernel
- Change to "ABDB V3.0" kernel

---

## 📝 Summary

**What I did:**
1. ✅ Installed Jupyter in V3.0 venv
2. ✅ Registered venv as kernel "ABDB V3.0"
3. ✅ Created explore_data.ipynb notebook

**What you do:**
1. Launch: `jupyter notebook explore_data.ipynb`
2. Select kernel: "ABDB V3.0"
3. Run cells and explore!

**Note:** Jupyter is only for development/testing. It's not in requirements.txt since end users don't need it.

---

**Ready to explore!** 🔬

