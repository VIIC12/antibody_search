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


def get_columns_for_chain(chain_type: str, extraction_level: int = 1) -> list:
    """
    Determine which columns to extract based on chain type from metadata and extraction level.
    
    Args:
        chain_type: Chain type from metadata ('Paired', 'Heavy', 'Light')
        extraction_level: Extraction level (1=Basic, 2=+Additional, 3=+Full)
        
    Returns:
        List of column names to keep
    """
    chain_type_lower = chain_type.lower()
    
    # Check if this is paired data (contains both heavy and light chain columns)
    if chain_type_lower == 'paired':
        # Define columns by extraction level for paired data
        basic_columns = [
            # Heavy chain basic columns
            'v_call_heavy', 'd_call_heavy', 'j_call_heavy',
            'sequence_alignment_aa_heavy', 'v_sequence_alignment_aa_heavy', 
            'd_sequence_alignment_aa_heavy', 'j_sequence_alignment_aa_heavy',
            'cdr1_aa_heavy', 'cdr2_aa_heavy', 'cdr3_aa_heavy',
            'v_identity_heavy', 'd_identity_heavy', 'j_identity_heavy',
            # Light chain basic columns
            'v_call_light', 'd_call_light', 'j_call_light',
            'sequence_alignment_aa_light', 'v_sequence_alignment_aa_light',
            'd_sequence_alignment_aa_light', 'j_sequence_alignment_aa_light',
            'cdr1_aa_light', 'cdr2_aa_light', 'cdr3_aa_light',
            'v_identity_light', 'd_identity_light', 'j_identity_light'
        ]
        
        additional_columns = [
            # Heavy chain additional columns
            'sequence_alignment_heavy', 'v_sequence_alignment_heavy',
            'd_sequence_alignment_heavy', 'j_sequence_alignment_heavy',
            'cdr1_heavy', 'cdr2_heavy', 'cdr3_heavy',
            # Light chain additional columns
            'sequence_alignment_light', 'v_sequence_alignment_light',
            'd_sequence_alignment_light', 'j_sequence_alignment_light',
            'cdr1_light', 'cdr2_light', 'cdr3_light'
        ]
        
        full_columns = [
            # Heavy chain full columns
            'sequence_heavy', 'fwr1_heavy', 'fwr1_aa_heavy', 'fwr2_heavy', 'fwr2_aa_heavy',
            'fwr3_heavy', 'fwr3_aa_heavy', 'junction_heavy', 'junction_length_heavy',
            'junction_aa_heavy', 'junction_aa_length_heavy', 'v_score_heavy',
            'd_score_heavy', 'j_score_heavy',
            # Light chain full columns
            'sequence_light', 'fwr1_light', 'fwr1_aa_light', 'fwr2_light', 'fwr2_aa_light',
            'fwr3_light', 'fwr3_aa_light', 'junction_light', 'junction_length_light',
            'junction_aa_light', 'junction_aa_length_light', 'v_score_light',
            'd_score_light', 'j_score_light'
        ]
        
        # Combine columns based on extraction level
        columns = basic_columns.copy()
        if extraction_level >= 2:
            columns.extend(additional_columns)
        if extraction_level >= 3:
            columns.extend(full_columns)
            
        return columns
    
    # Unpaired data: single chain with extraction levels
    elif chain_type_lower == 'heavy':
        # Define columns by extraction level for Heavy chain
        basic_columns = [
            'v_call', 'd_call', 'j_call',
            'sequence_alignment_aa', 'v_sequence_alignment_aa', 
            'd_sequence_alignment_aa', 'j_sequence_alignment_aa',
            'cdr1_aa', 'cdr2_aa', 'cdr3_aa'
        ]
        
        additional_columns = [
            'sequence_alignment', 'v_sequence_alignment',
            'd_sequence_alignment', 'j_sequence_alignment',
            'cdr1', 'cdr2', 'cdr3',
            'v_identity', 'd_identity', 'j_identity'
        ]
        
        full_columns = [
            'sequence', 'fwr2', 'fwr2_aa', 'fwr3', 'fwr3_aa',
            'fwr4', 'fwr4_aa', 'v_score', 'd_score', 'j_score'
        ]
        
        # Combine columns based on extraction level
        columns = basic_columns.copy()
        if extraction_level >= 2:
            columns.extend(additional_columns)
        if extraction_level >= 3:
            columns.extend(full_columns)
            
        return columns
    
    elif chain_type_lower == 'light':
        # Define columns by extraction level for Light chain (identical to Heavy)
        basic_columns = [
            'v_call', 'd_call', 'j_call',
            'sequence_alignment_aa', 'v_sequence_alignment_aa', 
            'd_sequence_alignment_aa', 'j_sequence_alignment_aa',
            'cdr1_aa', 'cdr2_aa', 'cdr3_aa'
        ]
        
        additional_columns = [
            'sequence_alignment', 'v_sequence_alignment',
            'd_sequence_alignment', 'j_sequence_alignment',
            'cdr1', 'cdr2', 'cdr3',
            'v_identity', 'd_identity', 'j_identity'
        ]
        
        full_columns = [
            'sequence', 'fwr2', 'fwr2_aa', 'fwr3', 'fwr3_aa',
            'fwr4', 'fwr4_aa', 'v_score', 'd_score', 'j_score'
        ]
        
        # Combine columns based on extraction level
        columns = basic_columns.copy()
        if extraction_level >= 2:
            columns.extend(additional_columns)
        if extraction_level >= 3:
            columns.extend(full_columns)
            
        return columns
    
    # Invalid chain type
    else:
        raise ValueError(f"Invalid chain type: '{chain_type}'. Expected 'Paired', 'Heavy', or 'Light'")


def convert_file(
    input_path: Path,
    output_dir: Path,
    extraction_level: int = 1
) -> Dict[str, Any]:
    """
    Convert single CSV.gz file to Parquet.
    
    Args:
        input_path: Path to input CSV.gz file
        output_dir: Directory for output Parquet files
        extraction_level: Extraction level (1=Basic, 2=+Additional, 3=+Full)
    
    Returns:
        Dictionary with conversion statistics
    """
    logger.info(f"Processing: {input_path.name}")
    
    # Extract metadata
    metadata = extract_metadata(input_path)
    
    # Get chain type from metadata
    chain_type = metadata.get('Chain', 'Unknown')
    if chain_type == 'Unknown':
        logger.error(f"No 'Chain' field found in metadata for {input_path}")
        return {'filename': input_path.name, 'error': 'No Chain field in metadata'}
    
    # Determine columns to keep based on chain type and extraction level
    try:
        columns = get_columns_for_chain(chain_type, extraction_level)
        logger.debug(f"Auto-detected columns for chain type '{chain_type}' (level {extraction_level}): {len(columns)} columns")
    except ValueError as e:
        logger.error(f"Invalid chain type in metadata for {input_path}: {e}")
        return {'filename': input_path.name, 'error': str(e)}
    
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
        # Handle both unpaired and paired data
        for col in df.columns:
            if col.endswith('_aa') and 'cdr' in col:
                length_col = col.replace('_aa', '_length')
                df[length_col] = df[col].fillna('').str.len()
        
        # Add metadata as columns
        df['file_source'] = input_path.stem
        df['subject'] = metadata.get('Subject', 'Unknown')
        df['isotype'] = metadata.get('Isotype', 'Unknown')
        df['disease'] = metadata.get('Disease', 'Unknown')
        df['species'] = metadata.get('Species', 'Unknown')
        # Use chain type from metadata
        df['chain'] = chain_type
        
        # Create output directory based on isotype (partitioning)
        isotype = metadata.get('Isotype', 'Unknown')
        output_subdir = output_dir / isotype
        output_subdir.mkdir(parents=True, exist_ok=True)
        
        # Output path, input is csv.gz remove .gz and .csv
        output_path = output_subdir / f"{input_path.stem.replace('.csv.gz', '.parquet')}"
        
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
        
        # Create single metadata file in the output directory root
        metadata_path = output_dir / 'metadata.parquet'
        metadata_df.to_parquet(metadata_path, index=False)
        logger.info(f"Created metadata table: {metadata_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Convert OAS CSV.gz files to Parquet format'
    )
    parser.add_argument(
        '--input',
        type=str,
        required=True,
        help='Input directory containing CSV.gz files, or path to CSV.gz files'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output directory for Parquet files. If not specified, creates a "converted/" subdirectory in the input directory.'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of files to convert (for testing)'
    )
    parser.add_argument(
        '-j',
        '--jobs',
        type=int,
        default=os.cpu_count(),
        help='Number of jobs to run in parallel, defaults to all available cores'
    )
    parser.add_argument(
        '--extraction-level',
        type=int,
        choices=[1, 2, 3],
        default=1,
        help='Extraction level for paired data: 1=Basic (default), 2=+Additional, 3=+Full'
    )
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    
    # Determine output directory
    if args.output is not None:
        # Output directory explicitly specified
        output_dir = Path(args.output)
    else:
        # No output specified - create converted/ subdirectory in input directory
        if input_path.is_file():
            # Single file - use parent directory
            output_dir = input_path.parent / "converted"
        else:
            # Directory - use same directory
            output_dir = input_path / "converted"
    
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
    logger.info(f"Extraction level: {args.extraction_level}")
    stats_list = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        future_to_file = {
            executor.submit(convert_file, filepath, output_dir, args.extraction_level): filepath
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

