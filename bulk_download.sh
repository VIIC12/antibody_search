#!/bin/bash

# Bulk download script for antibody sequencing data
# Usage: ./bulk_download.sh [OPTIONS]
# Options:
#   -o, --output-dir DIR    Output directory (default: current directory)
#   -j, --jobs N           Number of parallel jobs (default: 4)
#   -f, --file FILE        URL list file (default: paired-oas.txt)
#   -h, --help             Show this help message

set -euo pipefail

# Default values
OUTPUT_DIR="."
JOBS=4
URL_FILE="paired-oas.txt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Function to show usage
show_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Download antibody sequencing data files in parallel from a URL list file.

OPTIONS:
    -o, --output-dir DIR    Output directory for downloaded files (default: current directory)
    -j, --jobs N           Number of parallel download jobs (default: 4)
    -f, --file FILE        URL list file to read from (default: paired-oas.txt)
    -h, --help             Show this help message

EXAMPLES:
    $0                                    # Download to current directory with 4 parallel jobs
    $0 -o /path/to/data                   # Download to specified directory
    $0 -o /path/to/data -j 8              # Download with 8 parallel jobs
    $0 -f my_urls.txt -o /data -j 16      # Use custom URL file with 16 parallel jobs
    $0 --output-dir /data --jobs 16       # Long form options

REQUIREMENTS:
    - wget (for downloading files)
    - xargs (for parallel execution)
    - bash 4.0+ (for associative arrays)

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -o|--output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -j|--jobs)
            JOBS="$2"
            shift 2
            ;;
        -f|--file)
            URL_FILE="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            show_usage
            exit 1
            ;;
    esac
done

# Validate arguments
if ! [[ "$JOBS" =~ ^[0-9]+$ ]] || [ "$JOBS" -lt 1 ]; then
    echo "Error: Number of jobs must be a positive integer" >&2
    exit 1
fi

# Check if URL file exists
if [[ ! -f "$URL_FILE" ]]; then
    echo "Error: URL file '$URL_FILE' not found" >&2
    exit 1
fi

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Get absolute path for output directory
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

# Count total URLs
TOTAL_URLS=$(wc -l < "$URL_FILE")

echo "Starting bulk download..."
echo "URL file: $URL_FILE"
echo "Output directory: $OUTPUT_DIR"
echo "Parallel jobs: $JOBS"
echo "Total files to download: $TOTAL_URLS"
echo ""

# Function to download a single file
download_file() {
    local url="$1"
    local output_dir="$2"
    local filename=$(basename "$url")
    local filepath="$output_dir/$filename"
    
    # Skip if file already exists
    if [[ -f "$filepath" ]]; then
        echo "Skipping $filename (already exists)"
        return 0
    fi
    
    echo "Downloading $filename..."
    if wget -q --show-progress -O "$filepath" "$url"; then
        echo "✓ Downloaded $filename"
        return 0
    else
        echo "✗ Failed to download $filename" >&2
        return 1
    fi
}

# Export function for parallel execution
export -f download_file

# Download files in parallel
echo "Starting parallel downloads..."
if cat "$URL_FILE" | xargs -n 1 -P "$JOBS" -I {} bash -c 'download_file "$@"' _ {} "$OUTPUT_DIR"; then
    echo ""
    echo "✓ All downloads completed successfully!"
    
    # Count downloaded files
    DOWNLOADED_COUNT=$(find "$OUTPUT_DIR" -name "*.csv.gz" | wc -l)
    echo "Downloaded files: $DOWNLOADED_COUNT"
    
    # Show disk usage
    if command -v du >/dev/null 2>&1; then
        DISK_USAGE=$(du -sh "$OUTPUT_DIR" | cut -f1)
        echo "Total disk usage: $DISK_USAGE"
    fi
else
    echo ""
    echo "✗ Some downloads failed. Check the output above for details." >&2
    exit 1
fi
