#!/usr/bin/env python
"""
Automated OAS Database Update Script

This script:
1. Checks your current database for existing files
2. Compares with your OAS download script (e.g., full.sh)
3. Downloads only new/missing files
4. Converts to Parquet automatically
5. Updates metadata

Usage:
    python scripts/update_from_oas.py --download-script ../Server/full.sh --download-dir downloads/
"""

import argparse
import logging
import subprocess
import time
from pathlib import Path
from typing import List, Set
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_existing_files(parquet_dir: Path) -> Set[str]:
    """
    Get list of files already in the database.
    
    Returns set of base filenames (without .parquet extension).
    """
    existing = set()
    
    for pfile in parquet_dir.rglob("*.parquet"):
        if pfile.name != 'metadata.parquet':
            # Remove .parquet extension and .csv if present
            basename = pfile.stem.replace('.csv', '')
            existing.add(basename)
    
    logger.info(f"Found {len(existing)} existing files in database")
    return existing


def parse_download_script(script_path: Path) -> List[tuple]:
    """
    Parse a download script (like full.sh) to get list of files.
    
    Returns list of (url, filename) tuples.
    """
    files_to_download = []
    
    if not script_path.exists():
        logger.error(f"Download script not found: {script_path}")
        return files_to_download
    
    with open(script_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('wget '):
                url = line.replace('wget ', '')
                filename = url.split('/')[-1]
                files_to_download.append((url, filename))
    
    logger.info(f"Found {len(files_to_download)} files in download script")
    return files_to_download


def get_new_files(all_files: List[tuple], existing: Set[str]) -> List[tuple]:
    """
    Filter to only new files not in database.
    
    Returns list of (url, filename) for files we don't have yet.
    """
    new_files = []
    
    for url, filename in all_files:
        # Remove .csv.gz to get base name
        basename = filename.replace('.csv.gz', '')
        
        if basename not in existing:
            new_files.append((url, filename))
    
    logger.info(f"Found {len(new_files)} new files to download")
    return new_files


def download_file(url: str, output_dir: Path, filename: str) -> Path:
    """
    Download a single file from OAS.
    
    Returns path to downloaded file, or None if failed.
    """
    output_path = output_dir / filename
    
    try:
        logger.info(f"Downloading: {filename}")
        
        # Use requests for better control
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        
        # Write file
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(f"  ✓ Downloaded {filename} ({size_mb:.1f} MB)")
        return output_path
        
    except Exception as e:
        logger.error(f"  ✗ Failed to download {filename}: {e}")
        return None


def download_new_files(
    new_files: List[tuple],
    download_dir: Path,
    max_files: int = None
) -> List[Path]:
    """
    Download all new files.
    
    Returns list of successfully downloaded file paths.
    """
    download_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []
    
    files_to_process = new_files[:max_files] if max_files else new_files
    
    logger.info(f"Starting download of {len(files_to_process)} files...")
    
    for i, (url, filename) in enumerate(files_to_process, 1):
        logger.info(f"[{i}/{len(files_to_process)}] {filename}")
        
        filepath = download_file(url, download_dir, filename)
        if filepath:
            downloaded.append(filepath)
        
        # Small delay to be nice to OAS server
        time.sleep(0.5)
    
    logger.info(f"Downloaded {len(downloaded)} files successfully")
    return downloaded


def convert_files(downloaded_files: List[Path], output_dir: Path):
    """
    Convert downloaded CSV.gz files to Parquet.
    """
    logger.info(f"Converting {len(downloaded_files)} files to Parquet...")
    
    for filepath in downloaded_files:
        try:
            # Run conversion script
            result = subprocess.run([
                'python',
                'scripts/convert_to_parquet.py',
                '--input', str(filepath),
                '--output', str(output_dir)
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"  ✓ Converted {filepath.name}")
            else:
                logger.error(f"  ✗ Failed to convert {filepath.name}: {result.stderr}")
                
        except Exception as e:
            logger.error(f"  ✗ Error converting {filepath.name}: {e}")


def cleanup_downloads(download_dir: Path, keep_files: bool = False):
    """
    Clean up downloaded CSV.gz files after conversion.
    """
    if not keep_files:
        logger.info("Cleaning up downloaded CSV.gz files...")
        for file in download_dir.glob("*.csv.gz"):
            file.unlink()
        logger.info("  ✓ Cleanup complete")
    else:
        logger.info("Keeping downloaded CSV.gz files")


def main():
    parser = argparse.ArgumentParser(
        description='Automated OAS database update'
    )
    parser.add_argument(
        '--download-script',
        type=str,
        required=True,
        help='Path to OAS download script (e.g., ../Server/full.sh)'
    )
    parser.add_argument(
        '--download-dir',
        type=str,
        default='downloads/temp',
        help='Temporary directory for downloads'
    )
    parser.add_argument(
        '--parquet-dir',
        type=str,
        default='data/parquet',
        help='Output directory for Parquet files'
    )
    parser.add_argument(
        '--max-new-files',
        type=int,
        default=None,
        help='Limit number of new files to download (for testing)'
    )
    parser.add_argument(
        '--keep-downloads',
        action='store_true',
        help='Keep downloaded CSV.gz files after conversion'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be downloaded without actually downloading'
    )
    
    args = parser.parse_args()
    
    script_path = Path(args.download_script)
    download_dir = Path(args.download_dir)
    parquet_dir = Path(args.parquet_dir)
    
    logger.info("="*60)
    logger.info("ABDB V3.0 - Automated OAS Update")
    logger.info("="*60)
    
    # Step 1: Get existing files
    existing_files = get_existing_files(parquet_dir)
    
    # Step 2: Parse download script
    all_oas_files = parse_download_script(script_path)
    
    if not all_oas_files:
        logger.error("No files found in download script")
        return
    
    # Step 3: Find new files
    new_files = get_new_files(all_oas_files, existing_files)
    
    if not new_files:
        logger.info("✅ Database is up-to-date! No new files to download.")
        return
    
    logger.info(f"\n📥 Need to download {len(new_files)} new files")
    
    if args.dry_run:
        logger.info("\nDRY RUN - Would download:")
        for url, filename in new_files[:10]:
            logger.info(f"  - {filename}")
        if len(new_files) > 10:
            logger.info(f"  ... and {len(new_files) - 10} more")
        return
    
    # Step 4: Download new files
    downloaded = download_new_files(new_files, download_dir, args.max_new_files)
    
    if not downloaded:
        logger.warning("No files downloaded successfully")
        return
    
    # Step 5: Convert to Parquet
    convert_files(downloaded, parquet_dir)
    
    # Step 6: Cleanup
    cleanup_downloads(download_dir, args.keep_downloads)
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("UPDATE SUMMARY")
    logger.info("="*60)
    logger.info(f"New files added: {len(downloaded)}")
    logger.info(f"Total files in database: {len(existing_files) + len(downloaded)}")
    logger.info("="*60)
    logger.info("\n✅ Update complete!")
    logger.info("\n📝 Next steps:")
    logger.info("  1. Restart Streamlit or click 'Reload Database' button")
    logger.info("  2. Verify new data appears in searches")


if __name__ == "__main__":
    main()

