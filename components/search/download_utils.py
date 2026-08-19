"""
Download utilities for creating Parquet and ZIP files for search results.

This module provides functions for preparing and packaging search results
for download.
"""

import csv
import gzip
import io
import json
import hashlib
import zipfile
import tempfile
import os
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

import pandas as pd

# Set up global logger
logger = logging.getLogger(__name__)

from components.search.results_display import (
    get_exclude_columns,
    get_column_rename_mapping,
)
from components.search.search_execution import execute_search
from components.search.results_plotting import build_plotting_where_clause
from src.search_engine import AntibodySearchEngine

# Threshold for large files (1 GB)
LARGE_FILE_THRESHOLD = 1073741824

# Load .env once so ABHUNTER_DOWNLOAD_DIR / ABHUNTER_TMP_DIR are set when this module is used
_env_loaded = False


def _ensure_env_loaded() -> None:
    """Load .env from project root once per process so ABHUNTER_* paths are set."""
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


def _get_tmp_directory() -> Path:
    """
    Scratch directory for download preparation (e.g. FASTA sequence CSV, plot PNGs).

    Uses ABHUNTER_TMP_DIR when set, otherwise the OS temp directory.
    Always returns an absolute path and creates the directory if needed.
    """
    _ensure_env_loaded()
    raw = os.getenv("ABHUNTER_TMP_DIR")
    path = Path(raw).resolve() if raw else Path(tempfile.gettempdir()).resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o775)
    return path


def _use_nginx_download_urls() -> bool:
    """
    True when nginx serves /downloads/ with Content-Disposition: attachment
    (Docker Compose). Local Streamlit rewrites /downloads/ to /app/static/downloads/
    and displays the file in the browser instead of downloading it.
    """
    _ensure_env_loaded()
    return os.getenv("ABHUNTER_DOWNLOAD_DIR") == "/app/downloads" or Path("/.dockerenv").exists()



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
    
    ext = file_type
    # Use consistent prefix from original_filename (e.g. ABHunter_FASTA_paired_<hash>) so large
    # file downloads get the same naming as small; append token for uniqueness.
    if original_filename and original_filename.endswith("." + ext):
        base = original_filename[: -len(ext) - 1]
    elif original_filename and "." in original_filename:
        base = original_filename.rsplit(".", 1)[0]
    else:
        base = original_filename or ""
    if base:
        filename = f"{base}_{token}.{ext}"
    else:
        filename = f"{token}.{ext}"
    file_path = download_dir / filename

    # nginx serves /downloads/; local Streamlit serves via static/ symlink
    if _use_nginx_download_urls():
        download_url = f"/downloads/{filename}"
    else:
        download_url = f"app/static/downloads/{filename}"
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


_FREQUENCY_PLOT_EXPORT_COLUMNS = [
    "subject",
    "total_sequences",
    "hits",
    "percentage",
    "per_million",
    "hits_per_million",
    "log10_hits",
    "is_binned",
]


def prepare_frequency_download(
    summary_df: pd.DataFrame,
    plot_df: Optional[pd.DataFrame],
    plot_meta: Optional[Dict[str, Any]],
    search_params: Dict[str, Any],
    is_paired: bool,
    statistics: Optional[Dict[str, Any]] = None,
    selected_databases: Optional[List[str]] = None,
) -> Tuple[bytes, str]:
    """
    Prepare frequency summary + plotted donor data as a ZIP with search parameters.
    """
    from datetime import datetime

    summary_buffer = io.StringIO()
    if summary_df is not None and not summary_df.empty:
        summary_df.to_csv(summary_buffer, index=False)

    plot_export = pd.DataFrame()
    if plot_df is not None and not plot_df.empty:
        export_cols = [c for c in _FREQUENCY_PLOT_EXPORT_COLUMNS if c in plot_df.columns]
        plot_export = plot_df[export_cols] if export_cols else plot_df.copy()

    plot_buffer = io.StringIO()
    if not plot_export.empty:
        plot_export.to_csv(plot_buffer, index=False)

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
        "plot_options": plot_meta or {},
    }

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("frequency_summary.csv", summary_buffer.getvalue().encode("utf-8"))
        zip_file.writestr("frequency_by_donor.csv", plot_buffer.getvalue().encode("utf-8"))
        zip_file.writestr(
            "search_parameters.json",
            json.dumps(metadata, indent=2, sort_keys=True, default=str).encode("utf-8"),
        )

    zip_buffer.seek(0)
    identifier = _build_search_identifier({
        "search_params": search_params,
        "is_paired": is_paired,
        "plot_options": plot_meta or {},
    })
    filename = f"ABHunter_frequency_{identifier}.zip"
    return zip_buffer.getvalue(), filename


def _consume_generated_download(
    result: Dict[str, Any],
    *,
    data_keys: List[str],
) -> Tuple[bytes, str]:
    """Return generated download bytes, reading from disk when nginx-mode wrote a file."""
    if not result or not result.get("success"):
        raise ValueError((result or {}).get("error", "Download generation failed."))

    for key in data_keys:
        payload = result.get(key)
        if payload:
            return payload, result.get("filename", "download.bin")

    download_url = result.get("download_url")
    if not download_url:
        raise ValueError("Download result did not contain data bytes or a file URL.")

    stored_name = download_url.rsplit("/", 1)[-1]
    file_path = _get_download_directory() / stored_name
    if not file_path.exists():
        raise FileNotFoundError(f"Expected generated download file not found: {file_path}")

    file_bytes = file_path.read_bytes()
    file_path.unlink(missing_ok=True)
    return file_bytes, result.get("filename", stored_name)


def prepare_all_downloads(
    database_paths: List[str],
    search_params: Dict[str, Any],
    is_paired: bool,
    chain_label: str,
    stats_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    plot_df: Optional[pd.DataFrame],
    plot_meta: Optional[Dict[str, Any]],
    plots_data: List[Dict[str, Any]],
    statistics: Optional[Dict[str, Any]] = None,
    selected_databases: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Bundle results, FASTA, statistics, frequency data, and figures+raw data into one tar.gz.

    For large archives, avoid returning bytes in memory and instead return a filesystem-backed
    `download_url` + `saved_path` (local) so the UI can show a path instead of opening in browser.
    """
    statistics = statistics or {}
    selected_databases = selected_databases or []
    search_params_with_metadata = dict(search_params)
    search_params_with_metadata["selected_databases"] = selected_databases

    stats_zip, stats_filename = prepare_stats_download(
        stats_df, search_params, is_paired, statistics, selected_databases
    )
    frequency_zip, frequency_filename = prepare_frequency_download(
        summary_df,
        plot_df,
        plot_meta,
        search_params,
        is_paired,
        statistics,
        selected_databases,
    )

    full_result = prepare_full_results_download_background(
        database_paths,
        search_params_with_metadata,
        is_paired,
        chain_label,
    )

    fasta_result = prepare_fasta_download_background(
        database_paths,
        search_params_with_metadata,
        is_paired,
        chain_label,
    )

    plots_metadata: Dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "is_paired": is_paired,
        "includes_raw_plotting_data": True,
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
    plots_result = prepare_plots_download_background(
        plots_data,
        plots_metadata,
        include_raw_data=True,
    )
    identifier = _build_search_identifier(
        {
            "search_params": search_params,
            "is_paired": is_paired,
            "chain_label": chain_label,
            "plot_options": plot_meta or {},
        }
    )

    tar_gz_filename = f"ABHunter_all_downloads_{chain_label}_{identifier}.tar.gz"
    token, tar_gz_path, download_url = _get_download_path(tar_gz_filename, "tar.gz")

    staging_dir = _get_tmp_directory() / f"all_downloads_staging_{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    import shutil

    def _stage_artifact(result: Dict[str, Any], *, staging_name: str) -> None:
        if not result or not result.get("success"):
            raise ValueError((result or {}).get("error", "Artifact generation failed"))

        # If bytes were returned (small local case), write them directly.
        for key in ("parquet_data", "data", "zip_data"):
            if key in result and result.get(key) is not None:
                (staging_dir / staging_name).write_bytes(result[key])
                return

        # If a URL was returned, the file should exist on disk in our downloads directory.
        download_url_local = result.get("download_url")
        if download_url_local:
            stored_name = download_url_local.rsplit("/", 1)[-1]
            src_path = _get_download_directory() / stored_name
            if not src_path.exists():
                raise FileNotFoundError(f"Expected generated artifact not found: {src_path}")
            shutil.copyfile(src_path, staging_dir / staging_name)
            return

        raise ValueError("Artifact result did not contain bytes or a download_url")

    try:
        # Write small byte payloads from stats/frequency.
        (staging_dir / stats_filename).write_bytes(stats_zip)
        (staging_dir / frequency_filename).write_bytes(frequency_zip)

        # Stage full results + fasta tarballs + plots archive.
        _stage_artifact(full_result, staging_name=full_result.get("filename", "full_results.tar.gz"))
        _stage_artifact(fasta_result, staging_name=fasta_result.get("filename", "fasta.tar.gz"))
        _stage_artifact(plots_result, staging_name=plots_result.get("filename", "plots.zip"))

        # Create final top-level tar.gz on disk.
        files_to_tar = [f.name for f in sorted(staging_dir.iterdir())]
        import subprocess
        with open(tar_gz_path, "wb") as out_f:
            subprocess.run(
                ["tar", "-cf", "-", "--use-compress-program=pigz"] + files_to_tar,
                cwd=str(staging_dir),
                stdout=out_f,
                check=True,
            )

        os.chmod(tar_gz_path, 0o644)
        file_size_bytes = tar_gz_path.stat().st_size

        # Large archives: keep on disk, return URL/path for the UI.
        if file_size_bytes > LARGE_FILE_THRESHOLD:
            return {
                "success": True,
                "download_url": download_url,
                "filename": tar_gz_filename,
                "file_size_bytes": file_size_bytes,
                "is_large_file": True,
                "token": token,
                # On local runs, download_url is not /downloads/...; saved_path is what the UI should show.
                "saved_path": str(tar_gz_path),
            }

        # Small archives: return bytes for st.download_button, and cleanup disk file.
        file_bytes = tar_gz_path.read_bytes()
        tar_gz_path.unlink(missing_ok=True)
        return {
            "success": True,
            "data": file_bytes,
            "filename": tar_gz_filename,
            "file_size_bytes": file_size_bytes,
            "is_large_file": False,
        }

    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _build_copy_select_columns(schema_column_names: List[str], is_paired: bool) -> str:
    """
    Build the SELECT clause for DuckDB COPY so exported CSV matches formatted download
    (excluded columns removed, renames applied). Column names are quoted for SQL safety.
    """
    exclude = get_exclude_columns()
    rename = get_column_rename_mapping(is_paired)
    parts = []
    for col in schema_column_names:
        if col in exclude:
            continue
        alias = rename.get(col, col)
        q = '"'
        if alias != col:
            parts.append(f'{q}{col}{q} AS {q}{alias}{q}')
        else:
            parts.append(f'{q}{col}{q}')
    return ", ".join(parts)


def _copy_query_to_tar_gz_duckdb(
    conn,
    table_name: str,
    where_clause: str,
    tar_gz_path: Path,
    is_paired: bool,
    search_params: Dict[str, Any],
    csv_filename: str,
) -> None:
    """
    Export query result to CSV, add search parameters JSON, and package both into
    a .tar.gz archive using tar + pigz.
    """
    import subprocess
    import shutil

    df = conn.execute(
        f"SELECT * FROM {table_name} WHERE {where_clause} LIMIT 1"
    ).df()
    schema_names = list(df.columns)
    select_clause = _build_copy_select_columns(schema_names, is_paired)
    if not select_clause:
        raise ValueError("No columns to export after applying exclude list")
    conn.execute("SET preserve_insertion_order = false")
    conn.execute("SET enable_progress_bar = true")

    tmp_dir = _get_tmp_directory()
    staging_dir = tmp_dir / f"results_staging_{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        staged_csv = staging_dir / csv_filename
        sql = (
            f"COPY (SELECT {select_clause} FROM {table_name} WHERE {where_clause}) "
            f"TO ? (HEADER, DELIMITER ',')"
        )
        conn.execute(sql, [str(staged_csv.resolve())])

        params_path = staging_dir / "search_parameters.json"
        params_path.write_text(
            json.dumps(search_params, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

        files_to_tar = [f.name for f in sorted(staging_dir.iterdir())]
        with open(tar_gz_path, "wb") as out_f:
            subprocess.run(
                ["tar", "-cf", "-", "--use-compress-program=pigz"] + files_to_tar,
                cwd=str(staging_dir),
                stdout=out_f,
                check=True,
            )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


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
        
        table_name = "antibodies"

        search_params_with_metadata = dict(search_params)
        identifier = _build_search_identifier({
            "search_params": search_params_with_metadata,
            "chain_label": chain_label,
            "is_paired": is_paired,
        })
        base_filename = f"ABHunter_sequences_{chain_label}_{identifier}"
        csv_filename = f"{base_filename}.csv"
        tar_gz_filename = f"{base_filename}.tar.gz"
        token, tar_gz_path, download_url = _get_download_path(tar_gz_filename, "tar.gz")

        _copy_query_to_tar_gz_duckdb(
            engine.conn,
            table_name,
            where_clause,
            tar_gz_path,
            is_paired,
            dict(search_params),
            csv_filename,
        )
        if hasattr(engine, "conn"):
            engine.conn.close()

        os.chmod(tar_gz_path, 0o644)
        file_size_bytes = tar_gz_path.stat().st_size

        logger.info(f"Background full results download: Completed. File size: {file_size_bytes} bytes.")
        
        # Large files: avoid loading the whole archive into RAM.
        # We serve from disk via `download_url` (nginx in Docker, static/ in local).
        if file_size_bytes > LARGE_FILE_THRESHOLD:
            return {
                'success': True,
                'download_url': download_url,
                'filename': tar_gz_filename,
                'file_size_bytes': file_size_bytes,
                'is_large_file': True,
                'saved_path': str(tar_gz_path),
                'token': token
            }
        else:
            try:
                with open(tar_gz_path, 'rb') as f:
                    file_data = f.read()
                tar_gz_path.unlink()
                return {
                    'success': True,
                    'parquet_data': file_data,
                    'filename': tar_gz_filename,
                    'file_size_bytes': file_size_bytes,
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
        import plotly.io as pio
        
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
        
        plot_filenames = [
            _sanitize_plot_filename(title, idx + 1)
            for idx, (title, _, _) in enumerate(plots)
        ]

        # Create ZIP archive directly on disk (not in memory)
        try:
            with tempfile.TemporaryDirectory(dir=_get_tmp_directory()) as temp_dir:
                temp_dir_path = Path(temp_dir)
                image_paths = [temp_dir_path / name for name in plot_filenames]

                pio.write_images(
                    [figure for _, figure, _ in plots],
                    [str(path) for path in image_paths],
                    format="png",
                    scale=2,
                )

                with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for plot_filename, (_, _, data), image_path in zip(plot_filenames, plots, image_paths):
                        zf.writestr(plot_filename, image_path.read_bytes())
                    
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
                            "image_file": plot_filename,
                        }
                        for plot_filename, (title, _, _) in zip(plot_filenames, plots)
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
        
        # Large files: nginx URL in Docker; Streamlit download_button locally
        if file_size_bytes > LARGE_FILE_THRESHOLD and _use_nginx_download_urls():
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


def _duckdb_copy_fasta(
    conn,
    table_name: str,
    where_clause: str,
    col: str,
    chain_label: str,
    out_path: Path,
) -> int:
    """
    Use DuckDB COPY TO to write a FASTA file natively in C++ — no Python row loop.

    Each matching row becomes two lines: >rownum_label\\nsequence.
    Returns the number of sequences written.
    """
    conn.execute("SET preserve_insertion_order = false")

    full_where = f"{where_clause} AND \"{col}\" IS NOT NULL AND \"{col}\" != ''"

    # Get count first via DuckDB (fast aggregation, no Python file scan)
    count_result = conn.execute(
        f"SELECT COUNT(*) FROM {table_name} WHERE {full_where}"
    ).fetchone()
    seq_count = count_result[0] if count_result else 0
    if seq_count == 0:
        return 0

    logger.info(f"FASTA COPY TO: writing {seq_count:,} {chain_label} sequences to {out_path.name}")

    # Create a temp table with auto-incrementing rowid to avoid ROW_NUMBER() OVER ()
    # which forces a full sort. DuckDB base tables expose rowid; views/parquet do not.
    tmp_tbl = f"_fasta_tmp_{uuid.uuid4().hex[:8]}"
    conn.execute(
        f"CREATE TEMPORARY TABLE {tmp_tbl} AS "
        f"SELECT \"{col}\" FROM {table_name} WHERE {full_where}"
    )
    sql = (
        f"COPY ("
        f"  SELECT '>' || rowid || '_{chain_label}' || chr(10) || \"{col}\" "
        f"  FROM {tmp_tbl}"
        f") TO '{out_path}' (HEADER false, DELIMITER '', QUOTE '')"
    )
    conn.execute(sql)
    conn.execute(f"DROP TABLE IF EXISTS {tmp_tbl}")
    return seq_count


def _native_fasta_to_tar_gz(
    conn,
    table_name: str,
    where_clause: str,
    seq_columns: List[str],
    is_paired: bool,
    chain_label: str,
    tar_gz_path: Path,
    search_params: Dict[str, Any],
) -> Tuple[int, int]:
    """
    Write FASTA via DuckDB COPY TO (C++), then package into a .tar.gz with
    search_parameters.json using tar + pigz.

    Returns (file_size_bytes, total_sequences).
    """
    import time as _time
    import subprocess
    import shutil
    tmp_dir = _get_tmp_directory()
    staging_dir = tmp_dir / f"fasta_staging_{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    total_sequences = 0
    t0 = _time.monotonic()

    try:
        if is_paired:
            heavy_path = staging_dir / "sequences_heavy.fasta"
            light_path = staging_dir / "sequences_light.fasta"

            total_sequences += _duckdb_copy_fasta(
                conn, table_name, where_clause,
                "sequence_alignment_aa_heavy", "heavy", heavy_path,
            )
            total_sequences += _duckdb_copy_fasta(
                conn, table_name, where_clause,
                "sequence_alignment_aa_light", "light", light_path,
            )

        elif len(seq_columns) == 1:
            fasta_path = staging_dir / f"sequences_{chain_label}.fasta"
            total_sequences = _duckdb_copy_fasta(
                conn, table_name, where_clause,
                seq_columns[0], chain_label, fasta_path,
            )

        else:
            for col in seq_columns:
                lbl = "heavy" if "heavy" in col else "light"
                fasta_path = staging_dir / f"sequences_{lbl}.fasta"
                count = _duckdb_copy_fasta(
                    conn, table_name, where_clause, col, lbl, fasta_path,
                )
                if count == 0:
                    fasta_path.unlink(missing_ok=True)
                total_sequences += count

        # Write search parameters JSON
        params_path = staging_dir / "search_parameters.json"
        params_path.write_text(
            json.dumps(search_params, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

        t_fasta = _time.monotonic()
        logger.info(f"FASTA COPY TO completed in {t_fasta - t0:.1f}s. Creating tar.gz for {total_sequences:,} sequences...")

        # tar + pigz: create .tar.gz from staging directory contents
        files_to_tar = [f.name for f in sorted(staging_dir.iterdir())]
        subprocess.run(
            ["tar", "-cf", "-", "--use-compress-program=pigz"] + files_to_tar,
            cwd=str(staging_dir),
            stdout=open(tar_gz_path, "wb"),
            check=True,
        )

        os.chmod(tar_gz_path, 0o644)
        file_size_bytes = tar_gz_path.stat().st_size
        t_gz = _time.monotonic()
        logger.info(
            f"tar.gz completed in {t_gz - t_fasta:.1f}s. "
            f"Total FASTA pipeline: {t_gz - t0:.1f}s, "
            f"File size: {file_size_bytes / 1024 / 1024:.1f} MB"
        )
        return file_size_bytes, total_sequences

    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def prepare_fasta_download_background(
    database_paths: List[str],
    search_params: Dict[str, Any],
    is_paired: bool,
    chain_label: str = None
) -> Dict[str, Any]:
    """
    Prepare FASTA file download in a background process.

    Non-nginx (local): streams directly from DuckDB into a ZIP — no temp CSV,
    no giant in-memory FASTA string.
    Nginx (Docker): uses the legacy CSV+awk path so the file stays on disk for
    nginx to serve.

    Args:
        database_paths: List of database directory paths
        search_params: Search parameters dictionary (will be copied)
        is_paired: Whether this is a paired search
        chain_label: Chain label ("paired", "heavy", or "light")

    Returns:
        Dictionary with keys:
        - 'success': Boolean indicating if operation succeeded
        - 'data': ZIP file content as bytes (non-nginx)
        - 'download_url': URL for nginx download (nginx only)
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
            logging.getLogger(__name__).setLevel(logging.DEBUG)

        from components.search.database_utils import init_search_engine
        from components.search.download_utils import _build_search_identifier

        # Create a new search engine instance in the worker process
        engine = init_search_engine(
            data_dir=database_paths,
            db_path=":memory:"
        )
        logger.info("Background FASTA download: Search engine initialized")
        if hasattr(engine, "configure_threads"):
            engine.configure_threads(24)

        # Copy search params to avoid modifying original
        search_params_copy = search_params.copy()
        selected_databases_formatted = search_params_copy.pop("selected_databases", [])

        # Determine chain label if not provided
        if chain_label is None:
            if is_paired:
                chain_label = "paired"
            elif any(search_params_copy.get(k) for k in ['light_v', 'light_j', 'light_cdr1_length',
                                                          'light_cdr2_length', 'light_cdr3_length']):
                chain_label = "light"
            else:
                chain_label = "heavy"

        unpaired_chain_type = "Heavy" if chain_label == "heavy" else "Light"

        where_clause = _build_where_clause_from_params(
            engine, search_params_copy, is_paired, unpaired_chain_type
        )

        table_name = "antibodies"

        # Infer sequence columns from table schema (LIMIT 1)
        df = engine.conn.execute(
            f"SELECT * FROM {table_name} WHERE {where_clause} LIMIT 1"
        ).df()
        all_columns = list(df.columns)
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
                if hasattr(engine, "conn"):
                    engine.conn.close()
                return {"success": False, "error": "No sequence columns found in database."}
        seq_columns = [c for c in seq_columns if c in all_columns]
        if not seq_columns:
            if hasattr(engine, "conn"):
                engine.conn.close()
            return {"success": False, "error": "No sequence columns found in database."}

        identifier = _build_search_identifier({
            "search_params": search_params_copy,
            "chain_label": chain_label,
            "is_paired": is_paired,
            "selected_databases": sorted(selected_databases_formatted),
        })

        use_nginx = _use_nginx_download_urls()

        # ---- DuckDB COPY TO → FASTA → tar.gz (both nginx and local) ----
        chain_name = "paired" if is_paired else chain_label
        filename = f"ABHunter_FASTA_{chain_name}_{identifier}.tar.gz"

        token, file_path, download_url = _get_download_path(filename, "tar.gz")
        logger.info("Background FASTA download: DuckDB COPY TO → FASTA → tar.gz")

        file_size_bytes, total_sequences = _native_fasta_to_tar_gz(
            engine.conn, table_name, where_clause,
            seq_columns, is_paired, chain_label,
            file_path, dict(search_params),
        )
        if hasattr(engine, "conn"):
            engine.conn.close()

        if total_sequences == 0:
            file_path.unlink(missing_ok=True)
            return {'success': False, 'error': 'No sequences available for selected chain types.'}

        logger.info(f"Background FASTA download: Completed. File size: {file_size_bytes} bytes. Sequences: {total_sequences}")

        if use_nginx:
            # Nginx: keep file on disk, return URL for nginx to serve
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
            # Local: read into memory for st.download_button
            try:
                with open(file_path, 'rb') as f:
                    gz_data = f.read()
                file_path.unlink()
                return {
                    'success': True,
                    'data': gz_data,
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
