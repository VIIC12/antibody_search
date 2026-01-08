import time
import sys
from pathlib import Path
from typing import Dict, Any, List
import warnings
import logging

# Set up paths for worker processes
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "components"))

# Suppress Streamlit caching warnings in worker processes
warnings.filterwarnings("ignore", category=UserWarning, module="streamlit.runtime.caching.cache_data_api")
logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)


def some_heavy_computation(a, b, c):
    """Simple test function for ProcessPoolExecutor."""
    time.sleep(5)
    return a * b * c


def perform_heavy_chain_search(
    database_paths: List[str],
    heavy_v: str = "",
    heavy_cdr3_motif: str = "",
    sample_limit: int = 100
) -> Dict[str, Any]:
    """
    Perform a database search on Heavy chain datasets in a background process.
    
    This function creates a new AntibodySearchEngine instance in the worker process
    (since DuckDB connections can't be pickled) and performs the search.
    
    Args:
        database_paths: List of database directory paths (Heavy chain datasets)
        heavy_v: VH gene to search for (e.g., "IGHV1-2" or "IGHV1-2,IGHV1-3")
        heavy_cdr3_motif: CDR3 motif pattern to search for (e.g., "AR")
        sample_limit: Maximum number of sample results to return (default: 100)
    
    Returns:
        Dictionary with keys:
        - 'sequences_sample_df': DataFrame with sample sequences
        - 'stats_df': DataFrame with statistics per subject
        - 'statistics': Dictionary with search statistics
        - 'total_hits': Total number of hits found
        - 'search_params': Dictionary of search parameters used
    """
    try:
        # Import here to ensure paths are set up correctly in worker process
        from search_engine import AntibodySearchEngine
        from components.search.database_utils import init_search_engine
        from components.search.search_execution import execute_search_with_stats
        
        # Create a new search engine instance in the worker process
        # This is necessary because DuckDB connections can't be pickled
        engine = init_search_engine(
            data_dir=database_paths,
            db_path=":memory:"
        )
        
        # Build search parameters
        search_params = {
            'chain_type': 'Heavy',
            'heavy_v': heavy_v,
            'heavy_d': '',
            'heavy_j': '',
            'heavy_cdr1_length': None,
            'heavy_cdr2_length': None,
            'heavy_cdr3_length': None,
            'heavy_cdr1_motif': '',
            'heavy_cdr2_motif': '',
            'heavy_cdr3_motif': heavy_cdr3_motif,
            'heavy_cdr1_similarity': False,
            'heavy_cdr2_similarity': False,
            'heavy_cdr3_similarity': False,
            'heavy_cdr1_mismatches': 0,
            'heavy_cdr2_mismatches': 0,
            'heavy_cdr3_mismatches': 0,
        }
        
        # Execute the search
        sequences_sample_df, stats_df, statistics = execute_search_with_stats(
            engine=engine,
            search_params=search_params,
            is_paired=False,
            sample_limit=sample_limit
        )
        
        # Extract total hits from statistics
        total_hits = statistics.get('total_hits', 0)
        
        # Close the engine connection
        if hasattr(engine, 'conn'):
            engine.conn.close()
        
        return {
            'sequences_sample_df': sequences_sample_df,
            'stats_df': stats_df,
            'statistics': statistics,
            'total_hits': total_hits,
            'search_params': search_params,
            'success': True
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


def perform_database_search_background(
    database_paths: List[str],
    search_params: Dict[str, Any],
    is_paired: bool,
    sample_limit: int = 100
) -> Dict[str, Any]:
    """
    Perform a database search in a background process.
    Handles paired and unpaired searches.
    
    Args:
        database_paths: List of database directory paths
        search_params: Search parameters dictionary
        is_paired: Whether this is a paired search
        sample_limit: Maximum number of sample results to return (default: 100)
    
    Returns:
        Dictionary with keys:
        - 'success': Boolean indicating if operation succeeded
        - 'sequences_sample_df': DataFrame with sample sequences (if success)
        - 'stats_df': DataFrame with statistics per subject (if success)
        - 'statistics': Dictionary with search statistics (if success)
        - 'search_params': Dictionary of search parameters used (if success)
        - 'error': Error message if failed
    """
    try:
        # Import here to ensure paths are set up correctly in worker process
        from components.search.database_utils import init_search_engine
        from components.search.search_execution import execute_search_with_stats
        
        # Create a new search engine instance in the worker process
        engine = init_search_engine(
            data_dir=database_paths,
            db_path=":memory:"
        )
        
        # Execute the search
        sequences_sample_df, stats_df, statistics = execute_search_with_stats(
            engine=engine,
            search_params=search_params,
            is_paired=is_paired,
            sample_limit=sample_limit
        )
        
        # Close the engine connection
        if hasattr(engine, 'conn'):
            engine.conn.close()
        
        return {
            'success': True,
            'sequences_sample_df': sequences_sample_df,
            'stats_df': stats_df,
            'statistics': statistics,
            'search_params': search_params
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


def perform_dual_unpaired_search_background(
    database_paths: List[str],
    heavy_search_params: Dict[str, Any],
    light_search_params: Dict[str, Any],
    sample_limit: int = 100
) -> Dict[str, Any]:
    """
    Perform dual unpaired searches (Heavy + Light) in a background process.
    
    Args:
        database_paths: List of database directory paths
        heavy_search_params: Heavy chain search parameters
        light_search_params: Light chain search parameters
        sample_limit: Maximum number of sample results to return (default: 100)
    
    Returns:
        Dictionary with keys:
        - 'success': Boolean indicating if operation succeeded
        - 'heavy': Dictionary with heavy chain results (if success)
        - 'light': Dictionary with light chain results (if success)
        - 'error': Error message if failed
    """
    try:
        # Import here to ensure paths are set up correctly in worker process
        from components.search.database_utils import init_search_engine
        from components.search.search_execution import execute_search_with_stats
        
        # Create a new search engine instance in the worker process
        engine = init_search_engine(
            data_dir=database_paths,
            db_path=":memory:"
        )
        
        # Execute heavy chain search
        heavy_sequences_df, heavy_stats_df, heavy_statistics = execute_search_with_stats(
            engine=engine,
            search_params=heavy_search_params,
            is_paired=False,
            sample_limit=sample_limit
        )
        
        # Execute light chain search
        light_sequences_df, light_stats_df, light_statistics = execute_search_with_stats(
            engine=engine,
            search_params=light_search_params,
            is_paired=False,
            sample_limit=sample_limit
        )
        
        # Close the engine connection
        if hasattr(engine, 'conn'):
            engine.conn.close()
        
        return {
            'success': True,
            'heavy': {
                'sequences_sample_df': heavy_sequences_df,
                'stats_df': heavy_stats_df,
                'statistics': heavy_statistics,
                'search_params': heavy_search_params
            },
            'light': {
                'sequences_sample_df': light_sequences_df,
                'stats_df': light_stats_df,
                'statistics': light_statistics,
                'search_params': light_search_params
            }
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


def prepare_fasta_download_background(
    database_paths: List[str],
    heavy_v: str = "",
    heavy_cdr3_motif: str = "",
    include_heavy: bool = True,
    include_light: bool = False
) -> Dict[str, Any]:
    """
    Prepare FASTA file download in a background process.
    
    This function performs a full search (no limit) and generates FASTA content
    for download. This is a heavy operation that should run in the background.
    
    Args:
        database_paths: List of database directory paths (Heavy chain datasets)
        heavy_v: VH gene to search for (e.g., "IGHV1-2" or "IGHV1-2,IGHV1-3")
        heavy_cdr3_motif: CDR3 motif pattern to search for (e.g., "AR")
        include_heavy: Whether to include heavy chain sequences (default: True)
        include_light: Whether to include light chain sequences (default: False)
    
    Returns:
        Dictionary with keys:
        - 'success': Boolean indicating if operation succeeded
        - 'content': FASTA file content as string
        - 'filename': Suggested filename for download
        - 'sequence_count': Number of sequences in FASTA file
        - 'file_size_bytes': Size of FASTA content in bytes
        - 'error': Error message if failed
    """
    try:
        # Import here to ensure paths are set up correctly in worker process
        from search_engine import AntibodySearchEngine
        from components.search.database_utils import init_search_engine
        from components.search.search_execution import execute_search
        from components.search.download_utils import generate_fasta_content, _build_search_identifier, _serialize_search_params
        import json
        
        # Create a new search engine instance in the worker process
        engine = init_search_engine(
            data_dir=database_paths,
            db_path=":memory:"
        )
        
        # Build search parameters
        search_params = {
            'chain_type': 'Heavy',
            'heavy_v': heavy_v,
            'heavy_d': '',
            'heavy_j': '',
            'heavy_cdr1_length': None,
            'heavy_cdr2_length': None,
            'heavy_cdr3_length': None,
            'heavy_cdr1_motif': '',
            'heavy_cdr2_motif': '',
            'heavy_cdr3_motif': heavy_cdr3_motif,
            'heavy_cdr1_similarity': False,
            'heavy_cdr2_similarity': False,
            'heavy_cdr3_similarity': False,
            'heavy_cdr1_mismatches': 0,
            'heavy_cdr2_mismatches': 0,
            'heavy_cdr3_mismatches': 0,
        }
        
        # Execute full search (no limit) - this is the heavy operation
        sequences_full_df, _, _ = execute_search(
            engine=engine,
            search_params=search_params,
            is_paired=False,
            full_results=True,
            limit=None  # Get ALL results
        )
        
        if sequences_full_df.empty:
            return {
                'success': False,
                'error': 'No sequences found to download.'
            }
        
        # Generate FASTA content
        fasta_body = generate_fasta_content(
            sequences_full_df,
            is_paired=False,
            include_heavy=include_heavy,
            include_light=include_light
        )
        
        if not fasta_body:
            return {
                'success': False,
                'error': 'No sequences available for selected chain types.'
            }
        
        # Add metadata header
        selected_dbs_sorted = sorted(database_paths)
        metadata_payload = {
            "search_params": json.loads(_serialize_search_params(search_params)),
            "selected_databases": selected_dbs_sorted,
        }
        metadata_line = f"# Search Parameters: {json.dumps(metadata_payload, sort_keys=True)}"
        fasta_content = "\n".join([metadata_line, fasta_body])
        
        # Generate filename
        chain_parts = []
        if include_heavy:
            chain_parts.append("heavy")
        if include_light:
            chain_parts.append("light")
        chain_str = "_".join(chain_parts) if len(chain_parts) > 1 else chain_parts[0]
        identifier = _build_search_identifier({
            "search_params": search_params,
            "include_heavy": include_heavy,
            "include_light": include_light,
            "selected_databases": selected_dbs_sorted,
        })
        filename = f"ABHunter_{chain_str}_chain_{identifier}.fasta"
        
        sequence_count = fasta_body.count('>')
        file_size_bytes = len(fasta_content.encode('utf-8'))
        
        # Close the engine connection
        if hasattr(engine, 'conn'):
            engine.conn.close()
        
        return {
            'success': True,
            'content': fasta_content,
            'filename': filename,
            'sequence_count': sequence_count,
            'file_size_bytes': file_size_bytes,
            'total_sequences': len(sequences_full_df)
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }
