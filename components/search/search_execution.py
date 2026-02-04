"""
Search execution utilities for antibody search.

This module provides functions to execute searches and handle
search parameter validation and extraction.
"""

from typing import Dict, Any, Tuple, Optional
import pandas as pd

from search_engine import AntibodySearchEngine
from components.search.search_forms import validate_gene_range, validate_gene_range_oas


def validate_search_criteria(search_params: Dict[str, Any], is_paired: bool) -> Tuple[bool, Optional[str]]:
    """
    Validate that at least one search criterion is provided, that gene inputs
    are within allowed ranges, and that no OAS-disallowed genes are used.
    
    Args:
        search_params: Dictionary of search parameters
        is_paired: Whether this is a paired search
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Validate gene ranges when present (invalid genes => exit search)
    for key, gene_type in [
        ("heavy_v", "ighv"),
        ("heavy_d", "ighd"),
        ("heavy_j", "ighj"),
        ("light_v", "light_v"),
        ("light_j", "light_j"),
    ]:
        val = search_params.get(key)
        if val and isinstance(val, str) and val.strip():
            ok, err = validate_gene_range(val.strip(), gene_type)
            if not ok and err:
                return False, err

    # OAS dataset: reject genes not present in OAS (Heavy V8; Light V L11 [unpaired] or L1,L11 [paired]; Light J L4,L5)
    for key, gene_type in [("heavy_v", "ighv"), ("light_v", "light_v"), ("light_j", "light_j")]:
        val = search_params.get(key)
        if val and isinstance(val, str) and val.strip():
            ok, err = validate_gene_range_oas(val.strip(), gene_type, is_paired)
            if not ok and err:
                return False, err

    if is_paired:
        # Check paired parameters
        has_criteria = any([
            search_params.get('heavy_v'), search_params.get('heavy_d'), search_params.get('heavy_j'),
            search_params.get('heavy_cdr1_length'), search_params.get('heavy_cdr2_length'),
            search_params.get('heavy_cdr3_length'),
            search_params.get('heavy_cdr1_motif'), search_params.get('heavy_cdr2_motif'),
            search_params.get('heavy_cdr3_motif'),
            search_params.get('light_v'), search_params.get('light_j'),
            search_params.get('light_cdr1_length'), search_params.get('light_cdr2_length'),
            search_params.get('light_cdr3_length'),
            search_params.get('light_cdr1_motif'), search_params.get('light_cdr2_motif'),
            search_params.get('light_cdr3_motif')
        ])
    else:
        chain_type = search_params.get('chain_type', 'Heavy')
        if chain_type == 'Light':
            has_criteria = any([
                search_params.get('light_v'),
                search_params.get('light_j'),
                search_params.get('light_cdr1_length'),
                search_params.get('light_cdr2_length'),
                search_params.get('light_cdr3_length'),
                search_params.get('light_cdr1_motif'),
                search_params.get('light_cdr2_motif'),
                search_params.get('light_cdr3_motif')
            ])
        else:
            has_criteria = any([
                search_params.get('heavy_v'),
                search_params.get('heavy_d'),
                search_params.get('heavy_j'),
                search_params.get('heavy_cdr1_length'),
                search_params.get('heavy_cdr2_length'),
                search_params.get('heavy_cdr3_length'),
                search_params.get('heavy_cdr1_motif'),
                search_params.get('heavy_cdr2_motif'),
                search_params.get('heavy_cdr3_motif')
            ])
    
    if not has_criteria:
        return False, "⚠️ Please enter at least one search criterion"
    
    return True, None


def build_search_kwargs(search_params: Dict[str, Any], is_paired: bool) -> Dict[str, Any]:
    """
    Build keyword arguments for search engine from search_params.
    
    Args:
        search_params: Dictionary of search parameters from form
        is_paired: Whether this is a paired search
        
    Returns:
        Dictionary of keyword arguments for engine.search()
    """
    if is_paired:
        return {
            'chain_mode': 'paired',
            # Heavy chain parameters
            'heavy_v': search_params.get('heavy_v', ''),
            'heavy_d': search_params.get('heavy_d', ''),
            'heavy_j': search_params.get('heavy_j', ''),
            'heavy_cdr1_length': search_params.get('heavy_cdr1_length')
            if search_params.get('heavy_cdr1_length') is not None else None,
            'heavy_cdr2_length': search_params.get('heavy_cdr2_length')
            if search_params.get('heavy_cdr2_length') is not None else None,
            'heavy_cdr3_length': search_params.get('heavy_cdr3_length')
            if search_params.get('heavy_cdr3_length') is not None else None,
            'heavy_cdr1_motif': search_params.get('heavy_cdr1_motif', ''),
            'heavy_cdr2_motif': search_params.get('heavy_cdr2_motif', ''),
            'heavy_cdr3_motif': search_params.get('heavy_cdr3_motif', ''),
            'heavy_cdr1_similarity': search_params.get('heavy_cdr1_similarity', False),
            'heavy_cdr2_similarity': search_params.get('heavy_cdr2_similarity', False),
            'heavy_cdr3_similarity': search_params.get('heavy_cdr3_similarity', False),
            'heavy_cdr1_mismatches': search_params.get('heavy_cdr1_mismatches', 2),
            'heavy_cdr2_mismatches': search_params.get('heavy_cdr2_mismatches', 2),
            'heavy_cdr3_mismatches': search_params.get('heavy_cdr3_mismatches', 2),
            # Light chain parameters
            'light_v': search_params.get('light_v', ''),
            'light_j': search_params.get('light_j', ''),
            'light_cdr1_length': search_params.get('light_cdr1_length')
            if search_params.get('light_cdr1_length') is not None else None,
            'light_cdr2_length': search_params.get('light_cdr2_length')
            if search_params.get('light_cdr2_length') is not None else None,
            'light_cdr3_length': search_params.get('light_cdr3_length')
            if search_params.get('light_cdr3_length') is not None else None,
            'light_cdr1_motif': search_params.get('light_cdr1_motif', ''),
            'light_cdr2_motif': search_params.get('light_cdr2_motif', ''),
            'light_cdr3_motif': search_params.get('light_cdr3_motif', ''),
            'light_cdr1_similarity': search_params.get('light_cdr1_similarity', False),
            'light_cdr2_similarity': search_params.get('light_cdr2_similarity', False),
            'light_cdr3_similarity': search_params.get('light_cdr3_similarity', False),
            'light_cdr1_mismatches': search_params.get('light_cdr1_mismatches', 2),
            'light_cdr2_mismatches': search_params.get('light_cdr2_mismatches', 2),
            'light_cdr3_mismatches': search_params.get('light_cdr3_mismatches', 2),
        }
    else:
        chain_type = search_params.get('chain_type', 'Heavy')
        if chain_type == 'Light':
            return {
                'chain_mode': 'light',
                'light_v': search_params.get('light_v', ''),
                'light_j': search_params.get('light_j', ''),
                'light_cdr1_length': search_params.get('light_cdr1_length')
                if search_params.get('light_cdr1_length') is not None else None,
                'light_cdr2_length': search_params.get('light_cdr2_length')
                if search_params.get('light_cdr2_length') is not None else None,
                'light_cdr3_length': search_params.get('light_cdr3_length')
                if search_params.get('light_cdr3_length') is not None else None,
                'light_cdr1_motif': search_params.get('light_cdr1_motif', ''),
                'light_cdr2_motif': search_params.get('light_cdr2_motif', ''),
                'light_cdr3_motif': search_params.get('light_cdr3_motif', ''),
                'light_cdr1_similarity': search_params.get('light_cdr1_similarity', False),
                'light_cdr2_similarity': search_params.get('light_cdr2_similarity', False),
                'light_cdr3_similarity': search_params.get('light_cdr3_similarity', False),
                'light_cdr1_mismatches': search_params.get('light_cdr1_mismatches', 2),
                'light_cdr2_mismatches': search_params.get('light_cdr2_mismatches', 2),
                'light_cdr3_mismatches': search_params.get('light_cdr3_mismatches', 2),
            }
        else:
            return {
                'chain_mode': 'heavy',
                'heavy_v': search_params.get('heavy_v', ''),
                'heavy_d': search_params.get('heavy_d', ''),
                'heavy_j': search_params.get('heavy_j', ''),
                'heavy_cdr1_length': search_params.get('heavy_cdr1_length')
                if search_params.get('heavy_cdr1_length') is not None else None,
                'heavy_cdr2_length': search_params.get('heavy_cdr2_length')
                if search_params.get('heavy_cdr2_length') is not None else None,
                'heavy_cdr3_length': search_params.get('heavy_cdr3_length')
                if search_params.get('heavy_cdr3_length') is not None else None,
                'heavy_cdr1_motif': search_params.get('heavy_cdr1_motif', ''),
                'heavy_cdr2_motif': search_params.get('heavy_cdr2_motif', ''),
                'heavy_cdr3_motif': search_params.get('heavy_cdr3_motif', ''),
                'heavy_cdr1_similarity': search_params.get('heavy_cdr1_similarity', False),
                'heavy_cdr2_similarity': search_params.get('heavy_cdr2_similarity', False),
                'heavy_cdr3_similarity': search_params.get('heavy_cdr3_similarity', False),
                'heavy_cdr1_mismatches': search_params.get('heavy_cdr1_mismatches', 2),
                'heavy_cdr2_mismatches': search_params.get('heavy_cdr2_mismatches', 2),
                'heavy_cdr3_mismatches': search_params.get('heavy_cdr3_mismatches', 2),
            }


def execute_search(
    engine: AntibodySearchEngine,
    search_params: Dict[str, Any],
    is_paired: bool,
    full_results: bool = True,
    limit: Optional[int] = None
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Execute search with given parameters.
    
    Args:
        engine: Search engine instance
        search_params: Dictionary of search parameters from form
        is_paired: Whether this is a paired search
        full_results: Whether to return full sequence data
        limit: Maximum number of results to return
        
    Returns:
        Tuple of (results_df, stats_df, statistics_dict)
    """
    kwargs = build_search_kwargs(search_params, is_paired)
    kwargs['full_results'] = full_results
    if limit is not None:
        kwargs['limit'] = limit
    
    return engine.search(**kwargs)


def execute_search_with_stats(
    engine: AntibodySearchEngine,
    search_params: Dict[str, Any],
    is_paired: bool,
    sample_limit: int = 100
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Execute search and get both sample results and statistics.
    Now runs the search only once since stats_df is always returned.
    
    Args:
        engine: Search engine instance
        search_params: Dictionary of search parameters from form
        is_paired: Whether this is a paired search
        sample_limit: Maximum number of sample results to return
        
    Returns:
        Tuple of (sequences_sample_df, stats_df, statistics_dict)
    """
    # Enable DuckDB progress bar for terminal output only
    # (Streamlit UI will use spinner, not progress bar)
    engine.conn.execute("SET enable_progress_bar = true;")
    
    # Get sample sequences and statistics in one call
    # stats_df is now always returned, so we don't need a second call
    sequences_sample_df, stats_df, statistics = execute_search(
        engine, search_params, is_paired,
        full_results=True, limit=sample_limit
    )
    
    return sequences_sample_df, stats_df, statistics

