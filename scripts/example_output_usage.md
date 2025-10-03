# Convert to Parquet - Output Directory Examples

## New Output Behavior

The `convert_to_parquet.py` script now handles output directories as follows:

### 1. Explicit Output Directory (`--output` specified)

When you specify an output directory, all Parquet files and metadata are placed directly in that directory:

```bash
# Convert files to specific output directory
python scripts/convert_to_parquet.py --input data/csv_files/ --output data/parquet_output/

# Result:
# data/parquet_output/
# ├── file1.csv.parquet
# ├── file2.csv.parquet
# ├── file3.csv.parquet
# └── metadata.parquet
```

### 2. Default Behavior (no `--output` specified)

When no output directory is specified, a `converted/` subdirectory is created in the input directory:

```bash
# Convert files without specifying output
python scripts/convert_to_parquet.py --input data/csv_files/

# Result:
# data/csv_files/
# ├── converted/
# │   ├── file1.csv.parquet
# │   ├── file2.csv.parquet
# │   ├── file3.csv.parquet
# │   └── metadata.parquet
# ├── file1.csv.gz
# ├── file2.csv.gz
# └── file3.csv.gz
```

### 3. Single File Input

When converting a single file, the output directory is created relative to the file's location:

```bash
# Convert single file
python scripts/convert_to_parquet.py --input data/csv_files/single_file.csv.gz

# Result:
# data/csv_files/
# ├── converted/
# │   ├── single_file.csv.parquet
# │   └── metadata.parquet
# └── single_file.csv.gz
```

## Key Changes

1. **Flat Structure**: Parquet files are now placed directly in the output directory (no isotype subdirectories)
2. **Single Metadata File**: `metadata.parquet` is created in the root output directory
3. **Flexible Output**: Can specify any output directory or use the default `converted/` subdirectory
4. **Backward Compatible**: Existing functionality is preserved, just with cleaner output structure

## Benefits

- **Simpler Structure**: All files in one directory, easier to manage
- **Flexible Location**: Can output to any directory you choose
- **Clean Default**: Uses `converted/` subdirectory when no output specified
- **Single Metadata**: One metadata file instead of multiple per isotype
