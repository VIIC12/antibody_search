#!/usr/bin/env python
"""
Reindex metadata after adding/removing Parquet files per subdirectory.

This script:
1. Scans all subdirectories containing Parquet files
2. Reads their file-level metadata (added by add_parquet_metadata.py)
3. Creates/updates metadata.parquet in each subdirectory
4. Verifies counts match between actual files and metadata

The metadata.parquet file contains:
- file_path: Relative path (chain/isotype/filename)
- chain: Chain type (Light/Heavy/Paired)
- file_source: Original file source
- species: Species
- subject: Subject ID
- disease: Disease information
- vaccine: Vaccine information
- isotype: Isotype (IGHG, IGHM, Bulk, etc.)
- total_sequences: Total sequence count (as int)

Use this when you:
- Delete Parquet files from subdirectories
- Add new Parquet files manually to subdirectories
- Metadata.parquet gets corrupted in subdirectories
- Want to verify counts per subdirectory

This works per subdirectory, creating one metadata.parquet file per directory
where Parquet files are located.
"""

import argparse
import logging
import sys
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_file_metadata(parquet_file: Path) -> dict:
    """
    Extract metadata from a Parquet file's file-level metadata.
    
    Reads the file-level metadata that was added by add_parquet_metadata.py.
    This metadata includes:
    - chain
    - file_source
    - species
    - subject
    - disease
    - vaccine
    - isotype
    - total_sequences
    
    Args:
        parquet_file: Path to Parquet file
    
    Returns:
        Dictionary with metadata or None if failed
    """
    try:
        # Read Parquet file to access file-level metadata
        parquet_file_obj = pq.ParquetFile(parquet_file)
        table = parquet_file_obj.read()
        
        # Get row count
        num_rows = table.num_rows
        
        # Extract metadata from file-level schema metadata
        metadata = {}
        if table.schema.metadata:
            for key, value in table.schema.metadata.items():
                # Skip pandas metadata
                if not key.startswith(b'pandas'):
                    try:
                        metadata[key.decode()] = value.decode()
                    except (UnicodeDecodeError, AttributeError):
                        # If decoding fails, try to convert to string
                        try:
                            metadata[key.decode()] = str(value)
                        except:
                            pass
        
        # Required metadata fields (must be present in file-level metadata)
        REQUIRED_METADATA_FIELDS = [
            'chain',
            'file_source',
            'species',
            'subject',
            'disease',
            'vaccine',
            'isotype',
            'total_sequences'
        ]
        
        # Check if file-level metadata exists
        if not metadata:
            raise ValueError(f"{parquet_file.name}: No file-level metadata found. File must be optimized first with add_parquet_metadata.py")
        
        # Validate all required fields are present and not empty
        # Note: The string "None" is valid (meaning "no value" for optional fields like disease/vaccine)
        # But missing fields or empty strings are not acceptable
        missing_fields = []
        for field in REQUIRED_METADATA_FIELDS:
            if field not in metadata:
                missing_fields.append(field)
            else:
                value = metadata[field]
                # Reject None, empty strings, or whitespace-only strings
                # Allow the string "None" as it's a valid metadata value
                if value is None or (isinstance(value, str) and value.strip() == ''):
                    missing_fields.append(field)
        
        if missing_fields:
            raise ValueError(f"{parquet_file.name}: Missing required metadata fields: {', '.join(missing_fields)}")
        
        # Build file_path using directory structure (reflects actual file location)
        # This is important for files in optimized directories (e.g., Bulk_opti)
        # Expected structure: .../chain/isotype/filename.parquet
        parts = parquet_file.parts
        
        if len(parts) < 3:
            logger.error(f"❌ {parquet_file.name}: Cannot determine file_path from directory structure. Expected format: .../chain/isotype/filename.parquet")
            raise ValueError(f"Invalid directory structure for {parquet_file.name}: cannot extract chain and isotype")
        
        file_path_chain = parts[-3]
        file_path_isotype = parts[-2]
        file_path = f"{file_path_chain}/{file_path_isotype}/{parquet_file.name}"
        
        # Build the metadata record with only required fields
        # All values must come from file-level metadata (no fallbacks)
        record = {
            'file_path': file_path,
            'chain': metadata['chain'],
            'file_source': metadata['file_source'],
            'species': metadata['species'],
            'subject': metadata['subject'],
            'disease': metadata['disease'],
            'vaccine': metadata['vaccine'],
            'isotype': metadata['isotype'],
            'total_sequences': int(metadata['total_sequences'])  # Convert to int
        }
        
        return record
    
    except ValueError:
        # Re-raise ValueError - these are handled by the caller
        raise
    except Exception as e:
        # Re-raise other exceptions as ValueError with clear message
        raise ValueError(f"{parquet_file.name}: Failed to read file - {e}")


def reindex_metadata(data_dir: Path, force: bool = False):
    """
    Reindex all Parquet files and create/update metadata.parquet in each subdirectory.
    
    This works per subdirectory, creating one metadata.parquet file per directory
    where Parquet files are located. Automatically cleans up deleted files before indexing.
    
    Args:
        data_dir: Directory containing Parquet files (e.g., data/)
        force: If True, recreate metadata even if all files are already indexed
    """
    logger.info(f"Scanning directory: {data_dir}")
    
    # First, cleanup deleted files automatically
    cleanup_deleted_files(data_dir)
    
    # Find all subdirectories that contain Parquet files
    subdirs_with_parquet = set()
    parquet_files = []
    
    for pfile in data_dir.rglob("*.parquet"):
        if pfile.name != 'metadata.parquet':
            parquet_files.append(pfile)
            # Get the subdirectory (parent of the parquet file)
            subdir = pfile.parent
            subdirs_with_parquet.add(subdir)
    
    if not parquet_files:
        logger.error(f"No Parquet files found in {data_dir}")
        return
    
    logger.info(f"Found {len(parquet_files)} Parquet files in {len(subdirs_with_parquet)} subdirectories")
    
    total_files_indexed = 0
    total_rows = 0
    total_new_files = 0
    skipped_subdirs = []  # Track subdirectories that were skipped due to errors
    total_all_sequences = 0  # Sum of total_sequences across all metadata files
    
    # Process each subdirectory separately
    for subdir in sorted(subdirs_with_parquet):
        logger.info(f"\n📁 Processing subdirectory: {subdir}")
        
        # Get Parquet files in this subdirectory
        subdir_parquet_files = [f for f in parquet_files if f.parent == subdir]
        
        if not subdir_parquet_files:
            continue
        
        logger.info(f"  Found {len(subdir_parquet_files)} Parquet files")
        
        # Check if metadata file already exists
        metadata_path = subdir / "metadata.parquet"
        existing_df = None
        existing_file_paths = set()
        
        if metadata_path.exists() and not force:
            try:
                existing_df = pd.read_parquet(metadata_path)
                existing_file_paths = set(existing_df['file_path'].tolist())
                num_metadata_files = len(existing_df)
                num_actual_files = len(subdir_parquet_files)
                
                logger.info(f"  📋 Found existing metadata file: {num_metadata_files} files")
                
                # Quick check: if file counts match, verify file_paths match
                # (cleanup already verified counts, so if counts match here, files are likely all there)
                # No need to read Parquet files - just compare file_paths from directory structure
                if num_actual_files == num_metadata_files:
                    logger.debug(f"  Quick check: File counts match ({num_actual_files})")
                    # Build file_paths from directory structure (very fast - no file reading)
                    quick_actual_file_paths = set()
                    all_valid = True
                    
                    for pfile in subdir_parquet_files:
                        parts = pfile.parts
                        if len(parts) >= 3:
                            file_path = f"{parts[-3]}/{parts[-2]}/{pfile.name}"
                            quick_actual_file_paths.add(file_path)
                        else:
                            all_valid = False
                            break
                    
                    # If file_paths match, skip detailed processing
                    # (cleanup already verified counts match, so files are likely all there)
                    if all_valid and quick_actual_file_paths == existing_file_paths:
                        logger.info(f"  ✅ All files already in metadata - skipping")
                        
                        # Calculate and display sums from existing metadata
                        try:
                            subdir_total_sequences_sum = existing_df['total_sequences'].astype(int).sum()
                            
                            logger.info(f"  📊 Subdirectory summary: {len(existing_df)} files total")
                            logger.info(f"     Total sequences: {subdir_total_sequences_sum:,}")
                            
                            # Add to overall totals
                            total_all_sequences += subdir_total_sequences_sum
                        except (ValueError, TypeError, KeyError) as e:
                            logger.debug(f"  Could not calculate sums from metadata: {e}")
                        
                        continue
                    # Otherwise, continue with detailed processing below
            except Exception as e:
                logger.warning(f"  ⚠️  Could not read existing metadata file: {e}")
                existing_df = None
        
        # Extract metadata from each file in this subdirectory
        metadata_records = []
        files_skipped = 0
        actual_file_paths = set()
        errors = []
        
        for pfile in subdir_parquet_files:
            try:
                meta = extract_file_metadata(pfile)
                if meta:
                    actual_file_paths.add(meta['file_path'])
                    
                    # Skip if file_path is already in metadata and not forcing
                    if meta['file_path'] in existing_file_paths and not force:
                        files_skipped += 1
                        continue
                    
                    metadata_records.append(meta)
                else:
                    # Should not happen - extract_file_metadata raises on error
                    error_msg = f"{pfile.name}: Unexpected error - metadata extraction returned None"
                    logger.error(f"  ❌ {error_msg}")
                    errors.append(error_msg)
            except ValueError as e:
                # Collect error - error message already formatted in extract_file_metadata
                error_msg = str(e)
                logger.error(f"  ❌ {error_msg}")
                errors.append(error_msg)
            except Exception as e:
                # Collect unexpected errors
                error_msg = f"{pfile.name}: Unexpected error - {e}"
                logger.error(f"  ❌ {error_msg}")
                errors.append(error_msg)
        
        # If there are errors, skip this subdirectory and continue with others
        if errors:
            logger.error(f"\n❌ ERRORS FOUND in {subdir}:")
            for error in errors:
                logger.error(f"   - {error}")
            logger.error(f"\n⚠️  {len(errors)} file(s) failed validation in {subdir}")
            logger.error("   These files must be optimized with: python scripts/add_parquet_metadata.py")
            logger.error(f"   ⏭️  Skipping this subdirectory, continuing with others...")
            skipped_subdirs.append(str(subdir))
            continue  # Skip this subdirectory, continue with next
        
        # Remove entries from existing metadata that no longer have corresponding files
        if existing_df is not None:
            files_before_cleanup = len(existing_df)
            # Keep only entries where the file still exists
            existing_df = existing_df[existing_df['file_path'].isin(actual_file_paths)]
            files_removed = files_before_cleanup - len(existing_df)
            if files_removed > 0:
                logger.info(f"  🗑️  Removed {files_removed} entries for deleted files")
        
        if files_skipped > 0:
            logger.info(f"  ⏭️  Skipped {files_skipped} files already in metadata")
        
        # Create metadata DataFrame from new records (if any)
        if metadata_records:
            new_metadata_df = pd.DataFrame(metadata_records)
        else:
            new_metadata_df = pd.DataFrame()
        
        # Merge with existing data if it exists
        if existing_df is not None and not force:
            if len(new_metadata_df) > 0:
                # Combine existing and new data
                combined_df = pd.concat([existing_df, new_metadata_df], ignore_index=True)
                # Remove duplicates, keeping the last occurrence (newest data)
                combined_df = combined_df.drop_duplicates(subset=['file_path'], keep='last')
                logger.info(f"  ✅ Updated metadata table: {len(combined_df)} total files ({len(metadata_records)} new)")
            else:
                # Only cleanup happened, use cleaned existing_df
                combined_df = existing_df
                if files_skipped > 0:
                    logger.info(f"  ✅ Updated metadata table: {len(combined_df)} files (cleaned up deleted files)")
                else:
                    logger.info(f"  ✅ Updated metadata table: {len(combined_df)} files")
        else:
            if len(new_metadata_df) > 0:
                # Create new metadata table
                combined_df = new_metadata_df
                logger.info(f"  ✅ Created new metadata table: {len(metadata_records)} files")
            else:
                logger.warning(f"  ⚠️  No valid metadata extracted from files in {subdir}")
                continue
        
        # Sort by file_path
        combined_df = combined_df.sort_values('file_path')
        
        # Calculate sums from the final combined metadata DataFrame
        try:
            subdir_total_sequences_sum = combined_df['total_sequences'].astype(int).sum()
        except (ValueError, TypeError, KeyError):
            subdir_total_sequences_sum = 0
        
        # Save the updated metadata
        combined_df.to_parquet(metadata_path, index=False, compression='zstd')
        
        total_files_indexed += len(metadata_records)
        total_new_files += len(metadata_records)
        
        # For total_rows, only count sequences from newly indexed files
        if metadata_records:
            new_file_sequences = sum(int(meta.get('total_sequences', 0)) for meta in metadata_records)
            total_rows += new_file_sequences
        
        # Add to overall totals (sum of all metadata files)
        total_all_sequences += subdir_total_sequences_sum
        
        logger.info(f"  📊 Subdirectory summary: {len(combined_df)} files total")
        logger.info(f"     Total sequences: {subdir_total_sequences_sum:,}")
    
    # Overall summary
    logger.info("\n" + "="*60)
    logger.info("REINDEXING SUMMARY")
    logger.info("="*60)
    logger.info(f"Subdirectories processed: {len(subdirs_with_parquet) - len(skipped_subdirs)}")
    if skipped_subdirs:
        logger.warning(f"Subdirectories skipped due to errors: {len(skipped_subdirs)}")
        for skipped in skipped_subdirs:
            logger.warning(f"  - {skipped}")
        logger.warning("  These subdirectories need optimization before they can be indexed")
    logger.info(f"Total new files indexed: {total_new_files}")
    logger.info(f"Total sequences indexed (new files): {total_rows:,}")
    logger.info("")
    logger.info(f"TOTAL ACROSS ALL METADATA FILES:")
    logger.info(f"  Total sequences: {total_all_sequences:,}")
    logger.info("="*60)
    if skipped_subdirs:
        logger.warning("⚠️  Reindexing complete with warnings - some subdirectories were skipped")
    else:
        logger.info("✅ Reindexing complete!")
    
    return total_files_indexed


def cleanup_deleted_files(data_dir: Path):
    """
    Remove entries from metadata.parquet files for deleted Parquet files.
    This cleanup is performed automatically whenever the script runs.
    
    Args:
        data_dir: Directory containing Parquet files
    
    Returns:
        Number of cleaned subdirectories
    """
    logger.info("Checking for deleted files in metadata...")
    
    # Find all subdirectories that contain metadata files
    metadata_files = list(data_dir.rglob("metadata.parquet"))
    
    if not metadata_files:
        logger.info("  No metadata.parquet files found")
        return 0
    
    cleaned_count = 0
    total_removed = 0
    skipped_subdirs = []  # Track subdirectories skipped due to errors during cleanup
    
    for metadata_file in metadata_files:
        subdir = metadata_file.parent
        
        # Quick check: compare file counts first
        subdir_parquet_files = [f for f in subdir.glob("*.parquet") 
                               if f.name != 'metadata.parquet']
        num_files = len(subdir_parquet_files)
        
        try:
            existing_df = pd.read_parquet(metadata_file)
            num_metadata_rows = len(existing_df)
        except Exception as e:
            logger.warning(f"  ⚠️  Error reading {metadata_file}: {e}")
            continue
        
        # Quick check: if counts match, skip detailed processing
        if num_files == num_metadata_rows:
            continue  # No changes needed, skip this directory
        
        # Counts don't match - need detailed check
        logger.debug(f"  {subdir}: File count mismatch ({num_files} files vs {num_metadata_rows} metadata rows) - checking details...")
        
        # Build set of actual file_paths from existing files
        actual_file_paths = set()
        cleanup_errors = []
        for pfile in subdir_parquet_files:
            try:
                meta = extract_file_metadata(pfile)
                if meta:
                    actual_file_paths.add(meta['file_path'])
                else:
                    # Should not happen - extract_file_metadata raises on error
                    error_msg = f"{pfile.name}: Unexpected error during cleanup - metadata extraction returned None"
                    logger.error(f"  ❌ {error_msg}")
                    cleanup_errors.append(error_msg)
            except ValueError as e:
                # Collect error - error message already formatted in extract_file_metadata
                error_msg = str(e)
                logger.error(f"  ❌ {error_msg}")
                cleanup_errors.append(error_msg)
            except Exception as e:
                # Collect unexpected errors
                error_msg = f"{pfile.name}: Unexpected error during cleanup - {e}"
                logger.error(f"  ❌ {error_msg}")
                cleanup_errors.append(error_msg)
        
        # If there are errors during cleanup, skip this subdirectory
        if cleanup_errors:
            logger.error(f"\n❌ ERRORS FOUND during cleanup in {subdir}:")
            for error in cleanup_errors:
                logger.error(f"   - {error}")
            logger.error(f"\n⚠️  {len(cleanup_errors)} file(s) failed validation")
            logger.error("   These files must be optimized with: python scripts/add_parquet_metadata.py")
            logger.error(f"   ⏭️  Skipping cleanup for this subdirectory, continuing with others...")
            skipped_subdirs.append(str(subdir))
            continue  # Skip this subdirectory, continue with next
        
        # Keep only entries where the file still exists
        files_before = num_metadata_rows
        cleaned_df = existing_df[existing_df['file_path'].isin(actual_file_paths)]
        files_after = len(cleaned_df)
        files_removed = files_before - files_after
        
        if files_removed > 0:
            # Sort and save cleaned metadata
            cleaned_df = cleaned_df.sort_values('file_path')
            cleaned_df.to_parquet(metadata_file, index=False, compression='zstd')
            logger.info(f"  🗑️  {subdir}: Removed {files_removed} entries for deleted files")
            cleaned_count += 1
            total_removed += files_removed
    
    if total_removed > 0:
        logger.info(f"  ✅ Cleaned up {total_removed} deleted file entries in {cleaned_count} subdirectories")
    else:
        logger.info(f"  ✅ No deleted files found - all metadata is up to date")
    
    if skipped_subdirs:
        logger.warning(f"  ⚠️  Skipped {len(skipped_subdirs)} subdirectories due to errors during cleanup:")
        for skipped in skipped_subdirs:
            logger.warning(f"     - {skipped}")
    
    return cleaned_count


def verify_counts(data_dir: Path):
    """
    Verify sequence counts match between files and metadata table in each subdirectory.
    
    This function automatically cleans up deleted files before verification.
    
    Useful for checking data integrity per subdirectory.
    
    Args:
        data_dir: Directory containing Parquet files
    
    Returns:
        True if all counts match, False otherwise
    """
    logger.info("Verifying counts per subdirectory...")
    
    # First, cleanup deleted files automatically
    cleanup_deleted_files(data_dir)
    
    # Find all subdirectories that contain Parquet files
    subdirs_with_parquet = set()
    parquet_files = []
    
    for pfile in data_dir.rglob("*.parquet"):
        if pfile.name != 'metadata.parquet':
            parquet_files.append(pfile)
            subdir = pfile.parent
            subdirs_with_parquet.add(subdir)
    
    if not parquet_files:
        logger.error(f"No Parquet files found in {data_dir}")
        return False
    
    all_counts_match = True
    
    # Verify each subdirectory separately
    for subdir in sorted(subdirs_with_parquet):
        logger.info(f"\n📁 Verifying: {subdir}")
        
        # Count from Parquet files directly
        subdir_parquet_files = [f for f in parquet_files if f.parent == subdir]
        
        actual_count = 0
        files_with_metadata = 0
        
        for pfile in subdir_parquet_files:
            try:
                parquet_table = pq.read_table(pfile)
                actual_count += parquet_table.num_rows
                
                # Check if file has file-level metadata
                if parquet_table.schema.metadata:
                    has_metadata = any(not k.startswith(b'pandas') 
                                      for k in parquet_table.schema.metadata.keys())
                    if has_metadata:
                        files_with_metadata += 1
            except Exception as e:
                logger.warning(f"  ⚠️  Error reading {pfile.name}: {e}")
        
        logger.info(f"  Actual count (from Parquet files): {actual_count:,}")
        logger.info(f"  Files with file-level metadata: {files_with_metadata}/{len(subdir_parquet_files)}")
        
        # Count from metadata table
        metadata_file = subdir / 'metadata.parquet'
        if metadata_file.exists():
            try:
                metadata_df = pd.read_parquet(metadata_file)
                
                # Sum total_sequences from metadata
                if 'total_sequences' in metadata_df.columns:
                    total_sequences_sum = metadata_df['total_sequences'].astype(int).sum()
                else:
                    logger.warning(f"  ⚠️  'total_sequences' column not found in metadata")
                    total_sequences_sum = 0
                
                logger.info(f"  Total sequences (from metadata.parquet): {total_sequences_sum:,}")
                
                if actual_count == total_sequences_sum:
                    logger.info(f"  ✅ Counts match - metadata is accurate")
                else:
                    logger.warning(f"  ⚠️  Counts don't match! Difference: {abs(actual_count - total_sequences_sum):,}")
                    logger.warning(f"     Actual: {actual_count:,}, Metadata: {total_sequences_sum:,}")
                    all_counts_match = False
            except Exception as e:
                logger.warning(f"  ⚠️  Error reading metadata file: {e}")
                all_counts_match = False
        else:
            logger.warning(f"  ⚠️  metadata.parquet not found")
            all_counts_match = False
    
    if all_counts_match:
        logger.info(f"\n✅ All subdirectories have accurate metadata!")
    else:
        logger.warning(f"\n⚠️  Some subdirectories have mismatched counts. Run with --reindex to fix.")
    
    return all_counts_match


def main():
    parser = argparse.ArgumentParser(
        description='Reindex Parquet metadata per subdirectory',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script reads file-level metadata from Parquet files (added by add_parquet_metadata.py)
and creates/updates metadata.parquet files in each subdirectory.

The script automatically (default behavior):
- Recursively finds all subdirectories with Parquet files starting from data/
- Checks if metadata.parquet exists in each subdirectory
- Creates metadata.parquet if it doesn't exist (adds all files)
- Updates existing metadata.parquet by:
  * Adding new files that aren't in metadata
  * Removing entries for deleted files
- Extracts metadata from file-level Parquet metadata (not data columns)

With --reindex flag:
- Deletes existing metadata.parquet files
- Recreates metadata.parquet from scratch for all files

Examples:
  # Default: automatically create/update metadata in data/ directory
  python scripts/reindex_metadata.py
  
  # Process specific directory
  python scripts/reindex_metadata.py --data-dir data/Heavy
  
  # Reindex: delete and recreate all metadata files from scratch
  python scripts/reindex_metadata.py --reindex
        """
    )
    parser.add_argument(
        '--data-dir',
        type=str,
        default='data',
        help='Directory containing Parquet files (default: data)'
    )
    parser.add_argument(
        '--reindex',
        action='store_true',
        help='Delete existing metadata.parquet files and recreate from scratch'
    )
    
    args = parser.parse_args()
    
    data_dir = Path(args.data_dir)
    
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        return
    
    if args.reindex:
        # Delete existing metadata files and recreate from scratch
        logger.info("Reindexing: Deleting existing metadata.parquet files...")
        metadata_files = list(data_dir.rglob("metadata.parquet"))
        deleted_count = 0
        for metadata_file in metadata_files:
            try:
                metadata_file.unlink()
                deleted_count += 1
            except Exception as e:
                logger.warning(f"  ⚠️  Could not delete {metadata_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"  🗑️  Deleted {deleted_count} existing metadata.parquet files")
        
        # Now reindex everything from scratch
        reindex_metadata(data_dir, force=True)
    else:
        # Default: create/update metadata automatically
        reindex_metadata(data_dir, force=False)


if __name__ == "__main__":
    main()

