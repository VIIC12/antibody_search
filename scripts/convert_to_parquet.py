#!/usr/bin/env python
"""
Convert OAS CSV.gz files to optimized Parquet format (data/parquet/). Gets called by update_from_oas.py.

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
from typing import Dict, Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import os
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def extract_metadata(filepath: Path) -> Dict[str, Any]:
    """Extract JSON metadata from first line of CSV.gz file."""
    try:
        with gzip.open(filepath, "rt", encoding="utf-8") as f:
            header_line = f.readline()
            # Clean up the header format
            header_cleaned = (
                header_line.replace('"{', "{").replace('}"', "}").replace('""', '"')
            )
            metadata = json.loads(header_cleaned)
            return metadata
    except Exception as e:
        logger.error(f"Failed to extract metadata from {filepath}: {e}")
        return {}


def calculate_identity_percentage(sequence: str, germline: str) -> float:
    """
    Calculate percentage identity between sequence and germline (reference).
    The germline sequence is the reference (100% identity), any changes represent mutations.
    
    Args:
        sequence: The actual sequence (e.g., v_sequence_alignment_aa)
        germline: The germline reference sequence (e.g., v_germline_alignment_aa)
    
    Returns:
        Percentage identity (0-100) based on the germline sequence length, rounded to 2 decimal places
    """
    # Check if both are empty/NaN - return NaN
    seq_empty = pd.isna(sequence) or sequence == ""
    germline_empty = pd.isna(germline) or germline == ""
    
    if seq_empty and germline_empty:
        return float('nan')
    
    # Check if only one is empty - this should not happen, return error
    if seq_empty or germline_empty:
        raise ValueError(f"Only one sequence is empty: sequence_empty={seq_empty}, germline_empty={germline_empty}")
    
    # Remove gaps and convert to uppercase for comparison
    sequence_clean = sequence.replace('-', '').replace('.', '').upper()
    germline_clean = germline.replace('-', '').replace('.', '').upper()
    
    # If either sequence is empty after cleaning, return 0
    if len(sequence_clean) == 0 or len(germline_clean) == 0:
        return 0.0
    
    # Use the germline sequence length as the reference (100%)
    germline_length = len(germline_clean)
    
    # Count identical positions up to the germline sequence length
    # If sequence is shorter, missing positions count as differences
    identical = sum(1 for i, germline_char in enumerate(germline_clean) 
                   if i < len(sequence_clean) and sequence_clean[i] == germline_char)
    
    # Calculate percentage based on the germline sequence length and round to 2 decimal places
    percentage = (identical / germline_length) * 100
    return round(percentage, 2)


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
    if chain_type_lower == "paired":
        # Define columns by extraction level for paired data
        basic_columns = [
            # Heavy chain basic columns
            "v_call_heavy",
            "d_call_heavy",
            "j_call_heavy",
            "sequence_alignment_aa_heavy",
            "v_sequence_alignment_aa_heavy",
            "d_sequence_alignment_aa_heavy",
            "j_sequence_alignment_aa_heavy",
            "v_germline_alignment_aa_heavy",
            "d_germline_alignment_aa_heavy",
            "j_germline_alignment_aa_heavy",
            "cdr1_aa_heavy",
            "cdr2_aa_heavy",
            "cdr3_aa_heavy",
            # Light chain basic columns
            "v_call_light",
            "d_call_light",
            "j_call_light",
            "sequence_alignment_aa_light",
            "v_sequence_alignment_aa_light",
            "d_sequence_alignment_aa_light",
            "j_sequence_alignment_aa_light",
            "v_germline_alignment_aa_light",
            "d_germline_alignment_aa_light",
            "j_germline_alignment_aa_light",
            "cdr1_aa_light",
            "cdr2_aa_light",
            "cdr3_aa_light"
        ]

        additional_columns = [
            # Heavy chain additional columns
            "sequence_alignment_heavy",
            "v_sequence_alignment_heavy",
            "d_sequence_alignment_heavy",
            "j_sequence_alignment_heavy",
            "cdr1_heavy",
            "cdr2_heavy",
            "cdr3_heavy",
            "v_identity_heavy", # How sure is the V gene call?
            "d_identity_heavy", # How sure is the D gene call?
            "j_identity_heavy", # How sure is the J gene call?
            # Light chain additional columns
            "sequence_alignment_light",
            "v_sequence_alignment_light",
            "d_sequence_alignment_light",
            "j_sequence_alignment_light",
            "cdr1_light",
            "cdr2_light",
            "cdr3_light",
            "v_identity_light",
            "d_identity_light",
            "j_identity_light",
        ]

        full_columns = [
            # Heavy chain full columns
            "sequence_heavy",
            "fwr1_heavy",
            "fwr1_aa_heavy",
            "fwr2_heavy",
            "fwr2_aa_heavy",
            "fwr3_heavy",
            "fwr3_aa_heavy",
            "junction_heavy",
            "junction_length_heavy",
            "junction_aa_heavy",
            "junction_aa_length_heavy",
            "v_score_heavy",
            "d_score_heavy",
            "j_score_heavy",
            # Light chain full columns
            "sequence_light",
            "fwr1_light",
            "fwr1_aa_light",
            "fwr2_light",
            "fwr2_aa_light",
            "fwr3_light",
            "fwr3_aa_light",
            "junction_light",
            "junction_length_light",
            "junction_aa_light",
            "junction_aa_length_light",
            "v_score_light",
            "d_score_light",
            "j_score_light",
        ]

        # Combine columns based on extraction level
        columns = basic_columns.copy()
        if extraction_level >= 2:
            columns.extend(additional_columns)
        if extraction_level >= 3:
            columns.extend(full_columns)

        return columns

    # Unpaired data: single chain with extraction levels
    elif chain_type_lower == "heavy":
        # Define columns by extraction level for Heavy chain
        basic_columns = [
            "v_call",
            "d_call",
            "j_call",
            "sequence_alignment_aa",
            "v_sequence_alignment_aa",
            "d_sequence_alignment_aa",
            "j_sequence_alignment_aa",
            "v_germline_alignment_aa",
            "d_germline_alignment_aa",
            "j_germline_alignment_aa",
            "cdr1_aa",
            "cdr2_aa",
            "cdr3_aa",
        ]

        additional_columns = [
            "sequence_alignment",
            "v_sequence_alignment",
            "d_sequence_alignment",
            "j_sequence_alignment",
            "cdr1",
            "cdr2",
            "cdr3",
            "v_identity",
            "d_identity",
            "j_identity",
        ]

        full_columns = [
            "sequence",
            "fwr2",
            "fwr2_aa",
            "fwr3",
            "fwr3_aa",
            "fwr4",
            "fwr4_aa",
            "v_score",
            "d_score",
            "j_score",
        ]

        # Combine columns based on extraction level
        columns = basic_columns.copy()
        if extraction_level >= 2:
            columns.extend(additional_columns)
        if extraction_level >= 3:
            columns.extend(full_columns)

        return columns

    elif chain_type_lower == "light":
        # Define columns by extraction level for Light chain (identical to Heavy)
        basic_columns = [
            "v_call",
            "d_call",
            "j_call",
            "sequence_alignment_aa",
            "v_sequence_alignment_aa",
            "d_sequence_alignment_aa",
            "j_sequence_alignment_aa",
            "v_germline_alignment_aa",
            "d_germline_alignment_aa",
            "j_germline_alignment_aa",
            "cdr1_aa",
            "cdr2_aa",
            "cdr3_aa",
        ]

        additional_columns = [
            "sequence_alignment",
            "v_sequence_alignment",
            "d_sequence_alignment",
            "j_sequence_alignment",
            "cdr1",
            "cdr2",
            "cdr3",
            "v_identity",
            "d_identity",
            "j_identity",
        ]

        full_columns = [
            "sequence",
            "fwr2",
            "fwr2_aa",
            "fwr3",
            "fwr3_aa",
            "fwr4",
            "fwr4_aa",
            "v_score",
            "d_score",
            "j_score",
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
        raise ValueError(
            f"Invalid chain type: '{chain_type}'. Expected 'Paired', 'Heavy', or 'Light'"
        )


def convert_file(
    input_path: Path, output_dir: Path, extraction_level: int = 1
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
    chain_type = metadata.get("Chain", "Unknown")
    if chain_type == "Unknown":
        logger.error(f"No 'Chain' field found in metadata for {input_path}")
        return {"filename": input_path.name, "error": "No Chain field in metadata"}
    
    # Convert to lowercase for comparison
    chain_type_lower = chain_type.lower()

    # Determine columns to keep based on chain type and extraction level
    try:
        columns = get_columns_for_chain(chain_type, extraction_level)
        logger.debug(
            f"Auto-detected columns for chain type '{chain_type}' (level {extraction_level}): {len(columns)} columns"
        )
    except ValueError as e:
        logger.error(f"Invalid chain type in metadata for {input_path}: {e}")
        return {"filename": input_path.name, "error": str(e)}

    # Read CSV data (skip first line with metadata)
    try:
        # Read specified columns
        df = pd.read_csv(
            input_path,
            skiprows=1,
            usecols=lambda col: col in columns,
            compression="gzip",
        )

        # Calculate CDR lengths from amino acid sequences
        # Handle both unpaired and paired data
        # -> cdr1_length, cdr1_lengt_hevy, cdr1_length_light
        for col in df.columns:
            if col.endswith("_aa") and "cdr" in col:
                length_col = col.replace("_aa", "_length")
                df[length_col] = df[col].fillna("").str.len()

        # Calculate percentage identity for V, D, J gene alignments (%SHM)
        if chain_type_lower == "paired":
            # Paired data: calculate for both heavy and light chains
            # Heavy chain %SHM calculations
            try:
                df["v_%SHM_heavy"] = df.apply(
                    lambda row: calculate_identity_percentage(
                        row["v_sequence_alignment_aa_heavy"], 
                        row["v_germline_alignment_aa_heavy"]
                    ), axis=1
                )
            except ValueError as e:
                logger.error(f"Error calculating v_%SHM_heavy: {e}")
                df["v_%SHM_heavy"] = float('nan')
            
            try:
                df["d_%SHM_heavy"] = df.apply(
                    lambda row: calculate_identity_percentage(
                        row["d_sequence_alignment_aa_heavy"], 
                        row["d_germline_alignment_aa_heavy"]
                    ), axis=1
                )
            except ValueError as e:
                logger.error(f"Error calculating d_%SHM_heavy: {e}")
                df["d_%SHM_heavy"] = float('nan')
            
            try:
                df["j_%SHM_heavy"] = df.apply(
                    lambda row: calculate_identity_percentage(
                        row["j_sequence_alignment_aa_heavy"], 
                        row["j_germline_alignment_aa_heavy"]
                    ), axis=1
                )
            except ValueError as e:
                logger.error(f"Error calculating j_%SHM_heavy: {e}")
                df["j_%SHM_heavy"] = float('nan')
            
            # Light chain %SHM calculations
            try:
                df["v_%SHM_light"] = df.apply(
                    lambda row: calculate_identity_percentage(
                        row["v_sequence_alignment_aa_light"], 
                        row["v_germline_alignment_aa_light"]
                    ), axis=1
                )
            except ValueError as e:
                logger.error(f"Error calculating v_%SHM_light: {e}")
                df["v_%SHM_light"] = float('nan')
            
            try:
                df["d_%SHM_light"] = df.apply(
                    lambda row: calculate_identity_percentage(
                        row["d_sequence_alignment_aa_light"], 
                        row["d_germline_alignment_aa_light"]
                    ), axis=1
                )
            except ValueError as e:
                logger.error(f"Error calculating d_%SHM_light: {e}")
                df["d_%SHM_light"] = float('nan')
            
            try:
                df["j_%SHM_light"] = df.apply(
                    lambda row: calculate_identity_percentage(
                        row["j_sequence_alignment_aa_light"], 
                        row["j_germline_alignment_aa_light"]
                    ), axis=1
                )
            except ValueError as e:
                logger.error(f"Error calculating j_%SHM_light: {e}")
                df["j_%SHM_light"] = float('nan')
        
        elif chain_type_lower in ["heavy", "light"]:
            # Unpaired data: calculate for single chain (heavy or light)
            try:
                df["v_%SHM"] = df.apply(
                    lambda row: calculate_identity_percentage(
                        row["v_sequence_alignment_aa"], 
                        row["v_germline_alignment_aa"]
                    ), axis=1
                )
            except ValueError as e:
                logger.error(f"Error calculating v_%SHM: {e}")
                df["v_%SHM"] = float('nan')
            
            try:
                df["d_%SHM"] = df.apply(
                    lambda row: calculate_identity_percentage(
                        row["d_sequence_alignment_aa"], 
                        row["d_germline_alignment_aa"]
                    ), axis=1
                )
            except ValueError as e:
                logger.error(f"Error calculating d_%SHM: {e}")
                df["d_%SHM"] = float('nan')
            
            try:
                df["j_%SHM"] = df.apply(
                    lambda row: calculate_identity_percentage(
                        row["j_sequence_alignment_aa"], 
                        row["j_germline_alignment_aa"]
                    ), axis=1
                )
            except ValueError as e:
                logger.error(f"Error calculating j_%SHM: {e}")
                df["j_%SHM"] = float('nan')
        
        else:
            # Invalid chain type
            raise ValueError(f"Invalid chain type: '{chain_type}'. Expected 'Paired', 'Heavy', or 'Light'")

        # Exclude columns that should not be in the data based on chain type
        # Light chains: exclude D-gene columns (always NaN)
        LIGHT_CHAIN_EXCLUDE_COLUMNS = [
            'd_call',
            'd_%SHM',
            'd_sequence_alignment_aa',
            'd_germline_alignment_aa'
        ]
        
        # Paired chains: exclude D-gene light chain columns (always NaN)
        PAIRED_CHAIN_EXCLUDE_COLUMNS = [
            'd_call_light',
            'd_%SHM_light',
            'd_sequence_alignment_aa_light',
            'd_germline_alignment_aa_light'
        ]
        
        if chain_type_lower == 'light':
            # Remove D-gene columns for Light chains
            columns_to_remove = [col for col in df.columns if col in LIGHT_CHAIN_EXCLUDE_COLUMNS]
            if columns_to_remove:
                df = df.drop(columns=columns_to_remove)
                logger.debug(f"  Removed D-gene columns for Light chain: {columns_to_remove}")
        elif chain_type_lower == 'paired':
            # Remove D-gene light chain columns for Paired chains
            columns_to_remove = [col for col in df.columns if col in PAIRED_CHAIN_EXCLUDE_COLUMNS]
            if columns_to_remove:
                df = df.drop(columns=columns_to_remove)
                logger.debug(f"  Removed D-gene light chain columns for Paired chain: {columns_to_remove}")

        # Prepare file-level metadata (NOT as data columns)
        # Extract metadata values and prepare for file-level storage
        file_metadata = {
            b'chain': str(chain_type).encode(),
            b'file_source': str(input_path.stem.replace('.csv', '') + '.csv').encode(),
            b'species': str(metadata.get("Species", "Unknown")).encode(),
            b'subject': str(metadata.get("Subject", "Unknown")).encode(),
            b'disease': str(metadata.get("Disease", "Unknown")).encode(),
            b'vaccine': str(metadata.get("Vaccine", "Unknown")).encode(),
            b'isotype': str(metadata.get("Isotype", "Unknown")).encode(),
            b'total_sequences': str(len(df)).encode(),  # Normalized as integer string
        }
        
        # Note: We do NOT include unique_sequences in file-level metadata (as per clean_parquet_metadata.py)

        # Create output directory based on chain_type and isotype (partitioning)
        isotype = metadata.get("Isotype", "Unknown")

        output_subdir = output_dir / chain_type / isotype
        output_subdir.mkdir(parents=True, exist_ok=True)

        # Output path, input is csv.gz remove .gz (input_path.stem) and .csv (.replace) -> .parquet
        output_path = output_subdir / f"{input_path.stem.replace('.csv', '.parquet')}"

        # Convert DataFrame to PyArrow table
        table = pa.Table.from_pandas(df)
        
        # Apply file-level metadata to schema
        new_schema = table.schema.with_metadata(file_metadata)
        table_with_metadata = table.replace_schema_metadata(new_schema.metadata)
        
        # Write to Parquet with optimal compression and file-level metadata
        pq.write_table(table_with_metadata, output_path, compression='zstd')

        stats = {
            "filename": input_path.name,
            "rows": len(df),
            "columns": len(df.columns),
            "input_size_mb": input_path.stat().st_size / (1024 * 1024),
            "output_size_mb": output_path.stat().st_size / (1024 * 1024),
            "compression_ratio": input_path.stat().st_size / output_path.stat().st_size,
            "metadata": metadata,
        }

        logger.info(
            f"  ✓ Converted: {stats['rows']:,} rows, "
            f"{stats['input_size_mb']:.1f}MB → {stats['output_size_mb']:.1f}MB "
            f"({stats['compression_ratio']:.1f}x)"
            f"({stats['metadata']})"
        )

        return stats

    except Exception as e:
        logger.error(f"Failed to convert {input_path}: {e}")
        return {"filename": input_path.name, "error": str(e)}


def extract_metadata_from_parquet_file(parquet_path: Path, output_dir: Path) -> Dict[str, Any]:
    """
    Extract metadata from a parquet file's file-level metadata.
    
    Args:
        parquet_path: Path to the parquet file
        output_dir: Base output directory (for calculating relative file_path)
    
    Returns:
        Dictionary with metadata fields
    """
    try:
        # Read file-level metadata
        table = pq.read_table(parquet_path)
        df = pd.read_parquet(parquet_path)
        
        # Extract file-level metadata
        file_metadata = {}
        if table.schema.metadata:
            for k, v in table.schema.metadata.items():
                if not k.startswith(b'pandas'):
                    file_metadata[k.decode()] = v.decode()
        
        # Calculate relative file path
        try:
            file_path = str(parquet_path.relative_to(output_dir))
        except ValueError:
            # Fall back to just the filename if relative path calculation fails
            file_path = parquet_path.name
        
        # Build metadata record (matching optimized structure)
        # Optimized metadata columns: file_path, chain, file_source, species, subject, 
        # disease, vaccine, isotype, total_sequences
        # Note: NO unique_sequences, filename, or rows columns
        record = {
            'file_path': file_path,
            'chain': file_metadata.get('chain', 'Unknown'),
            'file_source': file_metadata.get('file_source', 'Unknown'),
            'species': file_metadata.get('species', 'Unknown'),
            'subject': file_metadata.get('subject', 'Unknown'),
            'disease': file_metadata.get('disease', 'Unknown'),
            'vaccine': file_metadata.get('vaccine', 'Unknown'),
            'isotype': file_metadata.get('isotype', 'Unknown'),
            'total_sequences': len(df),
        }
        
        return record
        
    except Exception as e:
        logger.error(f"Failed to extract metadata from {parquet_path}: {e}")
        return {}


def create_metadata_table(stats_list: list, output_dir: Path):
    """
    Create/update metadata tables for each subdirectory containing Parquet files.
    
    This function:
    1. Scans all parquet files in each subdirectory
    2. Extracts metadata from file-level metadata (not data columns)
    3. Merges with existing metadata files if they exist
    4. Creates comprehensive metadata.parquet files
    """
    from collections import defaultdict
    
    # Group newly converted files by subdirectory
    converted_subdirs = defaultdict(set)
    for stats in stats_list:
        if "error" not in stats and "metadata" in stats:
            metadata = stats["metadata"]
            chain_type = metadata.get("Chain", "Unknown")
            isotype = metadata.get("Isotype", "Unknown")
            converted_subdirs[(chain_type, isotype)].add(
                stats["filename"].replace('.csv.gz', '.parquet')
            )
    
    # Process each subdirectory that has parquet files
    processed_subdirs = set()
    
    # First, process subdirectories with newly converted files
    for (chain_type, isotype), converted_files in converted_subdirs.items():
        subdir = output_dir / chain_type / isotype
        if not subdir.exists():
            continue
        
        metadata_path = subdir / "metadata.parquet"
        processed_subdirs.add((chain_type, isotype))
        
        # Find all parquet files in this subdirectory
        parquet_files = [f for f in subdir.glob("*.parquet") if f.name != "metadata.parquet"]
        
        if not parquet_files:
            continue
        
        logger.info(f"Updating metadata for {chain_type}/{isotype} ({len(parquet_files)} files)")
        
        # Extract metadata from all parquet files
        metadata_records = []
        for parquet_path in parquet_files:
            record = extract_metadata_from_parquet_file(parquet_path, output_dir)
            if record:
                metadata_records.append(record)
        
        if not metadata_records:
            logger.warning(f"  ⚠️  No valid metadata extracted for {subdir}")
            continue
        
        # Create DataFrame from metadata records
        new_df = pd.DataFrame(metadata_records)
        
        # Define the correct columns for optimized metadata
        # Matching structure: file_path, chain, file_source, species, subject, 
        # disease, vaccine, isotype, total_sequences
        # Note: NO unique_sequences, filename, or rows columns
        correct_columns = ['file_path', 'chain', 'file_source', 'species', 'subject', 
                          'disease', 'vaccine', 'isotype', 'total_sequences']
        
        # Load existing metadata if it exists and merge
        if metadata_path.exists():
            try:
                existing_df = pd.read_parquet(metadata_path)
                logger.info(f"  📂 Found existing metadata file with {len(existing_df)} entries")
                
                # Remove unwanted columns if they exist in existing metadata
                columns_to_remove = ['unique_sequences', 'filename', 'rows']
                existing_columns_to_remove = [col for col in columns_to_remove if col in existing_df.columns]
                if existing_columns_to_remove:
                    existing_df = existing_df.drop(columns=existing_columns_to_remove)
                    logger.debug(f"  🧹 Removed columns from existing metadata: {existing_columns_to_remove}")
                
                # Check for orphaned records: metadata entries referencing files that don't exist on disk
                if 'file_path' in existing_df.columns:
                    # Create set of actual parquet files that exist (by filename)
                    actual_parquet_filenames = {f.name for f in parquet_files}
                    
                    # Check which existing metadata records reference files that don't exist
                    orphaned_mask = []
                    for _, row in existing_df.iterrows():
                        file_path_str = str(row['file_path'])
                        # Extract filename from file_path (could be relative path like "Heavy/IGHA/file.parquet")
                        filename = Path(file_path_str).name
                        file_exists = filename in actual_parquet_filenames
                        orphaned_mask.append(not file_exists)
                    
                    orphaned_count = sum(orphaned_mask)
                    if orphaned_count > 0:
                        logger.info(f"  🗑️  Found {orphaned_count} orphaned metadata record(s) (referenced files no longer exist)")
                        # Filter out orphaned records from existing metadata
                        existing_df = existing_df[~pd.Series(orphaned_mask)]
                        logger.info(f"  ✅ Removed {orphaned_count} orphaned record(s) from metadata")
                
                # Merge with existing data, removing duplicates based on file_path
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                # Remove duplicates, keeping the last occurrence (most recent data)
                combined_df = combined_df.drop_duplicates(subset=['file_path'], keep='last')
                
                # Ensure only correct columns are present (in correct order)
                combined_df = combined_df[[col for col in correct_columns if col in combined_df.columns]]
                
                logger.info(f"  ✅ Updated metadata: {len(existing_df)} → {len(combined_df)} files")
                
            except Exception as e:
                logger.error(f"  ❌ Could not read existing metadata file: {e}")
                combined_df = new_df
                logger.info(f"  ✅ Created new metadata (old file was corrupted): {len(new_df)} files")
        else:
            combined_df = new_df
            logger.info(f"  ✅ Created new metadata file: {len(new_df)} files")
        
        # Ensure correct column order and remove any unwanted columns
        combined_df = combined_df[[col for col in correct_columns if col in combined_df.columns]]
        
        # Save the updated metadata
        try:
            combined_df.to_parquet(metadata_path, index=False)
            logger.info(f"  💾 Saved metadata to: {metadata_path}")
        except Exception as e:
            logger.error(f"  ❌ Could not save metadata file: {e}")
    
    # Also scan for any other subdirectories that might have parquet files but weren't converted
    # This ensures metadata is created for all subdirectories
    for chain_type_dir in output_dir.iterdir():
        if not chain_type_dir.is_dir():
            continue
        
        for isotype_dir in chain_type_dir.iterdir():
            if not isotype_dir.is_dir():
                continue
            
            subdir_key = (chain_type_dir.name, isotype_dir.name)
            if subdir_key in processed_subdirs:
                continue  # Already processed
            
            metadata_path = isotype_dir / "metadata.parquet"
            parquet_files = [f for f in isotype_dir.glob("*.parquet") if f.name != "metadata.parquet"]
            
            if not parquet_files:
                continue
            
            # Only create metadata if it doesn't exist (don't overwrite existing)
            if not metadata_path.exists():
                logger.info(f"Creating metadata for {chain_type_dir.name}/{isotype_dir.name} ({len(parquet_files)} files)")
                
                metadata_records = []
                for parquet_path in parquet_files:
                    record = extract_metadata_from_parquet_file(parquet_path, output_dir)
                    if record:
                        metadata_records.append(record)
                
                if metadata_records:
                    metadata_df = pd.DataFrame(metadata_records)
                    # Ensure correct column order (matching optimized structure)
                    correct_columns = ['file_path', 'chain', 'file_source', 'species', 'subject', 
                                      'disease', 'vaccine', 'isotype', 'total_sequences']
                    metadata_df = metadata_df[[col for col in correct_columns if col in metadata_df.columns]]
                    metadata_df.to_parquet(metadata_path, index=False)
                    logger.info(f"  💾 Created metadata: {metadata_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert OAS CSV.gz files to Parquet format"
    )
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Input directory containing CSV.gz files, or path to CSV.gz files",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help='Output directory for Parquet files. If not specified, creates a "converted/" subdirectory in the input directory.',
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of files to convert (for testing)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=os.cpu_count(),
        help="Number of jobs to run in parallel, defaults to all available cores",
    )
    parser.add_argument(
        "--extraction-level",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="Extraction level for paired data: 1=Basic (default), 2=+Additional, 3=+Full",
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
        if input_path.suffix == ".gz" and input_path.stem.endswith(".csv"):
            csv_files = [input_path]
        else:
            logger.error(f"File must be a .csv.gz file: {input_path}")
            return
    elif input_path.is_dir():
        # Directory provided - find all CSV.gz files
        csv_files = sorted(input_path.glob("*.csv.gz"))
    else:
        logger.error(f"Input path not found: {input_path}")
        return

    if not csv_files:
        logger.error(f"No CSV.gz files found in {input_path}")
        return

    # Limit files if specified
    if args.limit:
        csv_files = csv_files[: args.limit]

    logger.info(f"Found {len(csv_files)} files to convert")
    logger.info(f"Output directory: {output_dir.absolute()}")

    # Convert files in parallel
    logger.info(f"Converting files in parallel using {os.cpu_count()} cores")
    logger.info(f"Extraction level: {args.extraction_level}")
    stats_list = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        future_to_file = {
            executor.submit(
                convert_file, filepath, output_dir, args.extraction_level
            ): filepath
            for filepath in csv_files
        }
        for future in tqdm(
            as_completed(future_to_file), total=len(csv_files), desc="Converting files"
        ):
            try:
                stats = future.result()
                stats_list.append(stats)
            except Exception as exc:
                stats_list.append(
                    {"filename": str(future_to_file[future]), "error": str(exc)}
                )

    # Create metadata table from all converted files
    create_metadata_table(stats_list, output_dir)

    # Summary statistics
    successful = [s for s in stats_list if "error" not in s]
    failed = [s for s in stats_list if "error" in s]

    total_input_mb = sum(s["input_size_mb"] for s in successful)
    total_output_mb = sum(s["output_size_mb"] for s in successful)
    total_rows = sum(s["rows"] for s in successful)

    logger.info("\n" + "=" * 60)
    logger.info("CONVERSION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total files processed: {len(csv_files)}")
    logger.info(f"  ✓ Successful: {len(successful)}")
    logger.info(f"  ✗ Failed: {len(failed)}")
    logger.info(f"Total rows: {total_rows:,}")
    logger.info(f"Total input size: {total_input_mb:.1f} MB")
    logger.info(f"Total output size: {total_output_mb:.1f} MB")
    logger.info(f"Overall compression: {total_input_mb/total_output_mb:.1f}x")
    logger.info("=" * 60)

    if failed:
        logger.warning("\nFailed files:")
        for s in failed:
            logger.warning(f"  - {s['filename']}: {s['error']}")


if __name__ == "__main__":
    main()
