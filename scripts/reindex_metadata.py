#!/usr/bin/env python
"""
Reindex metadata after adding/removing Parquet files.

This script:
1. Scans all existing Parquet files
2. Reads their built-in metadata
3. Recreates the metadata.parquet summary table

Use this when you:
- Delete Parquet files
- Add new Parquet files manually
- Metadata.parquet gets corrupted
- Want to verify counts
"""

import argparse
import logging
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_parquet_metadata(parquet_file: Path) -> dict:
    """
    Extract metadata from a Parquet file.
    
    This reads the Parquet file's built-in metadata, not the data itself.
    Very fast operation (milliseconds per file).
    """
    try:
        # Read Parquet metadata (not the actual data)
        parquet_table = pq.read_table(parquet_file)
        
        # Get row count from metadata
        num_rows = parquet_table.num_rows
        
        # Try to get our custom metadata columns
        if 'subject' in parquet_table.column_names:
            # Read just the subject column (first value)
            subjects = parquet_table.column('subject').to_pylist()
            subject = subjects[0] if subjects else 'Unknown'
        else:
            subject = 'Unknown'
        
        if 'isotype' in parquet_table.column_names:
            isotypes = parquet_table.column('isotype').to_pylist()
            isotype = isotypes[0] if isotypes else 'Unknown'
        else:
            # Infer from filename or directory
            if 'IGHM' in parquet_file.stem:
                isotype = 'IGHM'
            elif 'IGHG' in parquet_file.stem:
                isotype = 'IGHG'
            else:
                isotype = parquet_file.parent.name
        
        return {
            'filename': parquet_file.name,
            'filepath': str(parquet_file),
            'rows': num_rows,
            'subject': subject,
            'isotype': isotype,
            'file_size_mb': parquet_file.stat().st_size / (1024 * 1024),
        }
    
    except Exception as e:
        logger.error(f"Failed to read metadata from {parquet_file}: {e}")
        return None


def reindex_metadata(data_dir: Path, output_file: Path = None):
    """
    Reindex all Parquet files and create new metadata table.
    
    Args:
        data_dir: Directory containing Parquet files
        output_file: Output path for metadata.parquet (default: data_dir/metadata.parquet)
    """
    if output_file is None:
        output_file = data_dir / 'metadata.parquet'
    
    logger.info(f"Scanning directory: {data_dir}")
    
    # Find all Parquet files (exclude metadata.parquet itself)
    parquet_files = [
        f for f in data_dir.rglob("*.parquet") 
        if f.name != 'metadata.parquet'
    ]
    
    if not parquet_files:
        logger.error(f"No Parquet files found in {data_dir}")
        return
    
    logger.info(f"Found {len(parquet_files)} Parquet files")
    
    # Extract metadata from each file
    metadata_records = []
    total_rows = 0
    
    for pfile in tqdm(parquet_files, desc="Reading metadata"):
        meta = extract_parquet_metadata(pfile)
        if meta:
            metadata_records.append(meta)
            total_rows += meta['rows']
    
    # Create metadata DataFrame
    metadata_df = pd.DataFrame(metadata_records)
    
    # Sort by subject and filename
    metadata_df = metadata_df.sort_values(['subject', 'filename'])
    
    # Save as Parquet
    metadata_df.to_parquet(output_file, index=False)
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("REINDEXING SUMMARY")
    logger.info("="*60)
    logger.info(f"Files indexed: {len(metadata_records)}")
    logger.info(f"Total sequences: {total_rows:,}")
    logger.info(f"Total size: {metadata_df['file_size_mb'].sum():.1f} MB")
    logger.info(f"Metadata file: {output_file}")
    logger.info(f"Metadata size: {output_file.stat().st_size / 1024:.1f} KB")
    
    # Breakdown by subject
    logger.info("\nSequences by subject:")
    subject_summary = metadata_df.groupby('subject')['rows'].sum().sort_values(ascending=False)
    for subject, count in subject_summary.head(10).items():
        logger.info(f"  {subject}: {count:,}")
    
    # Breakdown by isotype
    logger.info("\nSequences by isotype:")
    isotype_summary = metadata_df.groupby('isotype')['rows'].sum().sort_values(ascending=False)
    for isotype, count in isotype_summary.items():
        logger.info(f"  {isotype}: {count:,}")
    
    logger.info("="*60)
    logger.info("✅ Reindexing complete!")
    
    return metadata_df


def verify_counts(data_dir: Path):
    """
    Verify sequence counts match between files and metadata table.
    
    Useful for checking data integrity.
    """
    logger.info("Verifying counts...")
    
    # Count from Parquet files directly
    parquet_files = [
        f for f in data_dir.rglob("*.parquet") 
        if f.name != 'metadata.parquet'
    ]
    
    actual_count = 0
    for pfile in parquet_files:
        parquet_table = pq.read_table(pfile)
        actual_count += parquet_table.num_rows
    
    logger.info(f"Actual count (from Parquet files): {actual_count:,}")
    
    # Count from metadata table
    metadata_file = data_dir / 'metadata.parquet'
    if metadata_file.exists():
        metadata_df = pd.read_parquet(metadata_file)
        metadata_count = metadata_df['rows'].sum()
        logger.info(f"Metadata count (from metadata.parquet): {metadata_count:,}")
        
        if actual_count == metadata_count:
            logger.info("✅ Counts match - metadata is accurate")
            return True
        else:
            logger.warning(f"⚠️  Counts don't match! Difference: {abs(actual_count - metadata_count):,}")
            logger.warning("Run with --reindex to fix")
            return False
    else:
        logger.warning("⚠️  metadata.parquet not found")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Reindex Parquet metadata'
    )
    parser.add_argument(
        '--data-dir',
        type=str,
        default='data/parquet',
        help='Directory containing Parquet files'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify counts without reindexing'
    )
    parser.add_argument(
        '--reindex',
        action='store_true',
        help='Force reindex (recreate metadata.parquet)'
    )
    
    args = parser.parse_args()
    
    data_dir = Path(args.data_dir)
    
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        return
    
    if args.verify:
        # Just verify counts
        verify_counts(data_dir)
    elif args.reindex:
        # Force reindex
        reindex_metadata(data_dir)
        logger.info("\nVerifying new metadata...")
        verify_counts(data_dir)
    else:
        # Default: verify first, offer to reindex if needed
        if not verify_counts(data_dir):
            response = input("\nReindex now? (y/n): ")
            if response.lower() == 'y':
                reindex_metadata(data_dir)
                verify_counts(data_dir)


if __name__ == "__main__":
    main()

