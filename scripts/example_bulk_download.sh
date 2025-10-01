#!/bin/bash
# Example usage of bulk_download_and_convert.py

echo "=== Bulk Download and Convert Example ==="
echo

# Example 1: Dry run to see what would be downloaded
echo "1. Dry run (first 5 files):"
python scripts/bulk_download_and_convert.py \
    --input data/unpaired/bulk_download-3.sh \
    --output ./data/parquet \
    --dry-run \
    --max-files 5

echo
echo "2. Download and convert first 10 files:"
python scripts/bulk_download_and_convert.py \
    --input data/unpaired/bulk_download-3.sh \
    --output ./data/parquet \
    --max-files 10

echo
echo "3. Run again to test skip functionality:"
python scripts/bulk_download_and_convert.py \
    --input data/unpaired/bulk_download-3.sh \
    --output ./data/parquet \
    --max-files 10

echo
echo "=== Done ==="
