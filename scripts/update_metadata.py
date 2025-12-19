#!/usr/bin/env python3
"""
Metadata Update Script - Update metadata files for parquet directories.

This script:
1. Scans data directory for parquet files in subdirectories (chain_type/isotype)
2. For each subdirectory, checks if metadata.parquet exists
3. If not, creates a new metadata file from scratch by reading metadata from parquet files
4. If it exists, checks if all parquet files are included and adds missing ones
"""

import argparse
import logging
import os
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def extract_metadata_from_parquet(parquet_path: Path) -> Dict[str, Any]:
    """
    Extract metadata from a parquet file by reading the first row.
    
    Args:
        parquet_path: Path to the parquet file
    
    Returns:
        Dictionary with metadata fields
    """
    try:
        # Read just the first row to get metadata columns
        df = pd.read_parquet(parquet_path)
        
        if len(df) == 0:
            logger.warning(f"Empty parquet file: {parquet_path}")
            return {}
        
        # Get the first row to extract metadata fields
        first_row = df.iloc[0]
        
        # Try to get path relative to data directory (might be 2 or 3 levels deep)
        try:
            # Try 3 levels up first (chain_type/isotype/filename.parquet)
            file_path = str(parquet_path.relative_to(parquet_path.parent.parent.parent))
        except ValueError:
            try:
                # Try 2 levels up (isotype/filename.parquet)
                file_path = str(parquet_path.relative_to(parquet_path.parent.parent))
            except ValueError:
                # Fall back to just the filename
                file_path = parquet_path.name
        
        # Safely extract metadata with fallback values
        # Handle both NaN values and missing keys
        def safe_get(row, key, default='Unknown'):
            try:
                value = row.get(key, default)
                if pd.isna(value):
                    return default
                return value
            except (KeyError, AttributeError):
                return default
        
        metadata = {
            'filename': parquet_path.name,
            'file_path': file_path,
            'rows': len(df),
            'total_sequences': len(df),
            'subject': safe_get(first_row, 'subject', 'Unknown'),
            'isotype': safe_get(first_row, 'isotype', 'Unknown'),
            'disease': safe_get(first_row, 'disease', 'Unknown'),
            'species': safe_get(first_row, 'species', 'Unknown'),
            'vaccine': safe_get(first_row, 'vaccine', 'Unknown'),
            'chain': safe_get(first_row, 'chain', 'Unknown'),
            'unique_sequences': safe_get(first_row, 'unqiue_sequences', 'Unknown'),  # Note: typo preserved for compatibility
        }
        
        return metadata
        
    except Exception as e:
        logger.error(f"Failed to extract metadata from {parquet_path}: {e}")
        return {}


def find_parquet_files(data_dir: Path) -> Dict[tuple, List[Path]]:
    """
    Find all parquet files in subdirectories and group by chain_type/isotype.
    
    Args:
        data_dir: Base data directory
    
    Returns:
        Dictionary mapping (chain_type, isotype) tuples to lists of parquet file paths
    """
    parquet_files = defaultdict(list)
    
    # Find all parquet files in the directory structure
    for parquet_path in data_dir.rglob("*.parquet"):
        # Skip metadata files themselves
        if parquet_path.name == "metadata.parquet":
            continue
        
        # Extract chain_type and isotype from path
        # Structure: data_dir / chain_type / isotype / filename.parquet
        parts = parquet_path.relative_to(data_dir).parts
        
        if len(parts) >= 2:
            chain_type, isotype = parts[0], parts[1]
            parquet_files[(chain_type, isotype)].append(parquet_path)
        else:
            logger.warning(f"Could not determine chain_type/isotype for {parquet_path}")
    
    return parquet_files


def update_metadata_for_subdirectory(subdir: Path, parquet_files: List[Path]) -> bool:
    """
    Update metadata.parquet file for a subdirectory.
    
    Args:
        subdir: Subdirectory path (chain_type/isotype)
        parquet_files: List of parquet files in this subdirectory
    
    Returns:
        True if successful, False otherwise
    """
    metadata_path = subdir / "metadata.parquet"
    
    logger.info(f"Processing subdirectory: {subdir}")
    logger.info(f"  Found {len(parquet_files)} parquet files")
    
    # Extract metadata from all parquet files
    metadata_records = []
    for parquet_path in parquet_files:
        metadata = extract_metadata_from_parquet(parquet_path)
        if metadata:
            metadata_records.append(metadata)
        else:
            logger.warning(f"  ⚠️  Could not extract metadata from {parquet_path.name}")
    
    if not metadata_records:
        logger.warning(f"  ❌ No valid metadata extracted for {subdir}")
        return False
    
    # Create DataFrame from metadata records
    new_df = pd.DataFrame(metadata_records)
    
    # Load existing metadata if it exists
    if metadata_path.exists():
        try:
            existing_df = pd.read_parquet(metadata_path)
            logger.info(f"  📂 Found existing metadata file with {len(existing_df)} entries")
            
            # Merge with existing data, removing duplicates based on filename
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            # Remove duplicates, keeping the last occurrence (most recent data)
            combined_df = combined_df.drop_duplicates(subset=['filename'], keep='last')
            
            # Check how many files were added
            new_files = len(new_df) - len(existing_df) + len(combined_df) - len(new_df)
            logger.info(f"  ✅ Updated metadata: {len(existing_df)} → {len(combined_df)} files (+{new_files} new)")
            
        except Exception as e:
            logger.error(f"  ❌ Could not read existing metadata file: {e}")
            combined_df = new_df
            logger.info(f"  ✅ Created new metadata (old file was corrupted): {len(new_df)} files")
    else:
        combined_df = new_df
        logger.info(f"  ✅ Created new metadata file: {len(new_df)} files")
    
    # Save the updated metadata
    try:
        combined_df.to_parquet(metadata_path, index=False)
        logger.info(f"  💾 Saved metadata to: {metadata_path}")
        return True
        
    except Exception as e:
        logger.error(f"  ❌ Could not save metadata file: {e}")
        return False


def inspect_metadata_files(data_dir: Path, max_rows: int = 10) -> None:
    """
    Inspect existing metadata files and show their contents.
    
    Args:
        data_dir: Base data directory
        max_rows: Maximum number of rows to display from each metadata file
    """
    logger.info(f"🔍 Scanning for metadata files in {data_dir}")
    
    # Find all metadata files
    metadata_files = []
    for metadata_path in data_dir.rglob("metadata.parquet"):
        metadata_files.append(metadata_path)
    
    if not metadata_files:
        logger.warning("❌ No metadata files found in data directory")
        return
    
    logger.info(f"📊 Found {len(metadata_files)} metadata files\n")
    
    total_entries = 0
    total_files_referenced = 0
    
    for metadata_path in sorted(metadata_files):
        try:
            df = pd.read_parquet(metadata_path)
            
            # Get the relative path from data_dir
            try:
                rel_path = metadata_path.relative_to(data_dir)
                subdir = '/'.join(rel_path.parts[:-1])  # Remove filename
            except ValueError:
                subdir = str(metadata_path.parent)
            
            total_entries += len(df)
            
            # Count unique files referenced
            if 'filename' in df.columns:
                total_files_referenced += len(df['filename'].unique())
            
            logger.info("="*80)
            logger.info(f"📁 {subdir}/metadata.parquet")
            logger.info(f"   Total entries: {len(df)}")
            logger.info(f"   Columns: {', '.join(df.columns)}")
            
            # Show first few rows
            if len(df) > 0:
                logger.info(f"\n   First {min(max_rows, len(df))} entries:")
                pd.set_option('display.max_columns', None)
                pd.set_option('display.width', None)
                pd.set_option('display.max_colwidth', 50)
                
                print(df.head(max_rows).to_string(index=False))
                
                if len(df) > max_rows:
                    logger.info(f"   ... and {len(df) - max_rows} more entries")
            
            logger.info("")
            
        except Exception as e:
            logger.error(f"❌ Failed to read {metadata_path}: {e}")
    
    logger.info("="*80)
    logger.info(f"📊 Summary: {len(metadata_files)} metadata files, {total_entries} total entries")


def update_all_metadata(data_dir: Path) -> Dict[str, Any]:
    """
    Update metadata files for all subdirectories containing parquet files.
    
    Args:
        data_dir: Base data directory
    
    Returns:
        Dictionary with statistics about the update process
    """
    logger.info(f"🔍 Scanning for parquet files in {data_dir}")
    
    # Find all parquet files grouped by subdirectory
    parquet_files_dict = find_parquet_files(data_dir)
    
    if not parquet_files_dict:
        logger.warning("❌ No parquet files found in data directory")
        return {
            'total_subdirs': 0,
            'successful': 0,
            'failed': 0,
            'total_files': 0
        }
    
    logger.info(f"📊 Found {len(parquet_files_dict)} subdirectories with parquet files")
    
    stats = {
        'total_subdirs': len(parquet_files_dict),
        'successful': 0,
        'failed': 0,
        'total_files': sum(len(files) for files in parquet_files_dict.values()),
        'new_metadata_files': 0,
        'updated_metadata_files': 0
    }
    
    # Process each subdirectory
    for (chain_type, isotype), parquet_files in sorted(parquet_files_dict.items()):
        subdir = data_dir / chain_type / isotype
        
        # Check if metadata file exists
        metadata_path = subdir / "metadata.parquet"
        metadata_existed = metadata_path.exists()
        
        success = update_metadata_for_subdirectory(subdir, parquet_files)
        
        if success:
            stats['successful'] += 1
            if metadata_existed:
                stats['updated_metadata_files'] += 1
            else:
                stats['new_metadata_files'] += 1
        else:
            stats['failed'] += 1
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Update metadata files for parquet directories',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script scans the data directory for parquet files and ensures that each
subdirectory (chain_type/isotype) has a corresponding metadata.parquet file.

If a metadata file doesn't exist, it creates one from scratch by reading
metadata columns from the parquet files. If it exists, it updates it to include
any new or missing parquet files.

Examples:
  # Update metadata for all parquet files in ./data
  python scripts/update_metadata.py

  # Update metadata for parquet files in a specific directory
  python scripts/update_metadata.py --data-dir /path/to/data

  # Inspect existing metadata files and show their contents
  python scripts/update_metadata.py --inspect

  # Dry run: show what would be updated without actually updating
  python scripts/update_metadata.py --dry-run
        """
    )
    
    parser.add_argument(
        '--data-dir',
        type=str,
        default='data',
        help='Base data directory (default: data)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without actually updating metadata files'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed information about each file processed'
    )
    
    parser.add_argument(
        '--inspect',
        action='store_true',
        help='Inspect existing metadata files and show their contents'
    )
    
    parser.add_argument(
        '--max-rows',
        type=int,
        default=10,
        help='Maximum number of rows to display when inspecting metadata files (default: 10)'
    )
    
    args = parser.parse_args()
    
    # Set log level based on verbose flag
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("="*60)
    logger.info("ABDB V3.0 - Metadata Update Script")
    logger.info("="*60)
    
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No files will be modified")
    
    data_dir = Path(args.data_dir)
    
    if not data_dir.exists():
        logger.error(f"❌ Data directory not found: {data_dir}")
        return
    
    if not data_dir.is_dir():
        logger.error(f"❌ Path is not a directory: {data_dir}")
        return
    
    logger.info(f"📁 Data directory: {data_dir.absolute()}")
    
    if args.inspect:
        # Inspect existing metadata files
        logger.info("\n🔍 INSPECTING EXISTING METADATA FILES")
        logger.info("="*60)
        inspect_metadata_files(data_dir, args.max_rows)
        return
    
    if args.dry_run:
        # Just show what would be processed
        logger.info("\n🔍 DRY RUN - Files that would be processed:")
        
        parquet_files_dict = find_parquet_files(data_dir)
        
        for (chain_type, isotype), parquet_files in sorted(parquet_files_dict.items()):
            metadata_path = data_dir / chain_type / isotype / "metadata.parquet"
            
            logger.info(f"\n  📂 {chain_type}/{isotype}:")
            logger.info(f"     Parquet files: {len(parquet_files)}")
            logger.info(f"     Metadata file exists: {metadata_path.exists()}")
            
            if metadata_path.exists():
                try:
                    existing_df = pd.read_parquet(metadata_path)
                    logger.info(f"     Current metadata entries: {len(existing_df)}")
                    logger.info(f"     Missing files: {len(parquet_files) - len(existing_df)}")
                except Exception as e:
                    logger.warning(f"     Could not read metadata: {e}")
    else:
        # Actually update metadata
        logger.info("\n🔄 Updating metadata files...")
        
        stats = update_all_metadata(data_dir)
        
        # Show summary
        logger.info("\n" + "="*60)
        logger.info("METADATA UPDATE SUMMARY")
        logger.info("="*60)
        logger.info(f"Total subdirectories: {stats['total_subdirs']}")
        logger.info(f"  ✅ Successful: {stats['successful']}")
        logger.info(f"  ❌ Failed: {stats['failed']}")
        logger.info(f"  🆕 New metadata files: {stats['new_metadata_files']}")
        logger.info(f"  📝 Updated metadata files: {stats['updated_metadata_files']}")
        logger.info(f"Total parquet files processed: {stats['total_files']}")
        logger.info("="*60)
        
        if stats['successful'] > 0:
            logger.info("\n🎉 Metadata update complete!")
        elif stats['failed'] > 0:
            logger.error("\n❌ Metadata update failed!")
        else:
            logger.info("\n💡 No parquet files found to process.")


if __name__ == "__main__":
    main()

