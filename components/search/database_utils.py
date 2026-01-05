"""
Database utility functions for antibody search.

This module provides functions for database discovery, initialization,
and metadata checking.
"""

import os
import streamlit as st
from pathlib import Path
from typing import Optional, Union, List
import logging

from search_engine import AntibodySearchEngine

logger = logging.getLogger(__name__)


def is_production() -> bool:
    """Check if running in production environment."""
    return os.getenv('STREAMLIT_ENV') == 'production'


def init_search_engine(
    data_dir: Union[str, List[str]],
    progress_callback=None,
    db_path: str = ":memory:",
    verbose: bool = True
) -> AntibodySearchEngine:
    """
    Initialize search engine for a given data directory or directories.
    
    Args:
        data_dir: Directory containing Parquet files, or list of directories
        progress_callback: Optional callback function(progress, status) for progress updates
        db_path: DuckDB database path (default: ":memory:" for in-memory database)
        verbose: Whether to print initialization messages (default: True)
        
    Returns:
        Initialized AntibodySearchEngine instance
        
    Raises:
        SystemExit: If initialization fails (via st.stop())
    """
    try:
        # Handle both single directory and list of directories
        if isinstance(data_dir, list):
            # Ensure all items in the list are strings
            data_dirs_list = [str(d) for d in data_dir]
            engine = AntibodySearchEngine(
                data_dirs=data_dirs_list,
                progress_callback=progress_callback,
                db_path=db_path,
                verbose=verbose
            )
        else:
            engine = AntibodySearchEngine(
                data_dir=str(data_dir),
                progress_callback=progress_callback,
                db_path=db_path,
                verbose=verbose
            )
        return engine
    except Exception as e:
        st.error(f"Failed to initialize search engine for {data_dir}: {e}")
        st.info("Please ensure the database directory exists and contains Parquet files.")
        st.stop()


@st.cache_data(ttl="5m")  # Cache for 5 minutes
def check_metadata_freshness(data_dir: str) -> bool:
    """
    Check if metadata.parquet is up-to-date with Parquet files.
    
    Args:
        data_dir: Directory to check
        
    Returns:
        True if metadata is fresh, False otherwise
    """
    try:
        metadata_path = Path(data_dir) / 'metadata.parquet'
        if not metadata_path.exists():
            return False
        
        # Get metadata modification time
        metadata_mtime = metadata_path.stat().st_mtime
        
        # Get newest Parquet file modification time
        parquet_files = [
            f for f in Path(data_dir).glob('*.parquet')
            if f.name != 'metadata.parquet'
        ]
        if not parquet_files:
            return True  # No data files, metadata is "fresh"
        
        newest_parquet_mtime = max(f.stat().st_mtime for f in parquet_files)
        
        return metadata_mtime >= newest_parquet_mtime
    except Exception:
        return False


@st.cache_data(ttl="10m")  # Cache database discovery for 10 minutes
def get_available_databases() -> list:
    """
    Automatically detect databases by scanning for directories with metadata.parquet files.
    
    Reads ABHUNTER_DB_PATH from environment variable and recursively finds
    all directories containing metadata.parquet files.
    
    Returns:
        List of database directory paths (as strings)
    """
    available_databases = []
    
    # Read ABHUNTER_DB_PATH from environment variable
    abhunter_db_path = os.getenv("ABHUNTER_DB_PATH")
    if abhunter_db_path:
        logger.debug(f"Scanning ABHUNTER_DB_PATH: {abhunter_db_path}")
        data_dir = Path(abhunter_db_path)
        if data_dir.exists():
            # Recursively find all directories containing metadata.parquet
            for metadata_file in data_dir.rglob("metadata.parquet"):
                db_dir = metadata_file.parent
                # Check if this directory also has other parquet files (not just metadata)
                parquet_files = [
                    f for f in db_dir.glob("*.parquet")
                    if f.name != "metadata.parquet"
                ]
                if parquet_files:
                    available_databases.append(str(db_dir))
                    logger.debug(
                        f"Found database: {db_dir} ({len(parquet_files)} parquet files)"
                    )
    
    logger.info(f"Found {len(available_databases)} available databases: {available_databases}")
    return available_databases


@st.cache_data(ttl="10m")  # Cache database structure for 10 minutes
def get_database_structure() -> dict:
    """
    Get organized database structure with Heavy, Light, Paired categories and subdirectories.
    
    Scans the data directory for Heavy/, Light/, and Paired/ subdirectories,
    and organizes them by category with metadata about each subdirectory.
    
    Uses ABHUNTER_DB_PATH environment variable if set, otherwise falls back to
    project_root / "data" for backward compatibility.
    
    Returns:
        Dictionary with structure:
        {
            'Heavy': {
                'subdir_name': {
                    'path': str,
                    'parquet_count': int,
                    'sequence_count': int,
                    'has_metadata': bool
                }
            },
            'Light': {...},
            'Paired': {...}
        }
    """
    structure = {
        'Heavy': {},
        'Light': {},
        'Paired': {}
    }
    
    # Check for ABHUNTER_DB_PATH environment variable first
    # If not set, fall back to project_root / "data" for backward compatibility
    abhunter_db_path = os.getenv("ABHUNTER_DB_PATH")
    if abhunter_db_path:
        data_dir = Path(abhunter_db_path)
        logger.debug(f"Using ABHUNTER_DB_PATH: {data_dir}")
    else:
        # Use data directory relative to project root
        # This assumes the function is called from pages/search.py
        project_root = Path(__file__).parent.parent.parent
        data_dir = project_root / "data"
        logger.debug(f"Using default data directory: {data_dir}")
    
    if not data_dir.exists():
        logger.warning(f"Data directory not found: {data_dir}")
        return structure
    
    # Scan each main category
    for category in ['Heavy', 'Light', 'Paired']:
        category_dir = data_dir / category
        if category_dir.exists():
            # Find all subdirectories with metadata.parquet
            for subdir in category_dir.iterdir():
                if not subdir.is_dir():
                    continue

                metadata_file = subdir / "metadata.parquet"

                if metadata_file.exists():
                    # Check if there are parquet files (not just metadata)
                    parquet_files = [
                        f for f in subdir.glob("*.parquet")
                        if f.name != "metadata.parquet"
                    ]
                    if parquet_files:
                        # Read sequence count from metadata file
                        sequence_count = 0
                        try:
                            import pandas as pd
                            metadata_df = pd.read_parquet(metadata_file)
                            if 'total_sequences' in metadata_df.columns:
                                sequence_count = metadata_df['total_sequences'].sum()
                        except Exception as e:
                            logger.warning(
                                f"Could not read sequence count from {metadata_file}: {e}"
                            )
                            sequence_count = 0

                        structure[category][subdir.name] = {
                            'path': str(subdir),
                            'parquet_count': len(parquet_files),
                            'sequence_count': sequence_count,
                            'has_metadata': True,
                            'is_inferred': False
                        }
                        logger.debug(
                            f"Found {category}/{subdir.name}: "
                            f"{len(parquet_files)} parquet files, "
                            f"{sequence_count:,} sequences"
                        )
    
    # Check for inferred directory directly in data/Inferred/
    inferred_dir = data_dir / "Inferred"
    if inferred_dir.exists() and inferred_dir.is_dir():
        # Check for inferred overlay files
        inferred_overlay_file_vh_vl = inferred_dir / "adj_vh_vl_freq_table_for_search_wo_epsilon.parquet"
        inferred_overlay_file_jh_jl = inferred_dir / "adj_jh_vj_freq_table_for_search_wo_epsilon.parquet"
        
        if inferred_overlay_file_vh_vl.exists() or inferred_overlay_file_jh_jl.exists():
            structure['Inferred'] = {
                'Inferred': {
                    'path': str(inferred_dir),
                    'parquet_count': 1,
                    'sequence_count': 0,
                    'has_metadata': False,
                    'is_inferred': True
                }
            }
            logger.debug(f"Found inferred pairing overlay at {inferred_dir}")
    
    logger.info(f"Database structure: {structure}")
    return structure

