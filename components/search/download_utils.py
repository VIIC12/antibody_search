"""
Download utilities for creating Parquet and ZIP files for search results.

This module provides functions for preparing and packaging search results
for download.
"""

import gzip
import io
import json
import hashlib
import zipfile
import tempfile
import os
import time
import uuid
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List, Callable

try:
    import fcntl
except ImportError:
    fcntl = None  # Windows: no file lock; cache may be filled twice for same query
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
# Query result cache: chunk size when filling cache, lock wait timeout (seconds)
# 100k rows per chunk to avoid OOM; 1M rows per chunk causes OOM in Docker/constrained memory.
QUERY_CACHE_CHUNK_SIZE = 1000000
QUERY_CACHE_LOCK_TIMEOUT = 300

# Load .env once so ABHUNTER_DOWNLOAD_DIR is set when this module is used (e.g. from Streamlit or scripts)
_env_loaded = False


def _ensure_env_loaded() -> None:
    """Load .env from project root once per process so ABHUNTER_DOWNLOAD_DIR etc. are set."""
    global _env_loaded
    if _env_loaded:
        return
    try:
        from dotenv import load_dotenv
        # Project root: components/search/download_utils.py -> go up to repo root
        repo_root = Path(__file__).resolve().parent.parent.parent
        load_dotenv(repo_root / ".env")
    except ImportError:
        pass
    _env_loaded = True


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
    Always returns an absolute path so writes do not depend on process CWD.
    In Docker, set ABHUNTER_DOWNLOAD_DIR=/app/downloads; the same path must
    be mounted for nginx (read-only) to serve files.
    """
    _ensure_env_loaded()
    raw = os.getenv("ABHUNTER_DOWNLOAD_DIR", "./downloads")
    return Path(raw).resolve()


def _build_query_cache_key(
    database_paths: List[str],
    table_name: str,
    where_clause: str
) -> str:
    """
    Build a stable cache key for a query result from database_paths, table_name, and where_clause.
    """
    payload = json.dumps(
        {"paths": sorted(database_paths), "table": table_name, "where": where_clause},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _get_query_cache_directory() -> Path:
    """
    Get the directory for caching full query results (Parquet files).
    Uses ABHUNTER_QUERY_CACHE_DIR if set, otherwise ABHUNTER_DOWNLOAD_DIR/.query_cache.
    """
    _ensure_env_loaded()
    raw = os.getenv("ABHUNTER_QUERY_CACHE_DIR")
    if raw:
        cache_dir = Path(raw).resolve()
    else:
        cache_dir = _get_download_directory() / ".query_cache"
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o775)
    return cache_dir


def _is_valid_parquet_file(path: Path) -> bool:
    """Return True if path exists and is a valid Parquet file (has proper footer)."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with pq.ParquetFile(path) as _:
            pass
        return True
    except Exception:
        return False


def _get_or_create_cached_result_parquet(
    database_paths: List[str],
    table_name: str,
    where_clause: str,
    engine,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Optional[Path]:
    """
    Return path to a Parquet file containing the full query result, filling the cache if needed.
    Uses a file lock so only one process runs the query; others wait and then read the cache.
    Returns None if the query returns no rows (no file written).
    On lock timeout, runs the query to a temp file and returns that path (caller may delete after use).
    """
    cache_dir = _get_query_cache_directory()
    cache_key = _build_query_cache_key(database_paths, table_name, where_clause)
    parquet_path = cache_dir / f"{cache_key}.parquet"
    lock_path = cache_dir / f"{cache_key}.lock"

    # Cache hit: file exists and is valid Parquet (reject incomplete/corrupt files)
    if _is_valid_parquet_file(parquet_path):
        return parquet_path
    if parquet_path.exists():
        parquet_path.unlink(missing_ok=True)

    lock_acquired = False
    lock_file = None

    if fcntl is not None:
        lock_path.touch(exist_ok=True)
        lock_file = open(lock_path, "a")
        deadline = time.monotonic() + QUERY_CACHE_LOCK_TIMEOUT
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_acquired = True
                break
            except (BlockingIOError, OSError):
                time.sleep(1)
        if not lock_acquired:
            lock_file.close()
            lock_file = None
            # Fall back to temp file: run query without caching
            temp_path = None
            try:
                fd, temp_path = tempfile.mkstemp(suffix=".parquet", prefix="abquery_")
                os.close(fd)
                # Use LIMIT/OFFSET so only one chunk is in memory at a time
                _fill_parquet_from_query_limit_offset(
                    engine, table_name, where_clause, Path(temp_path),
                    progress_callback=progress_callback,
                )
                if Path(temp_path).stat().st_size == 0:
                    Path(temp_path).unlink(missing_ok=True)
                    return None
                return Path(temp_path)
            except Exception:
                if temp_path is not None and Path(temp_path).exists():
                    Path(temp_path).unlink(missing_ok=True)
                raise

    if lock_acquired or fcntl is None:
        try:
            # Double-check after acquiring lock: another process may have filled it
            if _is_valid_parquet_file(parquet_path):
                return parquet_path
            if parquet_path.exists():
                parquet_path.unlink(missing_ok=True)
            # Use LIMIT/OFFSET (not streaming) so only one chunk is in memory at a time
            _fill_parquet_from_query_limit_offset(
                engine, table_name, where_clause, parquet_path,
                progress_callback=progress_callback,
            )
            if not _is_valid_parquet_file(parquet_path):
                parquet_path.unlink(missing_ok=True)
                return None
            return parquet_path
        finally:
            if lock_file is not None and fcntl is not None:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except (OSError, AttributeError):
                    pass
                lock_file.close()

    return None


def _fill_parquet_from_query(
    engine, table_name: str, where_clause: str, out_path: Path,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> None:
    """
    Run a single streaming query and write chunks to Parquet. Uses DuckDB's
    fetch_df_chunk on the connection (execute returns the connection) to avoid
    LIMIT/OFFSET and repeated scans. Falls back to LIMIT/OFFSET if streaming fails.
    Writes raw table columns (no formatting). If no rows, writes nothing.
    progress_callback(rows_written) is called after each chunk.
    """
    query_base = f"SELECT * FROM {table_name} WHERE {where_clause}"
    conn = engine.conn
    writer = None  # pq.ParquetWriter, set when first chunk is received
    schema = None
    rows_written = 0
    try:
        conn.execute(query_base)
        # vectors_per_chunk: DuckDB fetches in units of ~2048 rows; 50 gives ~100k rows per chunk
        vectors_per_chunk = max(1, QUERY_CACHE_CHUNK_SIZE // 2048)
        while True:
            chunk_df = conn.fetch_df_chunk(vectors_per_chunk)
            if chunk_df.empty:
                break
            if writer is None:
                schema = pa.Schema.from_pandas(chunk_df, preserve_index=False)
                fields = [pa.field(f.name, f.type, nullable=True) for f in schema]
                schema = pa.schema(fields)
                writer = pq.ParquetWriter(out_path, schema, compression="zstd")
            table = pa.Table.from_pandas(chunk_df)
            try:
                table = table.cast(schema)
            except Exception:
                unified = pa.unify_schemas([schema, table.schema])
                table = table.cast(unified)
            writer.write_table(table)
            rows_written += len(chunk_df)
            if progress_callback is not None:
                progress_callback(rows_written)
            else:
                prev_blocks = (rows_written - len(chunk_df)) // QUERY_CACHE_CHUNK_SIZE
                if rows_written // QUERY_CACHE_CHUNK_SIZE > prev_blocks:
                    logger.info("Caching query result: %s rows written", rows_written)
    except (AttributeError, TypeError) as e:
        logger.warning(
            "Streaming query failed (%s), falling back to LIMIT/OFFSET: %s",
            type(e).__name__,
            e,
        )
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
            out_path.unlink(missing_ok=True)
        _fill_parquet_from_query_limit_offset(
            engine, table_name, where_clause, out_path,
            progress_callback=progress_callback,
        )
        return
    finally:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                out_path.unlink(missing_ok=True)
        if out_path.exists() and out_path.stat().st_size == 0:
            out_path.unlink(missing_ok=True)


def _fill_parquet_from_query_limit_offset(
    engine, table_name: str, where_clause: str, out_path: Path,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> None:
    """
    Fallback: run query with LIMIT/OFFSET in chunks and write to Parquet.
    Used when streaming (fetch_df_chunk) is not available or fails.
    progress_callback(rows_written) is called after each chunk.
    """
    CHUNK_SIZE = QUERY_CACHE_CHUNK_SIZE
    query_base = f"SELECT * FROM {table_name} WHERE {where_clause}"
    first_df = engine.conn.execute(f"{query_base} LIMIT {CHUNK_SIZE}").df()
    if first_df.empty:
        return
    schema = pa.Schema.from_pandas(first_df, preserve_index=False)
    fields = [pa.field(f.name, f.type, nullable=True) for f in schema]
    schema = pa.schema(fields)
    writer = pq.ParquetWriter(out_path, schema, compression="zstd")
    chunk_df = first_df
    offset = 0
    rows_written = 0
    while True:
        if chunk_df.empty:
            break
        table = pa.Table.from_pandas(chunk_df)
        try:
            table = table.cast(schema)
        except Exception:
            unified = pa.unify_schemas([schema, table.schema])
            table = table.cast(unified)
        writer.write_table(table)
        rows_written += len(chunk_df)
        if progress_callback is not None:
            progress_callback(rows_written)
        else:
            prev_blocks = (rows_written - len(chunk_df)) // QUERY_CACHE_CHUNK_SIZE
            if rows_written // QUERY_CACHE_CHUNK_SIZE > prev_blocks:
                logger.info("Caching query result: %s rows written", rows_written)
        offset += CHUNK_SIZE
        if len(chunk_df) < CHUNK_SIZE:
            break
        chunk_df = engine.conn.execute(
            f"{query_base} LIMIT {CHUNK_SIZE} OFFSET {offset}"
        ).df()
    writer.close()
    if out_path.exists() and out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)


def _generate_download_token() -> str:
    """
    Generate a unique token for file downloads.
    
    Returns:
        Unique token string (UUID hex)
    """
    return uuid.uuid4().hex


def _get_download_path(
    original_filename: str,
    file_type: str = "zip"
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

    # Create directory if it doesn't exist (mode so nginx/process can read/write as needed)
    download_dir.mkdir(parents=True, exist_ok=True, mode=0o775)
    
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


def _convert_parquet_to_csv_gz(parquet_path: Path, csv_gz_path: Path) -> None:
    """
    Convert a Parquet file to gzip-compressed CSV by streaming batches directly
    into a gzip writer. Avoids writing uncompressed CSV to disk.
    """
    parquet_file = pq.ParquetFile(parquet_path)
    first_batch = True
    with gzip.open(csv_gz_path, "wt", encoding="utf-8") as f_out:
        for batch in parquet_file.iter_batches(batch_size=6291456):
            chunk_df = batch.to_pandas()
            chunk_df.to_csv(
                f_out,
                header=first_batch,
                index=False,
            )
            first_batch = False
    parquet_path.unlink()


def prepare_full_results_download_background(
    database_paths: List[str],
    search_params: Dict[str, Any],
    is_paired: bool,
    chain_label: str
) -> Dict[str, Any]:
    """
        Prepare full results table download (gzip-compressed CSV) in a background process.
        
        This function performs a full search (no limit), writes results as Parquet
        in chunks, then converts to gzip-compressed CSV (.csv.gz) and serves it for
        download. This is a heavy operation that should run in the background.
        
        Args:
            database_paths: List of database directory paths
            search_params: Search parameters dictionary (will be copied)
            is_paired: Whether this is a paired search
            chain_label: Chain label for filename ("paired", "heavy", or "light")
            
        Returns:
            Dictionary with keys:
            - 'success': Boolean indicating if operation succeeded
            - 'parquet_data': .csv.gz file content as bytes (for small files; key kept for API compatibility)
            - 'filename': Suggested filename for download (.csv.gz)
            - 'file_size_bytes': Size of file in bytes
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
        # use 24 threads when loading full results
        if hasattr(engine, "configure_threads"):
            engine.configure_threads(24)

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
        
        # Get or create cached full result (single query; shared with FASTA download)
        cached_parquet_path = _get_or_create_cached_result_parquet(
            database_paths, table_name, where_clause, engine
        )
        if hasattr(engine, "conn"):
            engine.conn.close()
        if cached_parquet_path is None:
            return {
                "success": False,
                "error": "No sequences found to download.",
            }
        cache_dir = _get_query_cache_directory()
        is_temp_path = cached_parquet_path.resolve().parent != cache_dir.resolve()
        
        # Generate token and file path for formatted output (parquet then converted to CSV)
        search_params_with_metadata = dict(search_params)
        identifier = _build_search_identifier({
            "search_params": search_params_with_metadata,
            "chain_label": chain_label,
            "is_paired": is_paired,
        })
        base_filename = f"ABHunter_sequences_{chain_label}_{identifier}"
        parquet_filename = f"{base_filename}.parquet"
        csv_gz_filename = f"{base_filename}.csv.gz"
        token, file_path, _ = _get_download_path(parquet_filename, "parquet")
        
        # Read cached Parquet in chunks, format for download, write to temp Parquet
        parquet_file = pq.ParquetFile(cached_parquet_path)
        writer = None
        schema = None
        sequence_count = 0
        try:
            for batch in parquet_file.iter_batches(batch_size=QUERY_CACHE_CHUNK_SIZE):
                chunk_df = batch.to_pandas()
                if chunk_df.empty:
                    continue
                chunk_formatted = prepare_download_data(chunk_df, is_paired)
                chunk_table = pa.Table.from_pandas(chunk_formatted)
                if schema is None:
                    schema = chunk_table.schema
                    fields = [pa.field(f.name, f.type, nullable=True) for f in schema]
                    schema = pa.schema(fields)
                    writer = pq.ParquetWriter(file_path, schema, compression="zstd")
                try:
                    chunk_table = chunk_table.cast(schema)
                except Exception:
                    unified = pa.unify_schemas([schema, chunk_table.schema])
                    chunk_table = chunk_table.cast(unified)
                if writer is not None:
                    writer.write_table(chunk_table)
                sequence_count += len(chunk_df)
                logger.debug(
                    "Background full results download: Processed chunk. Total: %s",
                    sequence_count,
                )
        finally:
            if writer is not None:
                writer.close()
        if is_temp_path and cached_parquet_path.exists():
            cached_parquet_path.unlink(missing_ok=True)
        
        if sequence_count == 0:
            return {"success": False, "error": "No sequences found to download."}
        
        # Convert formatted Parquet to gzip-compressed CSV for download
        os.chmod(file_path, 0o644)
        csv_gz_path = file_path.with_suffix(".csv.gz")
        _convert_parquet_to_csv_gz(file_path, csv_gz_path)
        
        os.chmod(csv_gz_path, 0o644)
        file_size_bytes = csv_gz_path.stat().st_size
        download_url = f"/downloads/{token}.csv.gz"
        
        logger.info(f"Background full results download: Completed. File size: {file_size_bytes} bytes. Sequences: {sequence_count}")
        
        # Check if file is too large for direct download
        if file_size_bytes > LARGE_FILE_THRESHOLD:
            # File already on disk, return URL
            return {
                'success': True,
                'download_url': download_url,
                'filename': csv_gz_filename,
                'file_size_bytes': file_size_bytes,
                'sequence_count': sequence_count,
                'is_large_file': True,
                'token': token
            }
        else:
            # For small files, read from disk and return bytes for direct download
            try:
                with open(csv_gz_path, 'rb') as f:
                    file_data = f.read()
                csv_gz_path.unlink()
                return {
                    'success': True,
                    'parquet_data': file_data,
                    'filename': csv_gz_filename,
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
        
        # Get or create cached full result (single query; shared with full results download)
        cached_parquet_path = _get_or_create_cached_result_parquet(
            database_paths, table_name, where_clause, engine
        )
        if hasattr(engine, "conn"):
            engine.conn.close()
        if cached_parquet_path is None:
            return {
                "success": False,
                "error": "No sequences found to download.",
            }
        cache_dir = _get_query_cache_directory()
        is_temp_path = cached_parquet_path.resolve().parent != cache_dir.resolve()
        
        # Infer sequence columns from cached Parquet schema
        parquet_file = pq.ParquetFile(cached_parquet_path)
        schema = parquet_file.schema_arrow
        all_columns = schema.names
        if is_paired:
            seq_columns = ["sequence_alignment_aa_heavy", "sequence_alignment_aa_light"]
        else:
            if "sequence_alignment_aa" in all_columns:
                seq_columns = ["sequence_alignment_aa"]
            elif "sequence_alignment_aa_heavy" in all_columns and "sequence_alignment_aa_light" in all_columns:
                seq_columns = ["sequence_alignment_aa_heavy", "sequence_alignment_aa_light"]
            elif "sequence_alignment_aa_heavy" in all_columns:
                seq_columns = ["sequence_alignment_aa_heavy"]
            elif "sequence_alignment_aa_light" in all_columns:
                seq_columns = ["sequence_alignment_aa_light"]
            else:
                if is_temp_path and cached_parquet_path.exists():
                    cached_parquet_path.unlink(missing_ok=True)
                return {
                    "success": False,
                    "error": "No sequence columns found in database.",
                }
        seq_columns = [c for c in seq_columns if c in all_columns]
        if not seq_columns:
            if is_temp_path and cached_parquet_path.exists():
                cached_parquet_path.unlink(missing_ok=True)
            return {
                "success": False,
                "error": "No sequence columns found in database.",
            }
        
        # Create temporary files for FASTA content (to avoid memory issues)
        fasta_files = {}
        temp_files = {}
        
        try:
            # Create temporary files for each FASTA file
            if is_paired:
                temp_files["paired"] = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8")
            else:
                if len(seq_columns) == 2:
                    temp_files["heavy"] = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8")
                    temp_files["light"] = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8")
                else:
                    temp_files[chain_label] = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8")
            
            hit_number = 1
            for batch in parquet_file.iter_batches(columns=seq_columns, batch_size=100000):
                chunk_df = batch.to_pandas()
                if chunk_df.empty:
                    continue
                if is_paired:
                    for _, row in chunk_df.iterrows():
                        heavy_seq = row.get("sequence_alignment_aa_heavy")
                        light_seq = row.get("sequence_alignment_aa_light")
                        if pd.notna(heavy_seq) and heavy_seq:
                            temp_files["paired"].write(f">{hit_number}_heavy\n")
                            temp_files["paired"].write(f"{heavy_seq}\n")
                        if pd.notna(light_seq) and light_seq:
                            temp_files["paired"].write(f">{hit_number}_light\n")
                            temp_files["paired"].write(f"{light_seq}\n")
                        hit_number += 1
                else:
                    if len(seq_columns) == 2:
                        for _, row in chunk_df.iterrows():
                            heavy_seq = row.get("sequence_alignment_aa_heavy")
                            light_seq = row.get("sequence_alignment_aa_light")
                            if pd.notna(heavy_seq) and heavy_seq:
                                temp_files["heavy"].write(f">{hit_number}_heavy\n")
                                temp_files["heavy"].write(f"{heavy_seq}\n")
                            if pd.notna(light_seq) and light_seq:
                                temp_files["light"].write(f">{hit_number}_light\n")
                                temp_files["light"].write(f"{light_seq}\n")
                            hit_number += 1
                    else:
                        seq_col = seq_columns[0]
                        for _, row in chunk_df.iterrows():
                            seq = row.get(seq_col)
                            if pd.notna(seq) and seq:
                                temp_files[chain_label].write(f">{hit_number}_{chain_label}\n")
                                temp_files[chain_label].write(f"{seq}\n")
                                hit_number += 1
                logger.debug("Background FASTA download: Processed chunk. Hit number: %s", hit_number)
            
            if is_temp_path and cached_parquet_path.exists():
                cached_parquet_path.unlink(missing_ok=True)
            
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
            try:
                zip_fp = zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED)
            except PermissionError as e:
                download_dir = _get_download_directory()
                raise PermissionError(
                    f"Cannot write to download directory: {download_dir}. "
                    "Ensure the directory exists and is writable by this process. "
                    "In Docker, set ABHUNTER_DOWNLOAD_DIR=/app/downloads and mount the same host path "
                    "(e.g. ./downloads) with write access; fix host permissions if needed (e.g. chmod 775 ./downloads)."
                ) from e
            with zip_fp as zip_file:
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
