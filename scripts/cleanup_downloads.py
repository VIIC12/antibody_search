#!/usr/bin/env python3
"""
Cleanup script for large download files.

This script monitors the download directory and deletes files that have been
marked as downloaded. Files are marked by the download_callback service when
nginx calls the HTTP callback endpoint after a successful download completion.
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Marker file suffix (must match download_callback_service.py)
MARKER_SUFFIX = ".downloaded"


def get_download_directory() -> Path:
    """Get the download directory path from environment variable or use default."""
    download_dir = os.getenv("ABHUNTER_DOWNLOAD_DIR", "./downloads")
    download_path = Path(download_dir)
    return download_path


def has_download_marker(file_path: Path) -> bool:
    """
    Check if a file has a download marker indicating it was successfully downloaded.
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if marker file exists, False otherwise
    """
    marker_path = file_path.parent / f"{file_path.name}{MARKER_SUFFIX}"
    return marker_path.exists()


def should_delete_file(file_path: Path) -> bool:
    """
    Determine if a file should be deleted based on download marker.
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if file should be deleted (has download marker), False otherwise
    """
    # Check if file has a download marker
    if has_download_marker(file_path):
        return True
    
    # Safety: Also delete files older than 24 hours (in case marker service fails)
    try:
        file_age = time.time() - os.path.getmtime(file_path)
        if file_age > 86400:  # 24 hours
            logger.warning(f"File {file_path.name} is older than 24 hours, deleting as safety measure")
            return True
    except OSError as e:
        logger.warning(f"Error checking file age for {file_path}: {e}")
        return False
    
    return False


def cleanup_downloads(download_dir: Path, dry_run: bool = False) -> int:
    """
    Clean up downloaded files that have been marked as downloaded.
    
    Args:
        download_dir: Directory containing download files
        dry_run: If True, only log what would be deleted without actually deleting
        
    Returns:
        Number of files deleted (or would be deleted in dry_run mode)
    """
    if not download_dir.exists():
        logger.warning(f"Download directory does not exist: {download_dir}")
        return 0
    
    deleted_count = 0
    
    # Iterate through files in download directory
    for file_path in download_dir.iterdir():
        if not file_path.is_file():
            continue
        
        # Skip hidden files, marker files, and metadata files
        if file_path.name.startswith('.') or file_path.name.endswith(MARKER_SUFFIX):
            continue
        
        if should_delete_file(file_path):
            try:
                file_size = file_path.stat().st_size
                file_size_mb = file_size / (1024 * 1024)
                
                # Also delete the marker file if it exists
                marker_path = download_dir / f"{file_path.name}{MARKER_SUFFIX}"
                
                if dry_run:
                    logger.info(f"[DRY RUN] Would delete: {file_path.name} ({file_size_mb:.2f} MB)")
                    if marker_path.exists():
                        logger.info(f"[DRY RUN] Would delete marker: {marker_path.name}")
                else:
                    file_path.unlink()
                    logger.info(f"Deleted: {file_path.name} ({file_size_mb:.2f} MB)")
                    
                    # Delete marker file if it exists
                    if marker_path.exists():
                        try:
                            marker_path.unlink()
                        except OSError as e:
                            logger.warning(f"Failed to delete marker {marker_path.name}: {e}")
                
                deleted_count += 1
            except OSError as e:
                logger.error(f"Failed to delete {file_path}: {e}")
    
    return deleted_count


def main():
    """Main entry point for cleanup script."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Cleanup large download files")
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=300,
        help='Run cleanup every N seconds (default: 300)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run cleanup once and exit'
    )
    
    args = parser.parse_args()
    
    download_dir = get_download_directory()
    
    if args.once:
        logger.info(f"Running cleanup once on {download_dir}")
        deleted = cleanup_downloads(download_dir, dry_run=args.dry_run)
        logger.info(f"Cleanup complete. {deleted} file(s) {'would be ' if args.dry_run else ''}deleted.")
        return
    
    # Continuous mode
    logger.info(f"Starting cleanup daemon for {download_dir} (interval: {args.interval}s)")
    try:
        while True:
            deleted = cleanup_downloads(download_dir, dry_run=args.dry_run)
            if deleted > 0:
                logger.info(f"Cleanup cycle complete. {deleted} file(s) {'would be ' if args.dry_run else ''}deleted.")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Cleanup daemon stopped by user")


if __name__ == "__main__":
    main()
