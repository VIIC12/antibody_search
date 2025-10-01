#!/usr/bin/env python3
"""
Bulk Download and Convert Script

Downloads CSV.gz files from a bulk download script, converts them to Parquet format,
and manages the conversion process efficiently.

Usage:
    python bulk_download_and_convert.py --input bulk_download-3.sh --output ./human
    python bulk_download_and_convert.py --input /path/to/download_script.sh --output /path/to/output
"""

import argparse
import os
import sys
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
import logging
from typing import List, Set
import time

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from convert_to_parquet import convert_file, get_columns_for_chain

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bulk_download.log')
    ]
)
logger = logging.getLogger(__name__)


def parse_download_script(script_path: str) -> List[str]:
    """Parse the bulk download script and extract URLs."""
    urls = []
    
    try:
        with open(script_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line.startswith('wget '):
                    # Extract URL from wget command
                    parts = line.split()
                    for part in parts[1:]:  # Skip 'wget'
                        if part.startswith('http'):
                            urls.append(part)
                            break
                    else:
                        logger.warning(f"Line {line_num}: Could not extract URL from: {line}")
    
    except FileNotFoundError:
        logger.error(f"Download script not found: {script_path}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error parsing download script: {e}")
        sys.exit(1)
    
    logger.info(f"Found {len(urls)} URLs in download script")
    return urls


def get_filename_from_url(url: str) -> str:
    """Extract filename from URL."""
    parsed = urlparse(url)
    return os.path.basename(parsed.path)


def get_parquet_filename(csv_filename: str) -> str:
    """Convert CSV.gz filename to Parquet filename (matching convert_file behavior)."""
    if csv_filename.endswith('.csv.gz'):
        # convert_file uses input_path.stem, so file.csv.gz becomes file.csv.parquet
        return csv_filename[:-3] + '.parquet'  # Remove .gz, keep .csv
    elif csv_filename.endswith('.csv'):
        return csv_filename + '.parquet'
    else:
        return csv_filename + '.parquet'


def check_existing_parquet(output_dir: Path, parquet_filename: str) -> bool:
    """Check if Parquet file already exists in output directory."""
    parquet_path = output_dir / parquet_filename
    return parquet_path.exists()


def download_file(url: str, download_dir: Path) -> Path:
    """Download a file using wget."""
    filename = get_filename_from_url(url)
    file_path = download_dir / filename
    
    # Skip if already downloaded
    if file_path.exists():
        logger.info(f"File already exists, skipping download: {filename}")
        return file_path
    
    logger.info(f"Downloading: {filename}")
    
    try:
        # Use wget with progress bar and resume capability
        cmd = [
            'wget',
            '--continue',  # Resume partial downloads
            '--progress=bar:force',  # Show progress bar
            '--timeout=30',  # 30 second timeout
            '--tries=3',  # Retry 3 times
            '-O', str(file_path),  # Output file
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            logger.info(f"✓ Downloaded: {filename}")
            return file_path
        else:
            logger.error(f"✗ Download failed: {filename}")
            logger.error(f"Error: {result.stderr}")
            return None
            
    except subprocess.TimeoutExpired:
        logger.error(f"✗ Download timeout: {filename}")
        return None
    except Exception as e:
        logger.error(f"✗ Download error: {filename} - {e}")
        return None


def convert_and_cleanup(csv_path: Path, output_dir: Path, temp_dir: Path) -> bool:
    """Convert CSV to Parquet and clean up."""
    try:
        # Determine output filename
        parquet_filename = get_parquet_filename(csv_path.name)
        parquet_path = output_dir / parquet_filename
        
        # Convert to Parquet
        logger.info(f"Converting: {csv_path.name} → {parquet_filename}")
        
        success = convert_file(
            input_path=csv_path,
            output_dir=output_dir,
            columns=get_columns_for_chain(csv_path.name)
        )
        
        if success:
            logger.info(f"✓ Converted: {parquet_filename}")
            
            # Delete the CSV.gz file
            csv_path.unlink()
            logger.info(f"✓ Cleaned up: {csv_path.name}")
            
            return True
        else:
            logger.error(f"✗ Conversion failed: {csv_path.name}")
            return False
            
    except Exception as e:
        logger.error(f"✗ Conversion error: {csv_path.name} - {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Bulk download and convert CSV.gz files to Parquet format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python bulk_download_and_convert.py --input bulk_download-3.sh --output ./human
    python bulk_download_and_convert.py --input /path/to/script.sh --output /path/to/output
        """
    )
    
    parser.add_argument(
        '--input',
        required=True,
        help='Path to bulk download script (.sh file with wget commands)'
    )
    
    parser.add_argument(
        '--output',
        required=True,
        help='Output directory for Parquet files'
    )
    
    parser.add_argument(
        '--temp-dir',
        help='Temporary download directory (default: <output>/temp_download)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be downloaded without actually downloading'
    )
    
    parser.add_argument(
        '--max-files',
        type=int,
        help='Maximum number of files to process (for testing)'
    )
    
    args = parser.parse_args()
    
    # Setup paths
    script_path = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()
    temp_dir = Path(args.temp_dir) if args.temp_dir else output_dir / 'temp_download'
    
    # Create directories
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Script: {script_path}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Temp: {temp_dir}")
    
    # Parse download script
    urls = parse_download_script(str(script_path))
    
    if not urls:
        logger.error("No URLs found in download script")
        sys.exit(1)
    
    # Limit files if specified
    if args.max_files:
        urls = urls[:args.max_files]
        logger.info(f"Limited to {args.max_files} files for testing")
    
    # Check existing Parquet files (including subdirectories by isotype)
    existing_parquet = set()
    for parquet_file in output_dir.rglob('*.parquet'):
        existing_parquet.add(parquet_file.name)
    
    logger.info(f"Found {len(existing_parquet)} existing Parquet files")
    
    # Process URLs
    stats = {
        'total': len(urls),
        'skipped': 0,
        'downloaded': 0,
        'converted': 0,
        'failed': 0
    }
    
    start_time = time.time()
    
    for i, url in enumerate(urls, 1):
        logger.info(f"\n[{i}/{len(urls)}] Processing: {url}")
        
        # Get filenames
        csv_filename = get_filename_from_url(url)
        parquet_filename = get_parquet_filename(csv_filename)
        
        # Check if Parquet already exists
        if parquet_filename in existing_parquet:
            logger.info(f"⏭️  Skipping (Parquet exists): {parquet_filename}")
            stats['skipped'] += 1
            continue
        
        if args.dry_run:
            logger.info(f"🔍 Would download: {csv_filename}")
            stats['downloaded'] += 1
            continue
        
        # Download file
        csv_path = download_file(url, temp_dir)
        
        if csv_path is None:
            stats['failed'] += 1
            continue
        
        stats['downloaded'] += 1
        
        # Convert to Parquet
        if convert_and_cleanup(csv_path, output_dir, temp_dir):
            stats['converted'] += 1
        else:
            stats['failed'] += 1
    
    # Summary
    elapsed = time.time() - start_time
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total files: {stats['total']}")
    logger.info(f"Skipped (existing): {stats['skipped']}")
    logger.info(f"Downloaded: {stats['downloaded']}")
    logger.info(f"Converted: {stats['converted']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"Time elapsed: {elapsed:.1f} seconds")
    
    if stats['failed'] > 0:
        logger.warning(f"⚠️  {stats['failed']} files failed - check logs for details")
        sys.exit(1)
    else:
        logger.info("✅ All files processed successfully!")


if __name__ == '__main__':
    main()
