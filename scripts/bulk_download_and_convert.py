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
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# Import conversion functions from the same directory
from convert_to_parquet import convert_file, create_metadata_table

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


def convert_and_cleanup(csv_path: Path, output_dir: Path, extraction_level: int = 1) -> dict:
    """Convert CSV to Parquet and clean up."""
    try:
        # Convert to Parquet using the proper function signature
        logger.info(f"Converting: {csv_path.name}")
        
        stats = convert_file(
            input_path=csv_path,
            output_dir=output_dir,
            extraction_level=extraction_level
        )
        
        if 'error' not in stats:
            logger.info(f"✓ Converted: {csv_path.name}")
            
            # Delete the CSV.gz file
            csv_path.unlink()
            logger.info(f"✓ Cleaned up: {csv_path.name}")
            
            return stats
        else:
            logger.error(f"✗ Conversion failed: {csv_path.name} - {stats['error']}")
            return stats
            
    except Exception as e:
        logger.error(f"✗ Conversion error: {csv_path.name} - {e}")
        return {'filename': csv_path.name, 'error': str(e)}


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
        help='Path to bulk download script (OAS bulk download script.sh file with wget commands)'
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
        '--extraction-level',
        type=int,
        choices=[1, 2, 3],
        default=1,
        help='Extraction level for data: 1=Basic (default), 2=+Additional, 3=+Full'
    )
    
    parser.add_argument(
        '-j',
        '--jobs',
        type=int,
        default=min(os.cpu_count(), 4),  # Limit to 4 to avoid overwhelming the server
        help='Number of parallel downloads (default: min(CPU cores, 4))'
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
    
    
    # Check existing Parquet files (including subdirectories by isotype)
    existing_parquet = set()
    for parquet_file in output_dir.rglob('*.parquet'):
        existing_parquet.add(parquet_file.name)
    
    logger.info(f"Found {len(existing_parquet)} existing Parquet files")
    
    def process_single_file(url: str) -> dict:
        """Process a single URL: download and convert."""
        csv_filename = get_filename_from_url(url)
        parquet_filename = get_parquet_filename(csv_filename)
        
        # Check if Parquet already exists
        if parquet_filename in existing_parquet:
            return {'status': 'skipped', 'filename': csv_filename, 'reason': 'Parquet exists'}
        
        # Download file
        csv_path = download_file(url, temp_dir)
        
        if csv_path is None:
            return {'status': 'failed', 'filename': csv_filename, 'reason': 'Download failed'}
        
        # Convert to Parquet
        stats = convert_and_cleanup(csv_path, output_dir, args.extraction_level)
        
        if 'error' not in stats:
            return {'status': 'success', 'filename': csv_filename, 'stats': stats}
        else:
            # Clean up failed download file
            try:
                if csv_path.exists():
                    csv_path.unlink()
                    logger.info(f"✓ Cleaned up failed download: {csv_filename}")
            except Exception as e:
                logger.warning(f"⚠️  Could not clean up failed download {csv_filename}: {e}")
            return {'status': 'failed', 'filename': csv_filename, 'reason': stats['error']}
    
    # Process URLs in parallel
    logger.info(f"Processing {len(urls)} URLs with {args.jobs} parallel workers")
    logger.info(f"Extraction level: {args.extraction_level}")
    
    stats = {
        'total': len(urls),
        'skipped': 0,
        'downloaded': 0,
        'converted': 0,
        'failed': 0
    }
    
    conversion_stats = []  # Store conversion statistics for metadata creation
    
    start_time = time.time()
    
    # Process files in parallel
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        # Submit all tasks
        future_to_url = {
            executor.submit(process_single_file, url): url
            for url in urls
        }
        
        # Process completed tasks with progress bar
        for future in tqdm(as_completed(future_to_url), total=len(urls), desc="Processing files"):
            result = future.result()
            
            if result['status'] == 'skipped':
                stats['skipped'] += 1
                logger.info(f"⏭️  Skipped: {result['filename']}")
            elif result['status'] == 'success':
                stats['downloaded'] += 1
                stats['converted'] += 1
                conversion_stats.append(result['stats'])
                logger.info(f"✓ Processed: {result['filename']}")
            else:
                stats['failed'] += 1
                logger.error(f"✗ Failed: {result['filename']} - {result['reason']}")
    
    # Create metadata tables from all converted files
    if conversion_stats:
        logger.info("Creating metadata tables...")
        create_metadata_table(conversion_stats, output_dir)
    
    # Clean up temporary download directory
    if temp_dir.exists() and temp_dir != output_dir:
        logger.info("Cleaning up temporary download directory...")
        try:
            import shutil
            shutil.rmtree(temp_dir)
            logger.info(f"✓ Cleaned up: {temp_dir}")
        except Exception as e:
            logger.warning(f"⚠️  Could not clean up temp directory {temp_dir}: {e}")
    
    # Summary
    elapsed = time.time() - start_time
    
    # Format elapsed time nicely
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = elapsed % 60
    
    if hours > 0:
        time_str = f"{hours}h {minutes}m {seconds:.1f}s"
    elif minutes > 0:
        time_str = f"{minutes}m {seconds:.1f}s"
    else:
        time_str = f"{seconds:.1f}s"
    
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total files: {stats['total']}")
    logger.info(f"Skipped (existing): {stats['skipped']}")
    logger.info(f"Downloaded: {stats['downloaded']}")
    logger.info(f"Converted: {stats['converted']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"⏱️  Total time: {time_str}")
    
    if stats['failed'] > 0:
        logger.warning(f"⚠️  {stats['failed']} files failed - check logs for details")
        sys.exit(1)
    else:
        logger.info("✅ All files processed successfully!")


if __name__ == '__main__':
    main()
