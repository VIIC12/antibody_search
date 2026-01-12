#!/usr/bin/env python3
"""
Download marker service.

This service monitors nginx access logs and creates marker files for completed downloads.
When a file is successfully downloaded (HTTP 200), a marker file is created to indicate
the download is complete and the file can be cleaned up.
"""

import os
import re
import time
import logging
from pathlib import Path
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Marker file suffix
MARKER_SUFFIX = ".downloaded"


def get_download_directory() -> Path:
    """Get the download directory path from environment variable or use default."""
    download_dir = os.getenv("ABHUNTER_DOWNLOAD_DIR", "./downloads")
    download_path = Path(download_dir)
    return download_path


def get_nginx_log_path() -> Path:
    """Get the nginx access log path."""
    log_path = os.getenv("NGINX_ACCESS_LOG", "/var/log/nginx/downloads_access.log")
    return Path(log_path)


def extract_downloaded_file(log_line: str) -> Optional[str]:
    """
    Extract downloaded file path from nginx access log line.
    
    Expected log format: standard nginx combined format or custom format
    Example: '172.22.180.238 - - [01/Jan/2024:12:00:00 +0000] "GET /downloads/abc123.parquet HTTP/1.1" 200 5368709120 ...'
    
    Args:
        log_line: Single line from nginx access log
        
    Returns:
        Filename if it's a successful download (200 status), None otherwise
    """
    # Pattern to match successful downloads: HTTP 200 status and /downloads/ path
    # Matches: GET /downloads/{filename} HTTP/1.x" 200
    pattern = r'GET\s+/downloads/([^\s"]+)\s+HTTP/[0-9.]+"\s+200\s+'
    match = re.search(pattern, log_line)
    
    if match:
        filename = match.group(1)
        # Only process actual files (not directories or special paths)
        if '.' in filename and not filename.startswith('.'):
            return filename
    
    return None


def mark_file_downloaded(download_dir: Path, filename: str) -> bool:
    """
    Create a marker file to indicate a file has been downloaded.
    
    Args:
        download_dir: Directory containing download files
        filename: Name of the downloaded file
        
    Returns:
        True if marker was created, False otherwise
    """
    file_path = download_dir / filename
    
    # Verify the file exists
    if not file_path.exists():
        logger.debug(f"File does not exist, skipping marker: {filename}")
        return False
    
    # Create marker file
    marker_path = download_dir / f"{filename}{MARKER_SUFFIX}"
    
    try:
        marker_path.touch()
        logger.info(f"Marked file as downloaded: {filename}")
        return True
    except OSError as e:
        logger.error(f"Failed to create marker for {filename}: {e}")
        return False


def process_nginx_logs(download_dir: Path, log_path: Path, last_position: int = 0) -> int:
    """
    Process nginx access logs to mark completed downloads.
    
    Args:
        download_dir: Directory containing download files
        log_path: Path to nginx access log file
        last_position: Last read position in the log file (for tailing)
        
    Returns:
        New file position after processing
    """
    if not log_path.exists():
        logger.debug(f"Log file does not exist: {log_path}")
        return last_position
    
    try:
        with open(log_path, 'r') as f:
            # Seek to last position
            f.seek(last_position)
            
            # Read new lines
            new_lines = f.readlines()
            new_position = f.tell()
            
            # Process each line
            for line in new_lines:
                filename = extract_downloaded_file(line)
                if filename:
                    mark_file_downloaded(download_dir, filename)
            
            return new_position
            
    except OSError as e:
        logger.error(f"Error reading log file {log_path}: {e}")
        return last_position


def main():
    """Main entry point for download marker service."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Mark downloaded files for cleanup")
    parser.add_argument(
        '--interval',
        type=int,
        default=30,
        help='Check logs every N seconds (default: 30)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Process logs once and exit'
    )
    
    args = parser.parse_args()
    
    download_dir = get_download_directory()
    log_path = get_nginx_log_path()
    
    if args.once:
        logger.info(f"Processing logs once from {log_path}")
        process_nginx_logs(download_dir, log_path)
        return
    
    # Continuous mode - tail the log file
    logger.info(f"Starting download marker service (checking {log_path} every {args.interval}s)")
    last_position = 0
    
    try:
        while True:
            last_position = process_nginx_logs(download_dir, log_path, last_position)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Download marker service stopped by user")


if __name__ == "__main__":
    main()
