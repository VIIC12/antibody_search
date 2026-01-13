"""
Download utilities for creating Parquet and ZIP files for search results.

This module provides functions for preparing and packaging search results
for download.
"""

import io
import json
import hashlib
import zipfile
import tempfile
import os
import uuid
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Set up global logger
logger = logging.getLogger(__name__)

from components.search.results_display import (
    format_results_dataframe,
    get_exclude_columns
)
from components.search.search_execution import execute_search
from components.search.results_plotting import build_plotting_where_clause
from src.search_engine import AntibodySearchEngine

# Threshold for large files (5MB)
LARGE_FILE_THRESHOLD = 5 * 1024 * 1024  # 5MB in bytes


def generate_filename_base(is_paired: bool) -> str:
    """
    Generate base filename for download files.
    
    Args:
        is_paired: Whether this is a paired search
        
    Returns:
        Base filename string
    """
    return "abdb_sequences_paired" if is_paired else "abdb_sequences_unpaired"


def prepare_download_data(
    df: pd.DataFrame,
    is_paired: bool,
    exclude_cols: Optional[set] = None
) -> pd.DataFrame:
    """
    Prepare dataframe for download by excluding columns and renaming.
    
    Args:
        df: Input dataframe with search results
        is_paired: Whether this is a paired search
        exclude_cols: Optional set of columns to exclude
        
    Returns:
        Formatted dataframe ready for download
    """
    return format_results_dataframe(df, is_paired, exclude_cols)


def _serialize_search_params(search_params: Dict[str, Any]) -> str:
    """Serialize search parameters into a stable JSON string."""
    return json.dumps(search_params or {}, sort_keys=True, default=str)


def _build_search_identifier(search_params: Dict[str, Any]) -> str:
    serialized = _serialize_search_params(search_params)
    digest = hashlib.md5(serialized.encode()).hexdigest()[:12]
    return digest


def _get_download_directory() -> Path:
    """
    Get the download directory path from environment variable or use default.
    
    Returns:
        Path object for the download directory
    """
    download_dir = os.getenv("ABHUNTER_DOWNLOAD_DIR", "./downloads")
    download_path = Path(download_dir)
    return download_path


def _generate_download_token() -> str:
    """
    Generate a unique token for file downloads.
    
    Returns:
        Unique token string (UUID hex)
    """
    return uuid.uuid4().hex


def _get_download_path(
    original_filename: str,
    file_type: str = "parquet"
) -> Tuple[str, Path, str]:
    """
    Generate download path and URL for streaming file writes.
    
    Args:
        original_filename: Original filename for the file
        file_type: Type of file (parquet, zip, etc.)
        
    Returns:
        Tuple of (token, file_path, download_url)
        
    Raises:
        OSError: If directory cannot be created
    """
    download_dir = _get_download_directory()
    
    # Create directory if it doesn't exist
    download_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate unique token
    token = _generate_download_token()
    
    # Determine file extension from original filename or file_type
    if original_filename and '.' in original_filename:
        ext = original_filename.split('.')[-1]
    else:
        ext = file_type
    
    # Generate filename with token
    filename = f"{token}.{ext}"
    file_path = download_dir / filename
    
    # Generate download URL
    # Use relative path that nginx will serve
    download_url = f"/downloads/{filename}"
    
    return token, file_path, download_url


def _build_where_clause_from_params(
    engine,
    search_params: Dict[str, Any],
    is_paired: bool,
    unpaired_chain_type: str = "Heavy"
) -> str:
    """
    Build WHERE clause from search parameters for direct DuckDB queries.
    Similar to build_plotting_where_clause but handles CDR motifs too.
    
    Args:
        engine: Search engine instance
        search_params: Search parameters dictionary
        is_paired: Whether this is a paired search
        unpaired_chain_type: Chain type for unpaired searches
        
    Returns:
        WHERE clause string
    """
    from components.search.results_plotting import build_plotting_where_clause
    
    # Start with base WHERE clause (handles V/D/J genes and CDR lengths)
    conditions = []
    base_where = build_plotting_where_clause(engine, search_params, is_paired, unpaired_chain_type)
    
    if base_where and base_where != "1=1":
        conditions.append(f"({base_where})")
    
    # Add CDR motif conditions
    if is_paired:
        # Heavy chain motifs
        for cdr_num in [1, 2, 3]:
            motif_key = f'heavy_cdr{cdr_num}_motif'
            similarity_key = f'heavy_cdr{cdr_num}_similarity'
            mismatches_key = f'heavy_cdr{cdr_num}_mismatches'
            
            motif = search_params.get(motif_key, '')
            if motif:
                similarity = search_params.get(similarity_key, False)
                mismatches = search_params.get(mismatches_key, 2)
                
                if similarity:
                    regex_pattern = engine.generate_similarity_pattern(motif, mismatches)
                else:
                    regex_pattern = engine._convert_motif_to_regex(motif)
                
                # Find CDR AA columns for heavy chain
                cdr_aa_key = f'cdr{cdr_num}_aa'
                if cdr_aa_key in engine.schema.get('chain_columns', {}):
                    motif_conditions = []
                    for col in engine.schema['chain_columns'][cdr_aa_key]:
                        if '_heavy' in col:
                            motif_conditions.append(f"{col} ~ '{regex_pattern}'")
                    if motif_conditions:
                        conditions.append(f"({' OR '.join(motif_conditions)})")
        
        # Light chain motifs
        for cdr_num in [1, 2, 3]:
            motif_key = f'light_cdr{cdr_num}_motif'
            similarity_key = f'light_cdr{cdr_num}_similarity'
            mismatches_key = f'light_cdr{cdr_num}_mismatches'
            
            motif = search_params.get(motif_key, '')
            if motif:
                similarity = search_params.get(similarity_key, False)
                mismatches = search_params.get(mismatches_key, 2)
                
                if similarity:
                    regex_pattern = engine.generate_similarity_pattern(motif, mismatches)
                else:
                    regex_pattern = engine._convert_motif_to_regex(motif)
                
                # Find CDR AA columns for light chain
                cdr_aa_key = f'cdr{cdr_num}_aa'
                if cdr_aa_key in engine.schema.get('chain_columns', {}):
                    motif_conditions = []
                    for col in engine.schema['chain_columns'][cdr_aa_key]:
                        if '_light' in col:
                            motif_conditions.append(f"{col} ~ '{regex_pattern}'")
                    if motif_conditions:
                        conditions.append(f"({' OR '.join(motif_conditions)})")
    else:
        # Unpaired motifs
        cdr_prefix = 'light_' if unpaired_chain_type.lower() == 'light' else 'heavy_'
        
        for cdr_num in [1, 2, 3]:
            motif_key = f'{cdr_prefix}cdr{cdr_num}_motif'
            similarity_key = f'{cdr_prefix}cdr{cdr_num}_similarity'
            mismatches_key = f'{cdr_prefix}cdr{cdr_num}_mismatches'
            
            # Also check without prefix for backward compatibility
            motif = search_params.get(motif_key) or search_params.get(f'cdr{cdr_num}_motif', '')
            if motif:
                similarity = search_params.get(similarity_key) or search_params.get(f'cdr{cdr_num}_similarity', False)
                mismatches = search_params.get(mismatches_key) or search_params.get(f'cdr{cdr_num}_mismatches', 2)
                
                if similarity:
                    regex_pattern = engine.generate_similarity_pattern(motif, mismatches)
                else:
                    regex_pattern = engine._convert_motif_to_regex(motif)
                
                # Find CDR AA columns
                cdr_aa_key = f'cdr{cdr_num}_aa'
                if cdr_aa_key in engine.schema.get('chain_columns', {}):
                    motif_conditions = []
                    for col in engine.schema['chain_columns'][cdr_aa_key]:
                        motif_conditions.append(f"{col} ~ '{regex_pattern}'")
                    if motif_conditions:
                        conditions.append(f"({' OR '.join(motif_conditions)})")
    
    return ' AND '.join(conditions) if conditions else "1=1"


def create_parquet_file(
    dataframe: pd.DataFrame,
    _filename_base: str,
    search_params: Dict[str, Any],
    chain_label: str,
    is_paired: bool = False
) -> Tuple[bytes, str]:
    """
    Create a Parquet file in memory with a unique filename.
    
    Args:
        dataframe: DataFrame to save as Parquet
        _filename_base: Deprecated base name parameter (retained for compatibility)
        search_params: Search parameters dictionary (including metadata)
        chain_label: Sequence grouping label ("paired", "heavy", or "light")
        is_paired: Whether this is a paired search (for filename)
        
    Returns:
        Parquet file contents as bytes along with the filename
    """
    # Prepare data for download
    download_data = prepare_download_data(dataframe, is_paired)
    
    # Create Parquet file in memory with ZSTD compression
    parquet_buffer = io.BytesIO()
    table = pa.Table.from_pandas(download_data)
    pq.write_table(table, parquet_buffer, compression="zstd")
    parquet_buffer.seek(0)

    identifier = _build_search_identifier({
        "search_params": search_params,
        "chain_label": chain_label,
        "is_paired": is_paired
    })
    filename = f"ABHunter_sequences_{chain_label}_{identifier}.parquet"

    return parquet_buffer.getvalue(), filename


def prepare_stats_download(
    stats_df: pd.DataFrame,
    search_params: Dict[str, Any],
    is_paired: bool,
    statistics: Optional[Dict[str, Any]] = None,
    selected_databases: Optional[List[str]] = None
) -> Tuple[bytes, str]:
    """
    Prepare statistics CSV for download as a ZIP file with search parameters.
    
    Args:
        stats_df: Statistics dataframe
        search_params: Search parameters dictionary (including metadata)
        is_paired: Whether the search is paired
        statistics: Optional statistics dictionary for metadata
        selected_databases: Optional list of selected database paths
        
    Returns:
        Tuple of (ZIP file content as bytes, filename)
    """
    from datetime import datetime
    
    # Convert dataframe to CSV string
    csv_buffer = io.StringIO()
    stats_df.to_csv(csv_buffer, index=False)
    csv_content = csv_buffer.getvalue()
    
    # Build search metadata similar to plots download
    selected_databases = selected_databases or []
    statistics = statistics or {}
    
    metadata: Dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "is_paired": is_paired,
        "search_params": search_params,
        "selected_databases": selected_databases,
        "statistics_summary": {
            "total_hits": statistics.get("total_hits"),
            "total_sequences": statistics.get("total_sequences"),
            "percentage": statistics.get("percentage"),
            "per_million": statistics.get("per_million"),
            "search_time": statistics.get("search_time"),
        },
    }
    
    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Add CSV file
        zip_file.writestr("statistics.csv", csv_content.encode('utf-8'))
        
        # Add search parameters JSON file
        metadata_json = json.dumps(metadata, indent=2, sort_keys=True, default=str)
        zip_file.writestr("search_parameters.json", metadata_json.encode('utf-8'))
    
    zip_buffer.seek(0)
    zip_data = zip_buffer.getvalue()
    
    # Generate filename
    identifier = _build_search_identifier({
        "search_params": search_params,
        "is_paired": is_paired
    })
    filename = f"ABHunter_statistics_{identifier}.zip"
    
    return zip_data, filename


def prepare_full_results_download_background(
    database_paths: List[str],
    search_params: Dict[str, Any],
    is_paired: bool,
    chain_label: str
) -> Dict[str, Any]:
    """
    Prepare full results table download (Parquet file) in a background process.
    
    This function performs a full search (no limit) and creates a Parquet file
    for download. This is a heavy operation that should run in the background.
    
    Args:
        database_paths: List of database directory paths
        search_params: Search parameters dictionary (will be copied)
        is_paired: Whether this is a paired search
        chain_label: Chain label for filename ("paired", "heavy", or "light")
        
    Returns:
        Dictionary with keys:
        - 'success': Boolean indicating if operation succeeded
        - 'parquet_data': Parquet file content as bytes
        - 'filename': Suggested filename for download
        - 'file_size_bytes': Size of Parquet file in bytes
        - 'sequence_count': Number of sequences in file
        - 'error': Error message if failed
    """
    try:
        # Import here to ensure paths are set up correctly in worker process
        import sys
        import warnings
        from pathlib import Path
        project_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(project_root))
        sys.path.insert(0, str(project_root / "src"))
        
        # Suppress Streamlit caching warnings in worker processes
        warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.caching.cache_data_api")
        logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
        
        # Ensure logging is configured in worker process
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[logging.StreamHandler(sys.stdout)]
            )
            # Set this module to DEBUG in worker
            logging.getLogger(__name__).setLevel(logging.DEBUG)

        
        from components.search.database_utils import init_search_engine
        from components.search.search_execution import execute_search
        import json
        
        # Import functions from this module
        from components.search.download_utils import (
            create_parquet_file,
            generate_filename_base,
            _build_search_identifier,
            LARGE_FILE_THRESHOLD,
            _get_download_path
        )
        
        # Create a new search engine instance in the worker process
        engine = init_search_engine(
            data_dir=database_paths,
            db_path=":memory:"
        )
        logger.info("Background full results download: Search engine initialized")
        
        # Copy search params to avoid modifying original
        search_params_copy = search_params.copy()
        selected_databases_formatted = search_params_copy.pop("selected_databases", [])
        
        # Determine chain type for unpaired searches
        unpaired_chain_type = "Heavy"
        if not is_paired:
            if any(search_params_copy.get(k) for k in ['light_v', 'light_j', 'light_cdr1_length', 
                                                       'light_cdr2_length', 'light_cdr3_length']):
                unpaired_chain_type = "Light"
        
        # Build WHERE clause directly (more efficient than using execute_search)
        where_clause = _build_where_clause_from_params(
            engine, search_params_copy, is_paired, unpaired_chain_type
        )
        
        # Determine table name
        table_name = "antibodies"
        
        # Get total count first (for progress tracking)
        count_query = f"SELECT COUNT(*) as cnt FROM {table_name} WHERE {where_clause}"
        total_count = engine.conn.execute(count_query).fetchone()[0]
        logger.info(f"Background full results download: Total sequences to process: {total_count}")
        
        if total_count == 0:
            return {
                'success': False,
                'error': 'No sequences found to download.'
            }
        
        # Generate token and file path BEFORE starting query (for streaming to disk)
        search_params_with_metadata = dict(search_params)
        identifier = _build_search_identifier({
            "search_params": search_params_with_metadata,
            "chain_label": chain_label,
            "is_paired": is_paired
        })
        parquet_filename = f"ABHunter_sequences_{chain_label}_{identifier}.parquet"
        
        # Get download path for streaming write
        token, file_path, download_url = _get_download_path(parquet_filename, "parquet")
        
        # Process in chunks to avoid memory issues - stream directly to disk
        CHUNK_SIZE = 100000  # Process 100k rows at a time
        
        # Get schema from a sample to properly infer nullability
        # Use a sample of 1000 rows to better detect nullable columns
        sample_query = f"SELECT * FROM {table_name} WHERE {where_clause} LIMIT 1000"
        sample_df = engine.conn.execute(sample_query).df()
        
        if sample_df.empty:
            return {
                'success': False,
                'error': 'No sequences found to download.'
            }
        
        # Prepare sample for download format
        sample_formatted = prepare_download_data(sample_df, is_paired)
        sample_table = pa.Table.from_pandas(sample_formatted)
        
        # Make all columns nullable to handle nulls in later chunks
        # This is safer when processing large datasets where different chunks may have different null patterns
        schema = sample_table.schema
        fields = []
        for field in schema:
            # Ensure all fields are nullable
            fields.append(pa.field(field.name, field.type, nullable=True))
        schema = pa.schema(fields)
        
        # Initialize Parquet writer - writes directly to disk file
        writer = pq.ParquetWriter(file_path, schema, compression='zstd')
        sequence_count = 0
        
        # Process in chunks using LIMIT/OFFSET - single query pass, stream to disk
        offset = 0
        while offset < total_count:
            chunk_query = f"""
                SELECT * FROM {table_name} 
                WHERE {where_clause}
                LIMIT {CHUNK_SIZE} OFFSET {offset}
            """
            chunk_df = engine.conn.execute(chunk_query).df()
            
            if chunk_df.empty:
                break
            
            # Format chunk for download
            chunk_formatted = prepare_download_data(chunk_df, is_paired)
            
            # Convert to PyArrow table
            chunk_table = pa.Table.from_pandas(chunk_formatted)
            
            # Cast to match schema (ensures all columns are nullable as per schema)
            # This handles cases where chunks have different null patterns
            try:
                chunk_table = chunk_table.cast(schema)
            except Exception as e:
                # If cast fails due to schema differences, unify schemas
                unified_schema = pa.unify_schemas([schema, chunk_table.schema])
                chunk_table = chunk_table.cast(unified_schema)
                # Note: We can't change writer schema mid-stream, so we'll use the unified schema
                # This should work as long as we made all fields nullable in the initial schema
            
            # Write chunk directly to disk file (no memory accumulation)
            writer.write_table(chunk_table)
            
            sequence_count += len(chunk_df)
            offset += CHUNK_SIZE
            
            logger.debug(f"Background full results download: Processed chunk. Total processed: {sequence_count}/{total_count}")
            
            # Safety check: if chunk is smaller than expected, we're done
            if len(chunk_df) < CHUNK_SIZE:
                break
        
        # Close writer - file is now complete on disk
        writer.close()
        
        # Set file permissions to be readable by nginx
        os.chmod(file_path, 0o644)
        
        # Get file size from disk
        file_size_bytes = file_path.stat().st_size
        
        logger.info(f"Background full results download: Completed. File size: {file_size_bytes} bytes. Sequences: {sequence_count}")
        
        # Close the engine connection
        if hasattr(engine, 'conn'):
            engine.conn.close()
        
        # Check if file is too large for direct download
        if file_size_bytes > LARGE_FILE_THRESHOLD:
            # File already on disk, return URL
            return {
                'success': True,
                'download_url': download_url,
                'filename': parquet_filename,
                'file_size_bytes': file_size_bytes,
                'sequence_count': sequence_count,
                'is_large_file': True,
                'token': token
            }
        else:
            # For small files, read from disk and return bytes for direct download
            try:
                with open(file_path, 'rb') as f:
                    parquet_data = f.read()
                # Delete the file since we're returning it in memory
                file_path.unlink()
                return {
                    'success': True,
                    'parquet_data': parquet_data,
                    'filename': parquet_filename,
                    'file_size_bytes': file_size_bytes,
                    'sequence_count': sequence_count,
                    'is_large_file': False
                }
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Failed to read file for direct download: {str(e)}',
                    'error_type': type(e).__name__
                }
        
    except Exception as e:
        logger.error(f"Background full results download failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


def prepare_plots_download_background(
    plots_data: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    include_raw_data: bool = False
) -> Dict[str, Any]:
    """
    Prepare plots download (ZIP file with PNG images and optionally CSV data) in a background process.
    
    This function recreates Plotly figures from serialized data and creates a ZIP archive.
    This is a heavy operation that should run in the background.
    
    Args:
        plots_data: List of dictionaries containing:
            - 'title': Plot title
            - 'figure_dict': Plotly figure as dictionary (from figure.to_dict())
            - 'data': Optional DataFrame data for raw data export (as dict/list)
        metadata: Search metadata dictionary
        include_raw_data: Whether to include CSV exports of plotting data
        
    Returns:
        Dictionary with keys:
        - 'success': Boolean indicating if operation succeeded
        - 'zip_data': ZIP file content as bytes
        - 'filename': Suggested filename for download
        - 'file_size_bytes': Size of ZIP file in bytes
        - 'plot_count': Number of plots in the archive
        - 'error': Error message if failed
    """
    try:
        # Import here to ensure paths are set up correctly in worker process
        import sys
        import warnings
        import json
        import io
        import zipfile
        from pathlib import Path
        from typing import Optional, Tuple
        import pandas as pd
        import plotly.graph_objects as go
        
        project_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(project_root))
        sys.path.insert(0, str(project_root / "src"))
        
        # Suppress Streamlit caching warnings in worker processes
        warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.caching.cache_data_api")
        logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
        
        # Ensure logging is configured in worker process
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[logging.StreamHandler(sys.stdout)]
            )
            # Set this module to DEBUG in worker
            logging.getLogger(__name__).setLevel(logging.DEBUG)

        
        # Import functions from results_plotting module
        from components.search.results_plotting import (
            create_plots_zip,
            _sanitize_plot_filename,
            _json_default
        )
        
        logger.info(f"Background plots download: Started. Plots count: {len(plots_data) if plots_data else 0}")
        
        if not plots_data:
            return {
                'success': False,
                'error': 'No plots available for download.'
            }
        
        # Recreate Plotly figures from dictionaries
        plots: List[Tuple[str, go.Figure, Optional[pd.DataFrame]]] = []
        for plot_info in plots_data:
            title = plot_info.get('title', 'Untitled Plot')
            figure_dict = plot_info.get('figure_dict')
            data = plot_info.get('data')
            
            if figure_dict:
                # Recreate Plotly figure from dictionary
                figure = go.Figure(figure_dict)
            else:
                # Skip if no figure data
                continue
            
            # Convert data to DataFrame if provided
            plot_data = None
            if data is not None:
                if isinstance(data, list):
                    # DataFrame was serialized as list of dicts (from to_dict('records'))
                    plot_data = pd.DataFrame(data)
                elif isinstance(data, dict):
                    # Series was serialized as dict, or DataFrame as dict (less common)
                    # Try to create DataFrame from dict
                    try:
                        plot_data = pd.DataFrame(data)
                    except Exception:
                        # If that fails, try as Series
                        plot_data = pd.Series(data)
                else:
                    plot_data = data
            
            plots.append((title, figure, plot_data))
        
        if not plots:
            return {
                'success': False,
                'error': 'No valid plots to include in download.'
            }
        
        # Generate filename first
        chain_label = "paired" if metadata.get('is_paired', False) else "heavy"
        seed_hash = abs(hash(str({
            "search_params": metadata.get('search_params', {}),
            "is_paired": metadata.get('is_paired', False),
        })))
        
        if include_raw_data:
            filename = f"abhunter_result_plots_raw_data_{chain_label}_{seed_hash}.zip"
        else:
            filename = f"abhunter_results_plots_{chain_label}_{seed_hash}.zip"
        
        # Get download path for streaming write
        token, file_path, download_url = _get_download_path(filename, "zip")
        
        # Create ZIP archive directly on disk (not in memory)
        try:
            with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for index, (title, figure, data) in enumerate(plots, start=1):
                    # Sanitize filename
                    from components.search.results_plotting import _sanitize_plot_filename
                    plot_filename = _sanitize_plot_filename(title, index)
                    # Generate PNG image
                    image_bytes = figure.to_image(format="png", scale=2)
                    zf.writestr(plot_filename, image_bytes)
                    
                    # Add raw data if requested
                    if include_raw_data and data is not None:
                        if isinstance(data, pd.DataFrame):
                            export_df = data.copy()
                        elif isinstance(data, pd.Series):
                            export_df = data.to_frame()
                        else:
                            export_df = pd.DataFrame(data)
                        
                        raw_filename = plot_filename.rsplit(".", 1)[0] + ".csv"
                        raw_path = f"raw_data/{raw_filename}"
                        csv_bytes = export_df.to_csv(index=False).encode("utf-8")
                        zf.writestr(raw_path, csv_bytes)
                
                # Add metadata JSON
                from components.search.results_plotting import _json_default
                plot_entries = [
                    {
                        "title": title,
                        "image_file": _sanitize_plot_filename(title, idx + 1),
                    }
                    for idx, (title, _, _) in enumerate(plots)
                ]
                metadata_with_plots = dict(metadata)
                metadata_with_plots["plots"] = plot_entries
                metadata_with_plots["includes_raw_plotting_data"] = include_raw_data
                metadata_bytes = json.dumps(
                    metadata_with_plots,
                    indent=2,
                    sort_keys=True,
                    default=_json_default
                ).encode("utf-8")
                zf.writestr("search_parameters.json", metadata_bytes)
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to create ZIP archive: {str(e)}',
                'error_type': type(e).__name__
            }
        
        # Set file permissions to be readable by nginx
        os.chmod(file_path, 0o644)
        
        # Get file size from disk
        file_size_bytes = file_path.stat().st_size
        plot_count = len(plots)
        
        # Check if file is too large for direct download
        if file_size_bytes > LARGE_FILE_THRESHOLD:
            # File already on disk, return URL
            return {
                'success': True,
                'download_url': download_url,
                'filename': filename,
                'file_size_bytes': file_size_bytes,
                'plot_count': plot_count,
                'is_large_file': True,
                'token': token
            }
        else:
            # For small files, read from disk and return bytes for direct download
            try:
                with open(file_path, 'rb') as f:
                    zip_bytes = f.read()
                # Delete the file since we're returning it in memory
                file_path.unlink()
                return {
                    'success': True,
                    'zip_data': zip_bytes,
                    'filename': filename,
                    'file_size_bytes': file_size_bytes,
                    'plot_count': plot_count,
                    'is_large_file': False
                }
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Failed to read file for direct download: {str(e)}',
                    'error_type': type(e).__name__
                }
        
    except Exception as e:
        logger.error(f"Background plots download failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


def prepare_fasta_download_background(
    database_paths: List[str],
    search_params: Dict[str, Any],
    is_paired: bool,
    chain_label: str = None
) -> Dict[str, Any]:
    """
    Prepare FASTA file download in a background process.
    
    This function performs a full search (no limit) and generates FASTA content
    for download. Creates a ZIP file with FASTA files and search parameters.
    
    Args:
        database_paths: List of database directory paths
        search_params: Search parameters dictionary (will be copied)
        is_paired: Whether this is a paired search
        chain_label: Chain label ("paired", "heavy", or "light")
        
    Returns:
        Dictionary with keys:
        - 'success': Boolean indicating if operation succeeded
        - 'data': ZIP file content as bytes
        - 'filename': Suggested filename for download
        - 'file_size_bytes': Size of ZIP file in bytes
        - 'sequence_count': Total number of sequences in FASTA files
        - 'error': Error message if failed
    """
    try:
        # Import here to ensure paths are set up correctly in worker process
        import sys
        import warnings
        from pathlib import Path
        project_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(project_root))
        sys.path.insert(0, str(project_root / "src"))
        
        # Suppress Streamlit caching warnings in worker processes
        warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.caching.cache_data_api")
        logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)
        
        # Ensure logging is configured in worker process
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[logging.StreamHandler(sys.stdout)]
            )
            # Set this module to DEBUG in worker
            logging.getLogger(__name__).setLevel(logging.DEBUG)

        
        from components.search.database_utils import init_search_engine
        from components.search.search_execution import execute_search
        
        # Import helper functions
        from components.search.download_utils import _build_search_identifier
        
        # Create a new search engine instance in the worker process
        engine = init_search_engine(
            data_dir=database_paths,
            db_path=":memory:"
        )
        logger.info("Background FASTA download: Search engine initialized")
        
        # Copy search params to avoid modifying original
        search_params_copy = search_params.copy()
        selected_databases_formatted = search_params_copy.pop("selected_databases", [])
        
        # Determine chain label if not provided
        if chain_label is None:
            if is_paired:
                chain_label = "paired"
            else:
                # Check if light chain parameters are present
                if any(search_params_copy.get(k) for k in ['light_v', 'light_j', 'light_cdr1_length', 
                                                           'light_cdr2_length', 'light_cdr3_length']):
                    chain_label = "light"
                else:
                    chain_label = "heavy"
        
        # Determine chain type for unpaired searches
        unpaired_chain_type = "Heavy" if chain_label == "heavy" else "Light"
        
        # Build WHERE clause directly (more efficient than using execute_search)
        where_clause = _build_where_clause_from_params(
            engine, search_params_copy, is_paired, unpaired_chain_type
        )
        
        # Determine table name
        table_name = "antibodies"
        
        # Get total count first
        count_query = f"SELECT COUNT(*) as cnt FROM {table_name} WHERE {where_clause}"
        total_count = engine.conn.execute(count_query).fetchone()[0]
        logger.info(f"Background FASTA download: Total sequences to process: {total_count}")
        
        if total_count == 0:
            return {
                'success': False,
                'error': 'No sequences found to download.'
            }
        
        # Process in chunks to avoid memory issues
        CHUNK_SIZE = 100000  # Process 100k rows at a time
        
        # Determine which sequence columns we need
        sample_query = f"SELECT * FROM {table_name} WHERE {where_clause} LIMIT 1"
        sample_df = engine.conn.execute(sample_query).df()
        
        if sample_df.empty:
            return {
                'success': False,
                'error': 'No sequences found to download.'
            }
        
        # Determine sequence columns
        if is_paired:
            seq_columns = ['sequence_alignment_aa_heavy', 'sequence_alignment_aa_light']
        else:
            if 'sequence_alignment_aa' in sample_df.columns:
                seq_columns = ['sequence_alignment_aa']
            elif 'sequence_alignment_aa_heavy' in sample_df.columns and 'sequence_alignment_aa_light' in sample_df.columns:
                seq_columns = ['sequence_alignment_aa_heavy', 'sequence_alignment_aa_light']
            elif 'sequence_alignment_aa_heavy' in sample_df.columns:
                seq_columns = ['sequence_alignment_aa_heavy']
            elif 'sequence_alignment_aa_light' in sample_df.columns:
                seq_columns = ['sequence_alignment_aa_light']
            else:
                return {
                    'success': False,
                    'error': 'No sequence columns found in database.'
                }
        
        # Create temporary files for FASTA content (to avoid memory issues)
        fasta_files = {}
        temp_files = {}
        
        try:
            # Create temporary files for each FASTA file
            if is_paired:
                temp_files['paired'] = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8')
            else:
                if len(seq_columns) == 2:
                    temp_files['heavy'] = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8')
                    temp_files['light'] = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8')
                else:
                    temp_files[chain_label] = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8')
            
            # Process in chunks
            offset = 0
            hit_number = 1
            
            while offset < total_count:
                chunk_query = f"""
                    SELECT {', '.join(seq_columns)} FROM {table_name} 
                    WHERE {where_clause}
                    LIMIT {CHUNK_SIZE} OFFSET {offset}
                """
                chunk_df = engine.conn.execute(chunk_query).df()
                
                if chunk_df.empty:
                    break
                
                # Write FASTA content incrementally
                if is_paired:
                    for _, row in chunk_df.iterrows():
                        heavy_seq = row.get('sequence_alignment_aa_heavy')
                        light_seq = row.get('sequence_alignment_aa_light')
                        
                        if pd.notna(heavy_seq) and heavy_seq:
                            temp_files['paired'].write(f">{hit_number}_heavy\n")
                            temp_files['paired'].write(f"{heavy_seq}\n")
                        
                        if pd.notna(light_seq) and light_seq:
                            temp_files['paired'].write(f">{hit_number}_light\n")
                            temp_files['paired'].write(f"{light_seq}\n")
                        
                        hit_number += 1
                else:
                    if len(seq_columns) == 2:
                        # Both heavy and light columns exist
                        for _, row in chunk_df.iterrows():
                            heavy_seq = row.get('sequence_alignment_aa_heavy')
                            light_seq = row.get('sequence_alignment_aa_light')
                            
                            if pd.notna(heavy_seq) and heavy_seq:
                                temp_files['heavy'].write(f">{hit_number}_heavy\n")
                                temp_files['heavy'].write(f"{heavy_seq}\n")
                            
                            if pd.notna(light_seq) and light_seq:
                                temp_files['light'].write(f">{hit_number}_light\n")
                                temp_files['light'].write(f"{light_seq}\n")
                            
                            hit_number += 1
                    else:
                        # Single sequence column
                        seq_col = seq_columns[0]
                        for _, row in chunk_df.iterrows():
                            seq = row.get(seq_col)
                            if pd.notna(seq) and seq:
                                temp_files[chain_label].write(f">{hit_number}_{chain_label}\n")
                                temp_files[chain_label].write(f"{seq}\n")
                                hit_number += 1
                
                logger.debug(f"Background FASTA download: Processed chunk. Processed sequences: {min(offset + len(chunk_df), total_count)}/{total_count}")
                
                offset += CHUNK_SIZE
                
                if len(chunk_df) < CHUNK_SIZE:
                    break
            
            # Close temp files and read content
            for key, temp_file in temp_files.items():
                temp_file.close()
                with open(temp_file.name, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip():
                        fasta_files[key] = content
                # Clean up temp file
                os.unlink(temp_file.name)
            
            if not fasta_files:
                return {
                    'success': False,
                    'error': 'No sequences available for selected chain types.'
                }
            
            # Generate filename first
            identifier = _build_search_identifier({
                "search_params": search_params_copy,
                "chain_label": chain_label,
                "is_paired": is_paired,
                "selected_databases": sorted(selected_databases_formatted),
            })
            
            if len(fasta_files) > 1:
                filename = f"ABHunter_FASTA_{identifier}.zip"
            else:
                chain_name = list(fasta_files.keys())[0]
                filename = f"ABHunter_FASTA_{chain_name}_{identifier}.zip"
            
            # Get download path for streaming write
            token, file_path, download_url = _get_download_path(filename, "zip")
            
            # Create ZIP file directly on disk (not in memory)
            with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                # Add FASTA files
                for chain_type, fasta_content in fasta_files.items():
                    fasta_filename = f"sequences_{chain_type}.fasta"
                    zip_file.writestr(fasta_filename, fasta_content.encode('utf-8'))
                
                # Add search parameters JSON file
                search_params_with_metadata = dict(search_params)
                search_params_json = json.dumps(search_params_with_metadata, indent=2, sort_keys=True, default=str)
                zip_file.writestr("search_parameters.json", search_params_json.encode('utf-8'))
            
            # Set file permissions to be readable by nginx
            os.chmod(file_path, 0o644)
            
            # Count total sequences
            total_sequences = sum(content.count('>') for content in fasta_files.values())
            file_size_bytes = file_path.stat().st_size
            
            logger.info(f"Background FASTA download: Completed. File size: {file_size_bytes} bytes. Sequences: {total_sequences}")
            
        except Exception as e:
            # Clean up temp files on error
            for temp_file in temp_files.values():
                try:
                    temp_file.close()
                    if os.path.exists(temp_file.name):
                        os.unlink(temp_file.name)
                except:
                    pass
            raise  # Re-raise to be caught by outer except
        
        # Close the engine connection
        if hasattr(engine, 'conn'):
            engine.conn.close()
        
        # Check if file is too large for direct download
        if file_size_bytes > LARGE_FILE_THRESHOLD:
            # File already on disk, return URL
            return {
                'success': True,
                'download_url': download_url,
                'filename': filename,
                'file_size_bytes': file_size_bytes,
                'sequence_count': total_sequences,
                'is_large_file': True,
                'token': token
            }
        else:
            # For small files, read from disk and return bytes for direct download
            try:
                with open(file_path, 'rb') as f:
                    zip_data = f.read()
                # Delete the file since we're returning it in memory
                file_path.unlink()
                return {
                    'success': True,
                    'data': zip_data,
                    'filename': filename,
                    'file_size_bytes': file_size_bytes,
                    'sequence_count': total_sequences,
                    'is_large_file': False
                }
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Failed to read file for direct download: {str(e)}',
                    'error_type': type(e).__name__
                }
        
    except Exception as e:
        logger.error(f"Background FASTA download failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }
