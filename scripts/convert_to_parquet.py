#!/usr/bin/env python
"""
Convert OAS CSV.gz files to optimized Parquet format.

This script:
1. Reads CSV.gz files with JSON metadata header
2. Extracts metadata into separate table
3. Converts to Parquet with optimal settings
4. Creates partitioned structure by Isotype
"""

import argparse
import gzip
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import os
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_metadata(filepath: Path) -> Dict[str, Any]:
    """Extract JSON metadata from first line of CSV.gz file."""
    try:
        with gzip.open(filepath, 'rt', encoding='utf-8') as f:
            header_line = f.readline()
            # Clean up the header format
            header_cleaned = (
                header_line
                .replace('"{', '{')
                .replace('}"', '}')
                .replace('""', '"')
            )
            metadata = json.loads(header_cleaned)
            return metadata
    except Exception as e:
        logger.error(f"Failed to extract metadata from {filepath}: {e}")
        return {}


def get_columns_for_chain(filename: str) -> list:
    """
    Determine which columns to extract based on chain type.
    
    Args:
        filename: Name of the CSV.gz file
        
    Returns:
        List of column names to keep
    """
    filename_lower = filename.lower()
    
    # Base columns for all chains
    base_columns = ['v_call', 'd_call', 'j_call']
    
    # Heavy chain specific
    if 'heavy' in filename_lower:
        return base_columns + ['cdr1_aa', 'cdr2_aa', 'cdr3_aa']
    
    # Light chain (future support)
    elif 'light' in filename_lower or 'lambda' in filename_lower or 'kappa' in filename_lower:
        # Light chains use different CDR naming
        return base_columns + ['cdr1_aa', 'cdr2_aa', 'cdr3_aa']
    
    # Default: include all CDR columns
    else:
        return base_columns + ['cdr1_aa', 'cdr2_aa', 'cdr3_aa']


def convert_file(
    input_path: Path,
    output_dir: Path,
    columns: Optional[list] = None
) -> Dict[str, Any]:
    """
    Convert single CSV.gz file to Parquet.
    
    Args:
        input_path: Path to input CSV.gz file
        output_dir: Directory for output Parquet files
        columns: Specific columns to keep (None = auto-detect)
    
    Returns:
        Dictionary with conversion statistics
    """
    logger.info(f"Processing: {input_path.name}")
    
    # Extract metadata
    metadata = extract_metadata(input_path)
    
    # Determine columns to keep
    if columns is None:
        columns = get_columns_for_chain(input_path.name)
        logger.debug(f"Auto-detected columns: {columns}")
    
    # Read CSV data (skip first line with metadata)
    try:
        # Read specified columns
        df = pd.read_csv(
            input_path,
            skiprows=1,
            usecols=lambda col: col in columns,
            compression='gzip'
        )
        
        # Calculate CDR lengths from amino acid sequences
        if 'cdr1_aa' in df.columns:
            df['cdr1_length'] = df['cdr1_aa'].fillna('').str.len()
        if 'cdr2_aa' in df.columns:
            df['cdr2_length'] = df['cdr2_aa'].fillna('').str.len()
        if 'cdr3_aa' in df.columns:
            df['cdr3_length'] = df['cdr3_aa'].fillna('').str.len()
        
        # Add metadata as columns
        df['file_source'] = input_path.stem
        df['subject'] = metadata.get('Subject', 'Unknown')
        df['isotype'] = metadata.get('Isotype', 'Unknown')
        df['disease'] = metadata.get('Disease', 'Unknown')
        df['species'] = metadata.get('Species', 'Unknown')
        df['chain'] = 'Heavy' if 'heavy' in input_path.name.lower() else 'Light' if 'light' in input_path.name.lower() else 'Unknown'
        
        # Create output directory based on isotype (partitioning)
        isotype = metadata.get('Isotype', 'Unknown')
        output_subdir = output_dir / isotype
        output_subdir.mkdir(parents=True, exist_ok=True)
        
        # Output path
        output_path = output_subdir / f"{input_path.stem}.parquet"
        
        # Write to Parquet with optimal compression
        df.to_parquet(
            output_path,
            engine='pyarrow',
            compression='zstd',  # Better compression than gzip
            index=False
        )
        
        stats = {
            'filename': input_path.name,
            'rows': len(df),
            'columns': len(df.columns),
            'input_size_mb': input_path.stat().st_size / (1024 * 1024),
            'output_size_mb': output_path.stat().st_size / (1024 * 1024),
            'compression_ratio': input_path.stat().st_size / output_path.stat().st_size,
            'metadata': metadata
        }
        
        logger.info(
            f"  ✓ Converted: {stats['rows']:,} rows, "
            f"{stats['input_size_mb']:.1f}MB → {stats['output_size_mb']:.1f}MB "
            f"({stats['compression_ratio']:.1f}x)"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"Failed to convert {input_path}: {e}")
        return {'filename': input_path.name, 'error': str(e)}


def create_metadata_table(stats_list: list, output_dir: Path):
    """Create a metadata table from all converted files."""
    metadata_records = []
    
    for stats in stats_list:
        if 'error' not in stats and 'metadata' in stats:
            record = {
                'filename': stats['filename'],
                'rows': stats['rows'],
                'subject': stats['metadata'].get('Subject'),
                'isotype': stats['metadata'].get('Isotype'),
                'disease': stats['metadata'].get('Disease'),
                'species': stats['metadata'].get('Species'),
                'unique_sequences': stats['metadata'].get('Unique sequences'),
                'total_sequences': stats['metadata'].get('Total sequences'),
            }
            metadata_records.append(record)
    
    if metadata_records:
        metadata_df = pd.DataFrame(metadata_records)
        
        # Group by isotype and create metadata files in each subdirectory
        for isotype, group_df in metadata_df.groupby('isotype'):
            isotype_dir = output_dir / isotype
            isotype_dir.mkdir(parents=True, exist_ok=True)
            metadata_path = isotype_dir / 'metadata.parquet'
            group_df.to_parquet(metadata_path, index=False)
            logger.info(f"Created metadata table for {isotype}: {metadata_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Convert OAS CSV.gz files to Parquet format'
    )
    parser.add_argument(
        '--input',
        type=str,
        required=True,
        help='Input directory containing CSV.gz files, or path to a single CSV.gz file'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/parquet',
        help='Output directory for Parquet files (relative to V3.0/)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of files to convert (for testing)'
    )
    parser.add_argument(
        '--columns',
        type=str,
        nargs='+',
        default=None,
        help='Columns to keep (default: auto-detect based on chain type)'
    )
    parser.add_argument(
        '-j',
        '--jobs',
        type=int,
        default=os.cpu_count(),
        help='Number of jobs to run in parallel, defaults to all available cores'
    )
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Handle both file and directory input
    if input_path.is_file():
        # Single file provided
        if input_path.suffix == '.gz' and input_path.stem.endswith('.csv'):
            csv_files = [input_path]
        else:
            logger.error(f"File must be a .csv.gz file: {input_path}")
            return
    elif input_path.is_dir():
        # Directory provided - find all CSV.gz files
        csv_files = sorted(input_path.glob('*.csv.gz'))
    else:
        logger.error(f"Input path not found: {input_path}")
        return
    
    if not csv_files:
        logger.error(f"No CSV.gz files found in {input_path}")
        return
    
    # Limit files if specified
    if args.limit:
        csv_files = csv_files[:args.limit]
    
    logger.info(f"Found {len(csv_files)} files to convert")
    logger.info(f"Output directory: {output_dir.absolute()}")
   
   
    # Convert files in parallel
    logger.info(f"Converting files in parallel using {os.cpu_count()} cores")
    stats_list = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        future_to_file = {
            executor.submit(convert_file, filepath, output_dir, args.columns): filepath
            for filepath in csv_files
        }
        for future in tqdm(as_completed(future_to_file), total=len(csv_files), desc="Converting files"):
            try:
                stats = future.result()
                stats_list.append(stats)
            except Exception as exc:
                stats_list.append({
                    'filename': str(future_to_file[future]),
                    'error': str(exc)
                })
    
    # Create metadata table
    create_metadata_table(stats_list, output_dir)
    
    # Summary statistics
    successful = [s for s in stats_list if 'error' not in s]
    failed = [s for s in stats_list if 'error' in s]
    
    total_input_mb = sum(s['input_size_mb'] for s in successful)
    total_output_mb = sum(s['output_size_mb'] for s in successful)
    total_rows = sum(s['rows'] for s in successful)
    
    logger.info("\n" + "="*60)
    logger.info("CONVERSION SUMMARY")
    logger.info("="*60)
    logger.info(f"Total files processed: {len(csv_files)}")
    logger.info(f"  ✓ Successful: {len(successful)}")
    logger.info(f"  ✗ Failed: {len(failed)}")
    logger.info(f"Total rows: {total_rows:,}")
    logger.info(f"Total input size: {total_input_mb:.1f} MB")
    logger.info(f"Total output size: {total_output_mb:.1f} MB")
    logger.info(f"Overall compression: {total_input_mb/total_output_mb:.1f}x")
    logger.info("="*60)
    
    if failed:
        logger.warning("\nFailed files:")
        for s in failed:
            logger.warning(f"  - {s['filename']}: {s['error']}")


if __name__ == "__main__":
    main()

