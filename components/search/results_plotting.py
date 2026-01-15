"""
Results plotting component for visualizing search results.

This module provides functions to create Plotly charts for search results,
including CDR length distributions, gene distributions, and other analyses.
"""

import io
import json
import re
import zipfile

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from typing import Any, Callable, Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from datetime import datetime
from search_engine import AntibodySearchEngine

# Global configuration for plotting limits
# Maximum number of sequences to fetch for CDR length, V/D/J gene distribution plots
# This limit balances accuracy of distributions with memory usage and query performance
PLOTTING_DATA_LIMIT = 1000000

# Threshold for showing warning message about large result sets
# If total_hits exceeds this, a message is shown indicating plots use a sample
PLOTTING_WARNING_THRESHOLD = 100000


def render_results_plots(
    sequences_sample_df: pd.DataFrame,
    statistics: Dict[str, Any],
    is_paired: bool,
    search_params: Dict[str, Any],
    engine: AntibodySearchEngine,
    show_heading: bool = True
) -> None:
    """
    Render plots for search results based on available data and search parameters.
    Uses optimized queries to fetch only the columns needed for plotting.
    Caches plotting data to avoid re-fetching on every render.
    
    Args:
        sequences_sample_df: Sample sequences dataframe (for display only)
        statistics: Statistics dictionary
        is_paired: Whether this is a paired search
        search_params: Search parameters dictionary
        engine: Search engine instance to fetch all results
        show_heading: Whether to render the section heading inside this function
    """
    if sequences_sample_df.empty:
        return
    
    if show_heading:
        st.markdown("### 📊 Result Distributions")
    
    # Check if we have a very large result set (will be sampled)
    total_hits = statistics.get('total_hits', 0)
    
    if total_hits > PLOTTING_WARNING_THRESHOLD:
        st.info(
            f"ℹ️ **Large result set detected** ({total_hits:,} hits). "
            f"Plots are based on a sample of up to {PLOTTING_DATA_LIMIT:,} sequences for performance. "
            f"Distributions should be representative of the full dataset."
        )
    
    # Determine unpaired chain type
    unpaired_chain_type = _get_unpaired_chain_type(search_params) if not is_paired else "Heavy"
    
    # Create cache key based on search parameters
    import json
    cache_key_seed = {
        "search_params": search_params,
        "is_paired": is_paired,
        "unpaired_chain_type": unpaired_chain_type,
        "total_hits": total_hits
    }
    cache_key = f"plotting_data_{abs(hash(json.dumps(cache_key_seed, sort_keys=True, default=str)))}"
    
    # Check if we have cached plotting data for this search
    cached_data = st.session_state.get(cache_key)
    
    if cached_data is not None:
        # Use cached data - no need to fetch again
        sequences_full_df = cached_data
    else:
        # Fetch only the columns needed for plotting (much faster)
        with st.spinner("Loading data for plotting..."):
            sequences_full_df = fetch_plotting_data(engine, search_params, is_paired, unpaired_chain_type)
        
        # Cache the fetched data
        st.session_state[cache_key] = sequences_full_df
    
    if sequences_full_df.empty:
        st.info("No results available for plotting.")
        return
    
    collected_plots: List[Tuple[str, go.Figure, Optional[pd.DataFrame]]] = []
    
    # Determine which plots to show based on search type and parameters
    if is_paired:
        render_paired_plots(sequences_full_df, search_params, collected_plots)
    else:
        render_unpaired_plots(
            sequences_full_df,
            search_params,
            collected_plots,
            chain_type=unpaired_chain_type,
            engine=engine,
            statistics=statistics
        )

    subject_plot_entry = st.session_state.get("latest_subject_hits_plot")
    if subject_plot_entry:
        if len(subject_plot_entry) == 3:
            plot_name, plot_figure, plot_data = subject_plot_entry
        else:
            plot_name, plot_figure = subject_plot_entry[:2]
            plot_data = None
        plot_data_copy = plot_data.copy() if isinstance(plot_data, pd.DataFrame) else plot_data
        collected_plots.append((plot_name, go.Figure(plot_figure), plot_data_copy))

    if collected_plots:
        # Render async download buttons (Option C style)
        _render_plot_download_buttons(
            collected_plots,
            search_params,
            statistics,
            is_paired,
            unpaired_chain_type
        )


def _render_plot_download_buttons(
    collected_plots: List[Tuple[str, go.Figure, Optional[pd.DataFrame]]],
    search_params: Dict[str, Any],
    statistics: Dict[str, Any],
    is_paired: bool,
    unpaired_chain_type: str
) -> None:
    """
    Render async download buttons for plots (Option C style).
    Button shows status and transforms into download button when ready.
    """
    import concurrent.futures
    import time
    from streamlit_autorefresh import st_autorefresh
    from components.search.download_utils import prepare_plots_download_background
    
    # Inject CSS for spinner animation
    st.markdown("""
    <style>
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    .spinner-dark {
        border: 2px solid rgba(255, 255, 255, 0.2);
        border-top: 2px solid #ffffff;
        border-radius: 50%;
        width: 16px;
        height: 16px;
        animation: spin 1s linear infinite;
        display: inline-block;
    }
    </style>
    """, unsafe_allow_html=True)
    
    download_key_seed = {
        "search_params": search_params,
        "is_paired": is_paired,
        "total_hits": statistics.get("total_hits"),
    }
    seed_hash = abs(hash(str(download_key_seed)))
    download_key = f"plot_zip_{seed_hash}"
    chain_label = "paired" if is_paired else unpaired_chain_type.lower()
    
    # Session state keys for async plot downloads
    def _get_state_keys(include_raw: bool) -> Dict[str, str]:
        suffix = "figures_raw" if include_raw else "figures"
        return {
            "future": f"{download_key}_future_{suffix}",
            "status": f"{download_key}_status_{suffix}",
            "result": f"{download_key}_result_{suffix}",
            "start_time": f"{download_key}_start_time_{suffix}",
        }
    
    # Initialize session state for both buttons
    for include_raw in [False, True]:
        keys = _get_state_keys(include_raw)
        if keys["status"] not in st.session_state:
            st.session_state[keys["status"]] = "idle"
        if keys["result"] not in st.session_state:
            st.session_state[keys["result"]] = None
        if keys["start_time"] not in st.session_state:
            st.session_state[keys["start_time"]] = None
    
    # Get executor (cached)
    @st.cache_resource
    def get_plots_executor():
        return concurrent.futures.ProcessPoolExecutor(max_workers=2)
    
    executor = get_plots_executor()
    
    # Check task status (non-blocking)
    def check_plots_status(include_raw: bool):
        keys = _get_state_keys(include_raw)
        future = st.session_state.get(keys["future"])
        if future is not None and future.done():
            try:
                result = future.result()
                st.session_state[keys["future"]] = None
                st.session_state[keys["result"]] = result
                if result.get('success'):
                    st.session_state[keys["status"]] = "completed"
                    st.toast("✅ Plot archive is ready for download!", icon="✅")
                else:
                    st.session_state[keys["status"]] = "failed"
                return result
            except Exception as e:
                st.session_state[keys["future"]] = None
                st.session_state[keys["status"]] = "failed"
                st.session_state[keys["result"]] = {'success': False, 'error': str(e)}
        return None
    
    # Check status on every run
    check_plots_status(False)  # Figures only
    check_plots_status(True)   # Figures + Raw Data
    
    # Auto-refresh when any task is running
    status_figures = st.session_state[_get_state_keys(False)["status"]]
    status_raw = st.session_state[_get_state_keys(True)["status"]]
    if status_figures == "running" or status_raw == "running":
        st_autorefresh(interval=2000, key=f"plots_refresh_{download_key}")
    
    # Estimate phase based on elapsed time
    def estimate_phase(elapsed: float) -> str:
        if elapsed < 3:
            return "Initializing..."
        elif elapsed < 10:
            return "Rendering plots..."
        elif elapsed < 30:
            return "Creating archive..."
        else:
            return "Finalizing..."
    
    # Render buttons
    col_figures, col_raw, _spacer = st.columns([1.5, 1.5, 7])
    
    # Button 1: Download Figures
    with col_figures:
        status = st.session_state[_get_state_keys(False)["status"]]
        keys = _get_state_keys(False)
        
        if status == "idle":
            if st.button(
                "📥 Download Figures",
                key=f"{download_key}_button_figures",
                use_container_width=True
            ):
                # Serialize plots for background processing
                plots_data = []
                for title, figure, data in collected_plots:
                    plot_info = {
                        'title': title,
                        'figure_dict': figure.to_dict(),
                        'data': None
                    }
                    if data is not None:
                        if isinstance(data, pd.DataFrame):
                            plot_info['data'] = data.to_dict('records')  # Convert to list of dicts
                        elif isinstance(data, pd.Series):
                            plot_info['data'] = data.to_dict()
                        else:
                            plot_info['data'] = data
                    plots_data.append(plot_info)
                
                # Build metadata
                search_metadata = build_search_metadata(
                    search_params,
                    statistics,
                    is_paired,
                    include_raw_data=False
                )
                
                # Submit background task
                future = executor.submit(
                    prepare_plots_download_background,
                    plots_data,
                    search_metadata,
                    include_raw_data=False
                )
                st.session_state[keys["future"]] = future
                st.session_state[keys["start_time"]] = time.time()
                st.session_state[keys["status"]] = "running"
                st.rerun()
        
        elif status == "running":
            elapsed = time.time() - st.session_state[keys["start_time"]] if st.session_state[keys["start_time"]] else 0
            phase = estimate_phase(elapsed)
            
            # Custom button with CSS spinner
            st.markdown(f"""
            <div style="width: 100%;">
                <button disabled style="
                    width: 100%;
                    padding: 0.5rem 1rem;
                    background-color: rgb(49, 51, 63);
                    color: rgb(250, 250, 250);
                    border: 1px solid rgb(49, 51, 63);
                    border-radius: 0.25rem;
                    cursor: not-allowed;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                    font-size: 0.875rem;
                ">
                    <div class="spinner-dark"></div>
                    <span>{phase}</span>
                </button>
            </div>
            """, unsafe_allow_html=True)
        
        elif status == "completed":
            result = st.session_state[keys["result"]]
            if result and result.get('success'):
                file_size_mb = result.get('file_size_bytes', 0) / 1024 / 1024
                plot_count = result.get('plot_count', 0)
                
                # The original button becomes the download button
                st.download_button(
                    label=f"✅ Download Figures ({file_size_mb:.2f} MB)",
                    data=result.get('zip_data', b''),
                    file_name=result.get('filename', 'plots.zip'),
                    mime="application/zip",
                    use_container_width=True,
                    type="primary",
                    key=f"download_{download_key}_figures"
                )
            else:
                st.button("❌ Generation Failed", disabled=True, key=f"{download_key}_failed_figures", use_container_width=True)
                error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
                st.error(f"❌ {error_msg}")
        
        elif status == "failed":
            result = st.session_state[keys["result"]]
            error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
            if st.button("🔄 Retry", key=f"{download_key}_retry_figures"):
                st.session_state[keys["status"]] = "idle"
                st.session_state[keys["result"]] = None
                st.session_state[keys["start_time"]] = None
                st.rerun()
            else:
                st.error(f"❌ {error_msg}")
    
    # Button 2: Download Figures + Raw Data
    with col_raw:
        status = st.session_state[_get_state_keys(True)["status"]]
        keys = _get_state_keys(True)
        
        if status == "idle":
            if st.button(
                "📥 Download Figures + Raw Data",
                key=f"{download_key}_button_raw",
                use_container_width=True
            ):
                # Serialize plots for background processing
                plots_data = []
                for title, figure, data in collected_plots:
                    plot_info = {
                        'title': title,
                        'figure_dict': figure.to_dict(),
                        'data': None
                    }
                    if data is not None:
                        if isinstance(data, pd.DataFrame):
                            plot_info['data'] = data.to_dict('records')  # Convert to list of dicts
                        elif isinstance(data, pd.Series):
                            plot_info['data'] = data.to_dict()
                        else:
                            plot_info['data'] = data
                    plots_data.append(plot_info)
                
                # Build metadata
                search_metadata = build_search_metadata(
                    search_params,
                    statistics,
                    is_paired,
                    include_raw_data=True
                )
                
                # Submit background task
                future = executor.submit(
                    prepare_plots_download_background,
                    plots_data,
                    search_metadata,
                    include_raw_data=True
                )
                st.session_state[keys["future"]] = future
                st.session_state[keys["start_time"]] = time.time()
                st.session_state[keys["status"]] = "running"
                st.rerun()
        
        elif status == "running":
            elapsed = time.time() - st.session_state[keys["start_time"]] if st.session_state[keys["start_time"]] else 0
            phase = estimate_phase(elapsed)
            
            # Custom button with CSS spinner
            st.markdown(f"""
            <div style="width: 100%;">
                <button disabled style="
                    width: 100%;
                    padding: 0.5rem 1rem;
                    background-color: rgb(49, 51, 63);
                    color: rgb(250, 250, 250);
                    border: 1px solid rgb(49, 51, 63);
                    border-radius: 0.25rem;
                    cursor: not-allowed;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                    font-size: 0.875rem;
                ">
                    <div class="spinner-dark"></div>
                    <span>{phase}</span>
                </button>
            </div>
            """, unsafe_allow_html=True)
        
        elif status == "completed":
            result = st.session_state[keys["result"]]
            if result and result.get('success'):
                file_size_mb = result.get('file_size_bytes', 0) / 1024 / 1024
                plot_count = result.get('plot_count', 0)
                
                # The original button becomes the download button
                st.download_button(
                    label=f"✅ Download Figures + Raw Data ({file_size_mb:.2f} MB)",
                    data=result.get('zip_data', b''),
                    file_name=result.get('filename', 'plots_raw.zip'),
                    mime="application/zip",
                    use_container_width=True,
                    type="primary",
                    key=f"download_{download_key}_raw"
                )
            else:
                st.button("❌ Generation Failed", disabled=True, key=f"{download_key}_failed_raw", use_container_width=True)
                error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
                st.error(f"❌ {error_msg}")
        
        elif status == "failed":
            result = st.session_state[keys["result"]]
            error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
            if st.button("🔄 Retry", key=f"{download_key}_retry_raw"):
                st.session_state[keys["status"]] = "idle"
                st.session_state[keys["result"]] = None
                st.session_state[keys["start_time"]] = None
                st.rerun()
            else:
                st.error(f"❌ {error_msg}")


def _get_unpaired_chain_type(search_params: Dict[str, Any]) -> str:
    """Return 'Heavy' or 'Light' for unpaired search parameters."""
    chain_type = search_params.get('chain_type') or search_params.get('unpaired_chain_type') or "Heavy"
    chain_type = chain_type.capitalize()
    if chain_type not in ("Heavy", "Light"):
        chain_type = "Heavy"
    return chain_type


def fetch_plotting_data(
    engine: AntibodySearchEngine,
    search_params: Dict[str, Any],
    is_paired: bool,
    unpaired_chain_type: str = "Heavy"
) -> pd.DataFrame:
    """
    Fetch data for plotting using the same search logic as the main search.
    This ensures ALL search parameters (motifs, similarity, mismatches, etc.) are applied identically.
    After fetching results, filters to only the columns needed for plotting.
    Limits results to prevent memory exhaustion on large result sets.
    
    Args:
        engine: Search engine instance
        search_params: Search parameters dictionary
        is_paired: Whether this is a paired search
        unpaired_chain_type: Chain type for unpaired searches ("Heavy" or "Light")
        
    Returns:
        DataFrame with only the columns needed for plotting (max 100k rows for performance)
    """
    # Use the search engine's search method to get results with identical filtering
    # This ensures ALL search parameters (including motifs, similarity, mismatches, etc.) are applied identically
    from components.search.search_execution import build_search_kwargs
    
    # Build search kwargs from search_params (same as main search)
    search_kwargs = build_search_kwargs(search_params, is_paired)
    
    # Add chain_mode for paired searches
    if is_paired:
        search_kwargs['chain_mode'] = 'paired'
    else:
        search_kwargs['chain_mode'] = unpaired_chain_type.lower()
    
    # Execute search with full_results=True but limit to plotting limit
    # This ensures we use the exact same WHERE clause as the main search
    sequences_df, _, _ = engine.search(
        **search_kwargs,
        full_results=True,
        limit=PLOTTING_DATA_LIMIT
    )
    
    if sequences_df.empty:
        return pd.DataFrame()
    
    # Determine which columns we need for plotting
    if is_paired:
        # Paired: need both heavy and light chain columns - use schema to get actual column names
        columns = []
        # Get CDR length columns
        for base_col in ['cdr1_length', 'cdr2_length', 'cdr3_length']:
            if base_col in engine.schema.get('length_columns', {}):
                columns.extend(engine.schema['length_columns'][base_col])
        # Get gene call columns
        for base_col in ['v_call', 'd_call', 'j_call']:
            if base_col in engine.schema.get('chain_columns', {}):
                columns.extend(engine.schema['chain_columns'][base_col])
    else:
        # Unpaired: need standard columns - use schema to get actual column names
        columns = []
        # Get CDR length columns
        for base_col in ['cdr1_length', 'cdr2_length', 'cdr3_length']:
            if base_col in engine.schema.get('length_columns', {}):
                columns.extend(engine.schema['length_columns'][base_col])
        # Get gene call columns
        for base_col in ['v_call', 'd_call', 'j_call']:
            if base_col in engine.schema.get('chain_columns', {}):
                columns.extend(engine.schema['chain_columns'][base_col])
    
    # Filter to only include columns that exist in the result DataFrame
    available_columns = [col for col in columns if col in sequences_df.columns]
    
    if not available_columns:
        return pd.DataFrame()
    
    # Return only the columns needed for plotting
    return sequences_df[available_columns]


def build_plotting_where_clause(
    engine: AntibodySearchEngine,
    search_params: Dict[str, Any],
    is_paired: bool,
    unpaired_chain_type: str = "Heavy"
) -> str:
    """
    Build WHERE clause from search parameters for plotting queries.
    Reuses the search engine's query building logic.
    
    Args:
        engine: Search engine instance
        search_params: Search parameters dictionary
        is_paired: Whether this is a paired search
        
    Returns:
        WHERE clause string
    """
    # We need to execute a search to get the WHERE clause, but we can do it
    # with full_results=False to avoid loading data
    # However, this still builds the query. Let's build it manually instead.
    
    conditions = []
    
    if is_paired:
        # Heavy chain conditions - use schema chain_columns
        if search_params.get('heavy_v'):
            heavy_v = search_params['heavy_v']
            separator = ',' if ',' in heavy_v else '|'
            if separator in heavy_v:
                heavy_v_conditions = []
                for g in heavy_v.split(separator):
                    for col in engine.schema['chain_columns']['v_call']:
                        if '_heavy' in col:
                            heavy_v_conditions.append(engine._build_gene_pattern(col, g))
                if heavy_v_conditions:
                    conditions.append(f"({' OR '.join(heavy_v_conditions)})")
            else:
                heavy_v_conditions = []
                for col in engine.schema['chain_columns']['v_call']:
                    if '_heavy' in col:
                        heavy_v_conditions.append(engine._build_gene_pattern(col, heavy_v))
                if heavy_v_conditions:
                    conditions.append(f"({' OR '.join(heavy_v_conditions)})")
        
        if search_params.get('heavy_d'):
            heavy_d = search_params['heavy_d']
            separator = ',' if ',' in heavy_d else '|'
            if separator in heavy_d:
                heavy_d_conditions = []
                for g in heavy_d.split(separator):
                    for col in engine.schema['chain_columns']['d_call']:
                        if '_heavy' in col:
                            heavy_d_conditions.append(engine._build_gene_pattern(col, g))
                if heavy_d_conditions:
                    conditions.append(f"({' OR '.join(heavy_d_conditions)})")
            else:
                heavy_d_conditions = []
                for col in engine.schema['chain_columns']['d_call']:
                    if '_heavy' in col:
                        heavy_d_conditions.append(engine._build_gene_pattern(col, heavy_d))
                if heavy_d_conditions:
                    conditions.append(f"({' OR '.join(heavy_d_conditions)})")
        
        if search_params.get('heavy_j'):
            heavy_j = search_params['heavy_j']
            # J gene handling matches search engine logic
            if not heavy_j.startswith('J'):
                heavy_j = f"J{heavy_j}"
            heavy_j_conditions = []
            for col in engine.schema['chain_columns']['j_call']:
                if '_heavy' in col:
                    heavy_j_conditions.append(f"{col} LIKE '%{heavy_j}%'")
            if heavy_j_conditions:
                conditions.append(f"({' OR '.join(heavy_j_conditions)})")
        
        # Heavy CDR lengths - use schema length_columns
        if search_params.get('heavy_cdr1_length') is not None:
            for col in engine.schema['length_columns']['cdr1_length']:
                if '_heavy' in col:
                    condition = engine._parse_cdr_length_condition(col, search_params['heavy_cdr1_length'])
                    if condition:
                        conditions.append(condition)
        if search_params.get('heavy_cdr2_length') is not None:
            for col in engine.schema['length_columns']['cdr2_length']:
                if '_heavy' in col:
                    condition = engine._parse_cdr_length_condition(col, search_params['heavy_cdr2_length'])
                    if condition:
                        conditions.append(condition)
        if search_params.get('heavy_cdr3_length') is not None:
            for col in engine.schema['length_columns']['cdr3_length']:
                if '_heavy' in col:
                    condition = engine._parse_cdr_length_condition(col, search_params['heavy_cdr3_length'])
                    if condition:
                        conditions.append(condition)
        
        # Light chain conditions - use schema chain_columns
        if search_params.get('light_v'):
            light_v = search_params['light_v']
            separator = ',' if ',' in light_v else '|'
            if separator in light_v:
                light_v_conditions = []
                for g in light_v.split(separator):
                    for col in engine.schema['chain_columns']['v_call']:
                        if '_light' in col:
                            light_v_conditions.append(engine._build_gene_pattern(col, g))
                if light_v_conditions:
                    conditions.append(f"({' OR '.join(light_v_conditions)})")
            else:
                light_v_conditions = []
                for col in engine.schema['chain_columns']['v_call']:
                    if '_light' in col:
                        light_v_conditions.append(engine._build_gene_pattern(col, light_v))
                if light_v_conditions:
                    conditions.append(f"({' OR '.join(light_v_conditions)})")
        
        if search_params.get('light_j'):
            light_j = search_params['light_j']
            separator = ',' if ',' in light_j else '|'
            if separator in light_j:
                light_j_conditions = []
                for g in light_j.split(separator):
                    for col in engine.schema['chain_columns']['j_call']:
                        if '_light' in col:
                            light_j_conditions.append(engine._build_gene_pattern(col, g))
                if light_j_conditions:
                    conditions.append(f"({' OR '.join(light_j_conditions)})")
            else:
                light_j_conditions = []
                for col in engine.schema['chain_columns']['j_call']:
                    if '_light' in col:
                        light_j_conditions.append(engine._build_gene_pattern(col, light_j))
                if light_j_conditions:
                    conditions.append(f"({' OR '.join(light_j_conditions)})")
        
        # Light CDR lengths - use schema length_columns
        if search_params.get('light_cdr1_length') is not None:
            for col in engine.schema['length_columns']['cdr1_length']:
                if '_light' in col:
                    condition = engine._parse_cdr_length_condition(col, search_params['light_cdr1_length'])
                    if condition:
                        conditions.append(condition)
        if search_params.get('light_cdr2_length') is not None:
            for col in engine.schema['length_columns']['cdr2_length']:
                if '_light' in col:
                    condition = engine._parse_cdr_length_condition(col, search_params['light_cdr2_length'])
                    if condition:
                        conditions.append(condition)
        if search_params.get('light_cdr3_length') is not None:
            for col in engine.schema['length_columns']['cdr3_length']:
                if '_light' in col:
                    condition = engine._parse_cdr_length_condition(col, search_params['light_cdr3_length'])
                    if condition:
                        conditions.append(condition)
        
        # Heavy chain CDR motifs
        for cdr_index in [1, 2, 3]:
            motif_key = f'heavy_cdr{cdr_index}_motif'
            similarity_key = f'heavy_cdr{cdr_index}_similarity'
            mismatches_key = f'heavy_cdr{cdr_index}_mismatches'
            
            motif_value = search_params.get(motif_key, '')
            if motif_value:
                similarity = search_params.get(similarity_key, False)
                mismatches = search_params.get(mismatches_key, 2)
                
                if similarity:
                    regex_pattern = engine.generate_similarity_pattern(motif_value, mismatches)
                else:
                    regex_pattern = engine._convert_motif_to_regex(motif_value)
                
                # Get CDR AA columns from schema
                cdr_aa_key = f'cdr{cdr_index}_aa'
                if cdr_aa_key in engine.schema.get('chain_columns', {}):
                    for col in engine.schema['chain_columns'][cdr_aa_key]:
                        if '_heavy' in col:
                            conditions.append(f"{col} ~ '{regex_pattern}'")
        
        # Light chain CDR motifs
        for cdr_index in [1, 2, 3]:
            motif_key = f'light_cdr{cdr_index}_motif'
            similarity_key = f'light_cdr{cdr_index}_similarity'
            mismatches_key = f'light_cdr{cdr_index}_mismatches'
            
            motif_value = search_params.get(motif_key, '')
            if motif_value:
                similarity = search_params.get(similarity_key, False)
                mismatches = search_params.get(mismatches_key, 2)
                
                if similarity:
                    regex_pattern = engine.generate_similarity_pattern(motif_value, mismatches)
                else:
                    regex_pattern = engine._convert_motif_to_regex(motif_value)
                
                # Get CDR AA columns from schema
                cdr_aa_key = f'cdr{cdr_index}_aa'
                if cdr_aa_key in engine.schema.get('chain_columns', {}):
                    for col in engine.schema['chain_columns'][cdr_aa_key]:
                        if '_light' in col:
                            conditions.append(f"{col} ~ '{regex_pattern}'")
    
    else:
        is_light_unpaired = unpaired_chain_type.lower() == "light"
        v_key = 'light_v' if is_light_unpaired else 'heavy_v'
        d_key = None if is_light_unpaired else 'heavy_d'
        j_key = 'light_j' if is_light_unpaired else 'heavy_j'
        cdr_prefix = 'light_' if is_light_unpaired else 'heavy_'
        
        v_gene_value = search_params.get(v_key, '')
        if v_gene_value:
            separator = ',' if ',' in v_gene_value else '|'
            if separator in v_gene_value:
                v_conditions = []
                for g in v_gene_value.split(separator):
                    for col in engine.schema['chain_columns']['v_call']:
                        v_conditions.append(engine._build_gene_pattern(col, g, force_light_chain=is_light_unpaired))
                if v_conditions:
                    conditions.append(f"({' OR '.join(v_conditions)})")
            else:
                v_conditions = [
                    engine._build_gene_pattern(col, v_gene_value, force_light_chain=is_light_unpaired)
                    for col in engine.schema['chain_columns']['v_call']
                ]
                if v_conditions:
                    conditions.append(f"({' OR '.join(v_conditions)})")
        
        if d_key and search_params.get(d_key):
            d_gene_value = search_params[d_key]
            separator = ',' if ',' in d_gene_value else '|'
            if separator in d_gene_value:
                d_conditions = []
                for g in d_gene_value.split(separator):
                    for col in engine.schema['chain_columns']['d_call']:
                        d_conditions.append(engine._build_gene_pattern(col, g, force_light_chain=is_light_unpaired))
                if d_conditions:
                    conditions.append(f"({' OR '.join(d_conditions)})")
            else:
                d_conditions = [
                    engine._build_gene_pattern(col, d_gene_value, force_light_chain=is_light_unpaired)
                    for col in engine.schema['chain_columns']['d_call']
                ]
                if d_conditions:
                    conditions.append(f"({' OR '.join(d_conditions)})")
        
        j_gene_value = search_params.get(j_key, '')
        if j_gene_value:
            separator = ',' if ',' in j_gene_value else '|'
            if separator in j_gene_value:
                j_conditions = []
                for g in j_gene_value.split(separator):
                    for col in engine.schema['chain_columns']['j_call']:
                        j_conditions.append(engine._build_gene_pattern(col, g, force_light_chain=is_light_unpaired))
                if j_conditions:
                    conditions.append(f"({' OR '.join(j_conditions)})")
            else:
                j_conditions = [
                    engine._build_gene_pattern(col, j_gene_value, force_light_chain=is_light_unpaired)
                    for col in engine.schema['chain_columns']['j_call']
                ]
                if j_conditions:
                    conditions.append(f"({' OR '.join(j_conditions)})")
        
        # CDR lengths - use schema length_columns
        for cdr_index in [1, 2, 3]:
            length_key = f'{cdr_prefix}cdr{cdr_index}_length'
            length_value = search_params.get(length_key)
            if length_value is not None:
                for col in engine.schema['length_columns'][f'cdr{cdr_index}_length']:
                    condition = engine._parse_cdr_length_condition(col, length_value)
                    if condition:
                        conditions.append(condition)
        
        # CDR motifs
        for cdr_index in [1, 2, 3]:
            motif_key = f'{cdr_prefix}cdr{cdr_index}_motif'
            similarity_key = f'{cdr_prefix}cdr{cdr_index}_similarity'
            mismatches_key = f'{cdr_prefix}cdr{cdr_index}_mismatches'
            
            motif_value = search_params.get(motif_key, '')
            if motif_value:
                similarity = search_params.get(similarity_key, False)
                mismatches = search_params.get(mismatches_key, 2)
                
                if similarity:
                    regex_pattern = engine.generate_similarity_pattern(motif_value, mismatches)
                else:
                    regex_pattern = engine._convert_motif_to_regex(motif_value)
                
                # Get CDR AA columns from schema
                # For unpaired searches, use all columns (schema will have correct columns for unpaired DBs)
                # For paired searches, columns have _heavy or _light suffix, but we're searching unpaired mode
                # so we need to filter by chain type
                cdr_aa_key = f'cdr{cdr_index}_aa'
                if cdr_aa_key in engine.schema.get('chain_columns', {}):
                    motif_conditions = []
                    for col in engine.schema['chain_columns'][cdr_aa_key]:
                        # For unpaired searches on unpaired databases, columns are just cdrX_aa
                        # For unpaired searches on paired databases, columns have _heavy/_light suffix
                        if is_light_unpaired:
                            # Light chain: use columns with _light suffix or just cdrX_aa (if no suffix exists)
                            if '_light' in col or (not any('_heavy' in c or '_light' in c for c in engine.schema['chain_columns'][cdr_aa_key])):
                                motif_conditions.append(f"{col} ~ '{regex_pattern}'")
                        else:
                            # Heavy chain: use columns with _heavy suffix or just cdrX_aa (if no suffix exists)
                            if '_heavy' in col or (not any('_heavy' in c or '_light' in c for c in engine.schema['chain_columns'][cdr_aa_key])):
                                motif_conditions.append(f"{col} ~ '{regex_pattern}'")
                    
                    if motif_conditions:
                        conditions.append(f"({' OR '.join(motif_conditions)})")
    
    return ' AND '.join(conditions) if conditions else '1=1'


def render_unpaired_plots(
    sequences_df: pd.DataFrame,
    search_params: Dict[str, Any],
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None,
    chain_type: str = "Heavy",
    engine: Optional[AntibodySearchEngine] = None,
    statistics: Optional[Dict[str, Any]] = None
) -> None:
    """
    Render plots for unpaired search results.
    
    Args:
        sequences_df: Sequences dataframe
        search_params: Search parameters dictionary
    """
    if chain_type.lower() == "light":
        render_light_chain_plots(sequences_df, search_params, prefix="", collector=collector)
    else:
        render_heavy_chain_plots(sequences_df, search_params, prefix="", collector=collector)

    overlay_active = (
        (statistics or {}).get('inferred_overlay_active')
        or st.session_state.get('inferred_overlay_active')
    )

    if overlay_active and engine is not None:
        # Check which gene columns are available in the results to determine which inferred plots to show
        has_v_gene = _find_unpaired_v_call_column(sequences_df, chain_type) is not None
        has_j_gene = _find_unpaired_j_call_column(sequences_df, chain_type) is not None
        
        # Calculate number of gene plots that would be shown
        # For heavy: V, D, J (3 plots typically)
        # For light: V, J (2 plots typically)
        if chain_type.lower() == "light":
            num_gene_plots = 2  # V and J for light chains
        else:
            num_gene_plots = 3  # V, D, and J for heavy chains
        
        # Render inferred plots for V and/or J genes (show if gene data is available)
        render_inferred_pairing_plots(
            sequences_df,
            chain_type=chain_type,
            engine=engine,
            search_params=search_params,
            collector=collector,
            num_columns=num_gene_plots,
            show_v=has_v_gene,
            show_j=has_j_gene
        )


def _find_unpaired_v_call_column(sequences_df: pd.DataFrame, chain_type: str) -> Optional[str]:
    """Identify the V gene column to use for inferred pairing plots."""
    if sequences_df.empty:
        return None
    chain_type = (chain_type or "Heavy").lower()
    candidates = [col for col in sequences_df.columns if 'v_call' in col.lower()]
    if not candidates:
        return None
    if chain_type == 'light':
        preferred = [col for col in candidates if 'light' in col.lower()]
        if preferred:
            return preferred[0]
    else:
        preferred = [col for col in candidates if 'light' not in col.lower()]
        if preferred:
            return preferred[0]
    return candidates[0]


def _find_unpaired_j_call_column(sequences_df: pd.DataFrame, chain_type: str) -> Optional[str]:
    """Identify the J gene column to use for inferred pairing plots."""
    if sequences_df.empty:
        return None
    chain_type = (chain_type or "Heavy").lower()
    candidates = [col for col in sequences_df.columns if 'j_call' in col.lower()]
    if not candidates:
        return None
    if chain_type == 'light':
        preferred = [col for col in candidates if 'light' in col.lower()]
        if preferred:
            return preferred[0]
    else:
        preferred = [col for col in candidates if 'light' not in col.lower()]
        if preferred:
            return preferred[0]
    return candidates[0]


def _create_inferred_heatmap(
    sequences_df: pd.DataFrame,
    chain_type: str,
    engine: AntibodySearchEngine,
    gene_type: str,
    max_sources: int = 8,
    max_partners: int = 12
) -> Optional[Tuple[pd.DataFrame, str, str, str, str]]:
    """
    Create an inferred pairing heatmap data structure for V or J genes.
    
    Args:
        sequences_df: Sequences dataframe
        chain_type: Chain type ('Heavy' or 'Light')
        engine: Search engine instance
        gene_type: 'V' or 'J' - the type of gene we're predicting (x-axis)
                   The y-axis will use the same gene type to match the gene plots above
        max_sources: Maximum number of source families
        max_partners: Maximum number of partner families
    
    Returns:
        Tuple of (pivot_df, row_label, col_label, title, caption) or None if no data
    """
    chain_type = (chain_type or "Heavy").capitalize()
    gene_type = gene_type.upper()
    
    # Use the same gene type for y-axis data to match the gene plots above
    # "Predicted Light V" plot: y-axis = V families (matching IGHV plot)
    # "Predicted Light J" plot: y-axis = J families (matching IGHJ plot)
    yaxis_gene_type = gene_type
    
    # Find the appropriate gene column for y-axis data
    if yaxis_gene_type == 'V':
        gene_column = _find_unpaired_v_call_column(sequences_df, chain_type)
        extract_family = engine.extract_v_family
    else:  # J
        gene_column = _find_unpaired_j_call_column(sequences_df, chain_type)
        extract_family = engine.extract_j_family
    
    if not gene_column:
        return None
    
    # Get actual genes from results (e.g., "IGHV3-30*01", "IGHJ4*01", "IGHV1/OR15")
    genes_series = sequences_df[gene_column].dropna().astype(str)
    if genes_series.empty:
        return None
    
    # Get the inferred lookup for this chain type and y-axis gene type
    # The lookup key should match the y-axis gene type (what we're using from results)
    lookup_dict = engine._inferred_lookup.get(yaxis_gene_type, {}).get(chain_type.capitalize(), {})
    if not lookup_dict:
        return None
    
    # Extract families from genes and create a mapping
    # We need to order families by the total frequency of all genes in that family
    # This matches how the gene plot orders genes (by frequency)
    gene_to_family = genes_series.map(extract_family)
    gene_counts = genes_series.value_counts()
    
    # Group genes by family and sum their frequencies
    # This gives us the total frequency for each family
    # Only include families that exist in the inferred lookup
    family_frequencies = {}
    for gene, count in gene_counts.items():
        family = extract_family(gene)
        if family and family in lookup_dict:
            family_frequencies[family] = family_frequencies.get(family, 0) + count
    
    if not family_frequencies:
        return None
    
    # Order families by their first appearance in the gene plot (sorted by frequency)
    # This ensures the inferred plot's y-axis matches the gene plot's order
    # Sort genes by frequency (descending - most frequent first)
    sorted_genes = gene_counts.sort_values(ascending=False)
    family_order = []
    seen_families = set()
    
    # Go through genes in frequency order and collect families in order of first appearance
    for gene in sorted_genes.index:
        family = extract_family(gene)
        if family and family in lookup_dict and family not in seen_families:
            family_order.append(family)
            seen_families.add(family)
    
    # Use this order for top_sources (families in order of first appearance in gene plot)
    top_sources = family_order
    
    if not top_sources:
        return None

    records: List[Dict[str, Any]] = []
    for source_family in top_sources:
        # Use the y-axis gene type for lookup (what we found in results)
        # But predict the opposite gene type (what we're showing on x-axis)
        distribution = engine.get_inferred_distribution(chain_type, source_family, gene_type=yaxis_gene_type, top_n=max_partners * 3)
        if not distribution:
            continue
        for partner_family, probability in distribution:
            if probability is None:
                continue
            records.append({
                'source_family': source_family,
                'partner_family': partner_family,
                'probability': float(probability)
            })

    if not records:
        return None

    matrix_df = pd.DataFrame(records)
    partner_scores = (
        matrix_df.groupby('partner_family')['probability']
        .max()
        .sort_values(ascending=False)
        .head(max_partners)
    )
    matrix_df = matrix_df[matrix_df['partner_family'].isin(partner_scores.index)]
    if matrix_df.empty:
        return None

    pivot_df = matrix_df.pivot_table(
        index='source_family',
        columns='partner_family',
        values='probability',
        aggfunc='max',
        fill_value=0.0
    )
    
    # Order x-axis (columns) by probability for the top gene (most frequent, first in top_sources)
    if top_sources and top_sources[0] in pivot_df.index:
        top_gene = top_sources[0]
        # Get probabilities for the top gene, order by highest to lowest
        top_gene_probs = pivot_df.loc[top_gene].sort_values(ascending=False)
        # Use this order for columns (x-axis)
        column_order = top_gene_probs.index.tolist()
    else:
        # Fallback to previous ordering
        column_order = partner_scores.index.tolist()
    
    pivot_df = pivot_df.reindex(index=top_sources, columns=column_order, fill_value=0.0)

    if pivot_df.empty or not np.any(pivot_df.values):
        return None

    # Set labels based on chain type and gene type
    if chain_type == 'Heavy':
        if gene_type == 'V':
            row_label = "Heavy V Family"
            col_label = "Predicted Light V Family"
            title = "Predicted Light V Families"
            caption = "Based on heavy-to-light V pairing frequencies (`h_to_l`)."
        else:  # J
            row_label = "Heavy J Family"
            col_label = "Predicted Light J Family"
            title = "Predicted Light J Families"
            caption = "Based on heavy-to-light J pairing frequencies (`h_to_l`)."
    else:  # Light
        if gene_type == 'V':
            row_label = "Light V Family"
            col_label = "Predicted Heavy V Family"
            title = "Predicted Heavy V Families"
            caption = "Based on light-to-heavy V pairing frequencies (`l_to_h`)."
        else:  # J
            row_label = "Light J Family"
            col_label = "Predicted Heavy J Family"
            title = "Predicted Heavy J Families"
            caption = "Based on light-to-heavy J pairing frequencies (`l_to_h`)."
    
    return (pivot_df, row_label, col_label, title, caption)


def render_inferred_pairing_plots(
    sequences_df: pd.DataFrame,
    chain_type: str,
    engine: AntibodySearchEngine,
    search_params: Dict[str, Any],
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None,
    max_sources: int = 8,
    max_partners: int = 12,
    num_columns: int = 3,
    show_v: bool = True,
    show_j: bool = True
) -> None:
    """
    Render inferred pairing heatmaps for V and/or J genes using overlay statistics for unpaired searches.
    Caches heatmap data to avoid re-processing on every render.
    
    Args:
        sequences_df: Sequences dataframe
        chain_type: Chain type ('Heavy' or 'Light')
        engine: Search engine instance
        search_params: Search parameters to determine which plots to show
        collector: Optional collector for export
        max_sources: Maximum number of source families to show
        max_partners: Maximum number of partner families to show
        num_columns: Number of columns in the gene plot layout (for width matching)
        show_v: Whether to show V gene inferred plot
        show_j: Whether to show J gene inferred plot
    """
    if sequences_df.empty:
        return

    chain_type = (chain_type or "Heavy").capitalize()
    
    # Create cache key for inferred heatmap data based on search parameters
    import json
    # Since sequences_df is already cached from the main plotting cache (which uses search_params),
    # we can create a cache key based on search params and chain type.
    # The sequences_df will be the same for the same search_params, so the inferred heatmap will be the same.
    cache_key_seed = {
        "search_params": search_params,
        "chain_type": chain_type,
        "show_v": show_v,
        "show_j": show_j,
        "max_sources": max_sources,
        "max_partners": max_partners
    }
    cache_key_hash = abs(hash(json.dumps(cache_key_seed, sort_keys=True, default=str)))
    inferred_cache_key = f"inferred_heatmap_{cache_key_hash}"
    
    # Check if we have cached inferred heatmap data
    cached_inferred_plots = st.session_state.get(inferred_cache_key)
    
    if cached_inferred_plots is not None:
        # Use cached heatmap data
        plots_to_render = cached_inferred_plots
    else:
        # Generate heatmap data
        plots_to_render = []
        
        # Render V gene inferred plot if requested
        # "Predicted Light V" plot: y-axis should show V families (matching IGHV plot)
        if show_v:
            v_plot = _create_inferred_heatmap(
                sequences_df, chain_type, engine, 'V', max_sources, max_partners
            )
            if v_plot:
                plots_to_render.append(('V', v_plot))
        
        # Render J gene inferred plot if requested
        # "Predicted Light J" plot: y-axis should show J families (matching IGHJ plot)
        if show_j:
            j_plot = _create_inferred_heatmap(
                sequences_df, chain_type, engine, 'J', max_sources, max_partners
            )
            if j_plot:
                plots_to_render.append(('J', j_plot))
        
        # Cache the heatmap data
        st.session_state[inferred_cache_key] = plots_to_render
    
    if not plots_to_render:
        return
    
    # Determine heading and color scheme based on what we're inferring
    heading_icon = "🔬" if chain_type == "Heavy" else "🧬"
    heading_chain = "Light" if chain_type == "Heavy" else "Heavy"
    
    # Color scheme based on what we're inferring (not the chain type being searched)
    # "Inferred Light" -> red (matching light chain plots)
    # "Inferred Heavy" -> blue (matching heavy chain plots)
    if chain_type == 'Heavy':
        # We're inferring Light families, so use RED color scheme (matching light chain plots)
        color_scale = [
            (0.0, "#FFFFFF"),
            (0.5, "#F7D5DB"),
            (1.0, "#CB4154"),
        ]
    else:
        # We're inferring Heavy families, so use BLUE color scheme (matching heavy chain plots)
        color_scale = [
            (0.0, "#FFFFFF"),
            (0.5, "#D8DEE9"),
            (1.0, "#4C6085"),
        ]
    
    # Render plots in a row matching the gene plot widths
    # For heavy: V plot in first column (same width as IGHV), J plot in third column (same width as IGHJ)
    # For light: V plot in first column, J plot in second column
    if chain_type == 'Heavy':
        # Heavy chain: V, D, J gene plots (3 columns)
        # V inferred plot in column 0, J inferred plot in column 2
        st.markdown(f"#### {heading_icon} Inferred {heading_chain} Gene Families (Overlay)")
        cols = st.columns(num_columns)
        
        for gene_type, (pivot_df, row_label, col_label, title, caption) in plots_to_render:
            if gene_type == 'V':
                with cols[0]:  # Match IGHV plot width
                    fig = px.imshow(
                        pivot_df,
                        labels=dict(x=col_label, y=row_label, color="Pair Probability (%)"),
                        color_continuous_scale=color_scale,
                        aspect="auto"
                    )
                    fig.update_layout(
                        title={"text": title, "x": 0.5, "xanchor": "center", "font": {"size": 16}},
                        margin=dict(l=60, r=40, t=60, b=60),
                        xaxis=dict(side="bottom"),
                        yaxis=dict(autorange="reversed"),
                        coloraxis_colorbar=dict(title="Probability (%)")
                    )
                    st.plotly_chart(fig, use_container_width=True, key=f"inferred_{chain_type.lower()}_v_plot")
            elif gene_type == 'J':
                with cols[2]:  # Match IGHJ plot width
                    fig = px.imshow(
                        pivot_df,
                        labels=dict(x=col_label, y=row_label, color="Pair Probability (%)"),
                        color_continuous_scale=color_scale,
                        aspect="auto"
                    )
                    fig.update_layout(
                        title={"text": title, "x": 0.5, "xanchor": "center", "font": {"size": 16}},
                        margin=dict(l=60, r=40, t=60, b=60),
                        xaxis=dict(side="bottom"),
                        yaxis=dict(autorange="reversed"),
                        coloraxis_colorbar=dict(title="Probability (%)")
                    )
                    st.plotly_chart(fig, use_container_width=True, key=f"inferred_{chain_type.lower()}_j_plot")
    else:
        # Light chain: V, J gene plots (2 columns)
        # V inferred plot in column 0, J inferred plot in column 1
        st.markdown(f"#### {heading_icon} Inferred {heading_chain} Gene Families (Overlay)")
        cols = st.columns(num_columns)
        
        for i, (gene_type, (pivot_df, row_label, col_label, title, caption)) in enumerate(plots_to_render):
            with cols[i]:  # Match V and J plot widths
                fig = px.imshow(
                    pivot_df,
                    labels=dict(x=col_label, y=row_label, color="Pair Probability (%)"),
                    color_continuous_scale=color_scale,
                    aspect="auto"
                )
                fig.update_layout(
                    title={"text": title, "x": 0.5, "xanchor": "center", "font": {"size": 16}},
                    margin=dict(l=60, r=40, t=60, b=60),
                    xaxis=dict(side="bottom"),
                    yaxis=dict(autorange="reversed"),
                    coloraxis_colorbar=dict(title="Probability (%)")
                )
                st.plotly_chart(fig, use_container_width=True, key=f"inferred_light_{gene_type.lower()}_plot_{i}")

    # Add to collector if provided
    if collector is not None:
        for gene_type, (pivot_df, row_label, col_label, title, caption) in plots_to_render:
            heatmap_export = pivot_df.copy()
            heatmap_export.index.name = row_label
            heatmap_export.columns.name = col_label
            fig = px.imshow(
                pivot_df,
                labels=dict(x=col_label, y=row_label, color="Pair Probability (%)"),
                color_continuous_scale=color_scale,
                aspect="auto"
            )
            collector.append((
                f"inferred_{heading_chain.lower()}_{gene_type.lower()}_heatmap",
                prepare_export_figure(fig),
                heatmap_export.reset_index().melt(
                    id_vars=[row_label],
                    var_name=col_label,
                    value_name="probability"
                )
            ))


def render_paired_plots(
    sequences_df: pd.DataFrame,
    search_params: Dict[str, Any],
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None
) -> None:
    """
    Render plots for paired search results.
    
    Args:
        sequences_df: Sequences dataframe
        search_params: Search parameters dictionary
    """
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 🧬 Heavy Chain")
        render_heavy_chain_plots(sequences_df, search_params, prefix="heavy_", collector=collector)
    
    with col2:
        st.markdown("#### 🔬 Light Chain")
        render_light_chain_plots(sequences_df, search_params, prefix="light_", collector=collector)

    # Render V and J gene pairing heatmaps side by side
    col_v, col_j = st.columns(2)
    
    with col_v:
        render_paired_v_gene_heatmap(sequences_df, collector)
    
    with col_j:
        render_paired_j_gene_heatmap(sequences_df, collector)

def render_paired_v_gene_heatmap(
    sequences_df: pd.DataFrame,
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None,
    max_genes: int = 12
) -> None:
    """
    Render heatmap showing heavy vs light V gene pairing frequencies.

    Args:
        sequences_df: Full sequences dataframe (paired mode).
        collector: Optional plot collector for downloads.
        max_genes: Maximum number of V genes to display per axis.
    """
    if sequences_df.empty:
        return

    heavy_candidates = [
        col for col in sequences_df.columns
        if "v_call" in col.lower() and "heavy" in col.lower()
    ]
    light_candidates = [
        col for col in sequences_df.columns
        if "v_call" in col.lower() and "light" in col.lower()
    ]

    if not heavy_candidates or not light_candidates:
        return

    heavy_col = heavy_candidates[0]
    light_col = light_candidates[0]

    pairing_df = sequences_df[[heavy_col, light_col]].dropna().astype(str)
    if pairing_df.empty:
        return

    heavy_top = pairing_df[heavy_col].value_counts().head(max_genes).index
    light_top = pairing_df[light_col].value_counts().head(max_genes).index

    filtered_df = pairing_df[
        pairing_df[heavy_col].isin(heavy_top) &
        pairing_df[light_col].isin(light_top)
    ]

    if filtered_df.empty:
        return

    heatmap_df = pd.crosstab(
        filtered_df[heavy_col],
        filtered_df[light_col]
    ).astype(int)

    heatmap_df = heatmap_df.reindex(index=heavy_top, columns=light_top, fill_value=0)

    if (heatmap_df.values.sum() == 0):
        return

    fig = px.imshow(
        heatmap_df,
        labels=dict(x="Light V Gene", y="Heavy V Gene", color="Pair Count"),
        color_continuous_scale=[(0.0, "#F8FAFC"), (0.5, "#818CF8"), (1.0, "#4338CA")],
        aspect="auto"
    )

    fig.update_layout(
        title={
            "text": "Heavy vs Light V Gene Pairing",
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 18}
        },
        margin=dict(l=60, r=60, t=60, b=60),
        xaxis=dict(side="bottom"),
        yaxis=dict(autorange="reversed"),
        coloraxis_colorbar=dict(title="Pairs")
    )

    st.markdown("#### 🧬 Heavy × Light V Gene Pairing")
    st.plotly_chart(fig, use_container_width=True)

    if collector is not None:
        heatmap_melt = heatmap_df.reset_index().melt(
            id_vars=heavy_col,
            var_name="light_v_gene",
            value_name="pair_count"
        )
        heatmap_melt.rename(columns={heavy_col: "heavy_v_gene"}, inplace=True)
        collector.append((
            "paired_v_gene_heatmap",
            prepare_export_figure(fig),
            heatmap_melt
        ))


def render_paired_j_gene_heatmap(
    sequences_df: pd.DataFrame,
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None,
    max_genes: int = 12
) -> None:
    """
    Render heatmap showing heavy vs light J gene pairing frequencies.

    Args:
        sequences_df: Full sequences dataframe (paired mode).
        collector: Optional plot collector for downloads.
        max_genes: Maximum number of J genes to display per axis.
    """
    if sequences_df.empty:
        return

    heavy_candidates = [
        col for col in sequences_df.columns
        if "j_call" in col.lower() and "heavy" in col.lower()
    ]
    light_candidates = [
        col for col in sequences_df.columns
        if "j_call" in col.lower() and "light" in col.lower()
    ]

    if not heavy_candidates or not light_candidates:
        return

    heavy_col = heavy_candidates[0]
    light_col = light_candidates[0]

    pairing_df = sequences_df[[heavy_col, light_col]].dropna().astype(str)
    if pairing_df.empty:
        return

    heavy_top = pairing_df[heavy_col].value_counts().head(max_genes).index
    light_top = pairing_df[light_col].value_counts().head(max_genes).index

    filtered_df = pairing_df[
        pairing_df[heavy_col].isin(heavy_top) &
        pairing_df[light_col].isin(light_top)
    ]

    if filtered_df.empty:
        return

    heatmap_df = pd.crosstab(
        filtered_df[heavy_col],
        filtered_df[light_col]
    ).astype(int)

    heatmap_df = heatmap_df.reindex(index=heavy_top, columns=light_top, fill_value=0)

    if (heatmap_df.values.sum() == 0):
        return

    fig = px.imshow(
        heatmap_df,
        labels=dict(x="Light J Gene", y="Heavy J Gene", color="Pair Count"),
        color_continuous_scale=[(0.0, "#F8FAFC"), (0.5, "#818CF8"), (1.0, "#4338CA")],
        aspect="auto"
    )

    fig.update_layout(
        title={
            "text": "Heavy vs Light J Gene Pairing",
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 18}
        },
        margin=dict(l=60, r=60, t=60, b=60),
        xaxis=dict(side="bottom"),
        yaxis=dict(autorange="reversed"),
        coloraxis_colorbar=dict(title="Pairs")
    )

    st.markdown("#### 🔬 Heavy × Light J Gene Pairing")
    st.plotly_chart(fig, use_container_width=True)

    if collector is not None:
        heatmap_melt = heatmap_df.reset_index().melt(
            id_vars=heavy_col,
            var_name="light_j_gene",
            value_name="pair_count"
        )
        heatmap_melt.rename(columns={heavy_col: "heavy_j_gene"}, inplace=True)
        collector.append((
            "paired_j_gene_heatmap",
            prepare_export_figure(fig),
            heatmap_melt
        ))


def render_heavy_chain_plots(
    sequences_df: pd.DataFrame,
    search_params: Dict[str, Any],
    prefix: str = "",
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None
) -> None:
    """
    Render Heavy chain specific plots.
    
    Args:
        sequences_df: Sequences dataframe
        search_params: Search parameters dictionary
        prefix: Prefix for column names ("" for unpaired, "heavy_" for paired)
    """
    plots_rendered = []
    cdr_plots = []  # Store CDR length plots to display in a row (order: CDR1, CDR2, CDR3)
    gene_plots = []  # Store gene plots to display in a row (order: V, D, J)
    
    # CDR1 Length distribution (always show, but highlight if used in search)
    cdr1_length_param = search_params.get(f'{prefix}cdr1_length') if prefix else search_params.get('heavy_cdr1_length')
    is_cdr1_highlighted = cdr1_length_param is not None
    
    cdr1_length_col = None
    for col in sequences_df.columns:
        if prefix:
            # For paired data, column names are like 'cdr1_length_heavy', not 'heavy_cdr1_length'
            if prefix == 'heavy_':
                if col == 'cdr1_length_heavy' or (col.endswith('_heavy') and 'cdr1_length' in col):
                    cdr1_length_col = col
                    break
        else:
            if col == 'cdr1_length' and 'light' not in col.lower():
                cdr1_length_col = col
                break
    
    if cdr1_length_col:
        cdr_plots.append((sequences_df, cdr1_length_col, "CDRH1 Length", is_cdr1_highlighted))
        plots_rendered.append("cdr1_length")
    
    # CDR2 Length distribution (always show, but highlight if used in search)
    cdr2_length_param = search_params.get(f'{prefix}cdr2_length') if prefix else search_params.get('heavy_cdr2_length')
    is_cdr2_highlighted = cdr2_length_param is not None
    
    cdr2_length_col = None
    for col in sequences_df.columns:
        if prefix:
            # For paired data, column names are like 'cdr2_length_heavy', not 'heavy_cdr2_length'
            if prefix == 'heavy_':
                if col == 'cdr2_length_heavy' or (col.endswith('_heavy') and 'cdr2_length' in col):
                    cdr2_length_col = col
                    break
        else:
            if col == 'cdr2_length' and 'light' not in col.lower():
                cdr2_length_col = col
                break
    
    if cdr2_length_col:
        cdr_plots.append((sequences_df, cdr2_length_col, "CDRH2 Length", is_cdr2_highlighted))
        plots_rendered.append("cdr2_length")
    
    # CDR3 Length distribution (always show, but highlight if used in search)
    cdr3_length_param = search_params.get(f'{prefix}cdr3_length') if prefix else search_params.get('heavy_cdr3_length')
    is_cdr3_highlighted = cdr3_length_param is not None
    
    # Try different column name variations
    cdr3_length_col = None
    for col in sequences_df.columns:
        if prefix:
            # For paired data, column names are like 'cdr3_length_heavy', not 'heavy_cdr3_length'
            if prefix == 'heavy_':
                if col == 'cdr3_length_heavy' or (col.endswith('_heavy') and 'cdr3_length' in col):
                    cdr3_length_col = col
                    break
        else:
            if col == 'cdr3_length' and 'light' not in col.lower():
                cdr3_length_col = col
                break
    
    if cdr3_length_col:
        cdr_plots.append((sequences_df, cdr3_length_col, "CDRH3 Length", is_cdr3_highlighted))
        plots_rendered.append("cdr3_length")
    
    # Display CDR length plots in a row if we have any
    if cdr_plots:
        cols = st.columns(len(cdr_plots))
        for i, plot_data in enumerate(cdr_plots):
            with cols[i]:
                # Handle both old format (3-tuple) and new format (4-tuple with highlight flag)
                if len(plot_data) == 4:
                    df, col, title, is_highlighted = plot_data
                    plot_cdr_length_distribution(
                        df,
                        col,
                        title,
                        is_highlighted=is_highlighted,
                        chain_type="heavy",
                        collector=collector
                    )
                else:
                    df, col, title = plot_data
                    plot_cdr_length_distribution(
                        df,
                        col,
                        title,
                        chain_type="heavy",
                        collector=collector
                    )
    
    # V Gene distribution - always show for Heavy chains to maintain layout
    v_call_col = None
    for col in sequences_df.columns:
        if prefix:
            if col == f'{prefix}v_call' or (prefix == 'heavy_' and col == 'v_call_heavy'):
                v_call_col = col
                break
        else:
            if col == 'v_call' and 'light' not in col.lower():
                v_call_col = col
                break
    
    if v_call_col:
        # Check if V gene was used in search
        v_gene_param = search_params.get(f'{prefix}v') if prefix else search_params.get('heavy_v')
        is_v_highlighted = bool(v_gene_param and v_gene_param.strip())
        gene_plots.append((sequences_df, v_call_col, "IGHV Gene", is_v_highlighted))
        plots_rendered.append("v_gene")
    
    # D Gene distribution - always show for Heavy chains (no D gene for Light chains)
    if not prefix:  # Only for unpaired Heavy chains
        d_call_col = None
        for col in sequences_df.columns:
            if col == 'd_call' and 'light' not in col.lower():
                d_call_col = col
                break
        
        if d_call_col:
            # Check if D gene was used in search
            d_gene_param = search_params.get('heavy_d') if not prefix else None
            is_d_highlighted = bool(d_gene_param and d_gene_param.strip())
            gene_plots.append((sequences_df, d_call_col, "IGHD Gene", is_d_highlighted))
            plots_rendered.append("d_gene")
    elif prefix == 'heavy_':  # For paired Heavy chains
        d_call_col = None
        for col in sequences_df.columns:
            if col == 'd_call_heavy':
                d_call_col = col
                break
        
        if d_call_col:
            # Check if D gene was used in search
            d_gene_param = search_params.get('heavy_d')
            is_d_highlighted = bool(d_gene_param and d_gene_param.strip())
            gene_plots.append((sequences_df, d_call_col, "IGHD Gene", is_d_highlighted))
            plots_rendered.append("d_gene")
    
    # J Gene distribution - always show for Heavy chains
    j_call_col = None
    for col in sequences_df.columns:
        if prefix:
            if col == f'{prefix}j_call' or (prefix == 'heavy_' and col == 'j_call_heavy'):
                j_call_col = col
                break
        else:
            if col == 'j_call' and 'light' not in col.lower():
                j_call_col = col
                break
    
    if j_call_col:
        # Check if J gene was used in search
        j_gene_param = search_params.get(f'{prefix}j') if prefix else search_params.get('heavy_j')
        is_j_highlighted = bool(j_gene_param and j_gene_param.strip())
        gene_plots.append((sequences_df, j_call_col, "IGHJ Gene", is_j_highlighted))
        plots_rendered.append("j_gene")
    
    # Display gene plots in a row if we have any
    if gene_plots:
        cols = st.columns(len(gene_plots))
        for i, plot_data in enumerate(gene_plots):
            with cols[i]:
                if len(plot_data) == 4:
                    df, col, title, is_highlighted = plot_data
                    plot_gene_distribution(
                        df,
                        col,
                        title,
                        is_highlighted=is_highlighted,
                        chain_type="heavy",
                        collector=collector
                    )
                else:
                    df, col, title = plot_data
                    plot_gene_distribution(
                        df,
                        col,
                        title,
                        chain_type="heavy",
                        collector=collector
                    )
    
    if not plots_rendered:
        st.info("No plots available (all filters specified).")


def render_light_chain_plots(
    sequences_df: pd.DataFrame,
    search_params: Dict[str, Any],
    prefix: str = "light_",
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None
) -> None:
    """
    Render Light chain specific plots.
    
    Args:
        sequences_df: Sequences dataframe
        search_params: Search parameters dictionary
        prefix: Prefix for column names ("light_" for paired, "" for unpaired)
    """
    plots_rendered = []
    cdr_plots = []  # Store CDR length plots to display in a row (order: CDR1, CDR2, CDR3)
    gene_plots = []  # Store gene plots to display in a row (order: V, J - no D gene for Light chains)
    
    # CDR1 Length distribution (if CDR1 length not specified in search)
    cdr1_length_param = search_params.get(f'{prefix}cdr1_length') if prefix else search_params.get('cdr1_length')
    if cdr1_length_param is None:
        cdr1_length_col = None
        for col in sequences_df.columns:
            if prefix:
                if col == f'{prefix}cdr1_length' or (prefix == 'light_' and col == 'cdr1_length_light'):
                    cdr1_length_col = col
                    break
            else:
                if col == 'cdr1_length':
                    cdr1_length_col = col
                    break
        
        if cdr1_length_col:
            cdr_plots.append((sequences_df, cdr1_length_col, "CDRL1 Length"))
            plots_rendered.append("cdr1_length")
    
    # CDR2 Length distribution (if CDR2 length not specified)
    cdr2_length_param = search_params.get(f'{prefix}cdr2_length') if prefix else search_params.get('cdr2_length')
    if cdr2_length_param is None:
        cdr2_length_col = None
        for col in sequences_df.columns:
            if prefix:
                if col == f'{prefix}cdr2_length' or (prefix == 'light_' and col == 'cdr2_length_light'):
                    cdr2_length_col = col
                    break
            else:
                if col == 'cdr2_length':
                    cdr2_length_col = col
                    break
        
        if cdr2_length_col:
            cdr_plots.append((sequences_df, cdr2_length_col, "CDRL2 Length"))
            plots_rendered.append("cdr2_length")
    
    # CDR3 Length distribution (if CDR3 length not specified)
    cdr3_length_param = search_params.get(f'{prefix}cdr3_length') if prefix else search_params.get('cdr3_length')
    if cdr3_length_param is None:
        cdr3_length_col = None
        for col in sequences_df.columns:
            if prefix:
                if col == f'{prefix}cdr3_length' or (prefix == 'light_' and col == 'cdr3_length_light'):
                    cdr3_length_col = col
                    break
            else:
                if col == 'cdr3_length':
                    cdr3_length_col = col
                    break
        
        if cdr3_length_col:
            cdr_plots.append((sequences_df, cdr3_length_col, "CDRL3 Length"))
            plots_rendered.append("cdr3_length")
    
    # Display CDR length plots in a row if we have any
    if cdr_plots:
        cols = st.columns(len(cdr_plots))
        for i, (df, col, title) in enumerate(cdr_plots):
            with cols[i]:
                plot_cdr_length_distribution(
                    df,
                    col,
                    title,
                    chain_type="light",
                    collector=collector
                )
    
    # V Gene distribution - always show for Light chains
    v_call_col = None
    for col in sequences_df.columns:
        if prefix:
            if col == f'{prefix}v_call' or (prefix == 'light_' and col == 'v_call_light'):
                v_call_col = col
                break
        else:
            if col == 'v_call':
                v_call_col = col
                break
    
    if v_call_col:
        # Check if V gene was used in search
        v_gene_param = search_params.get(f'{prefix}v') if prefix else search_params.get('light_v')
        is_v_highlighted = bool(v_gene_param and v_gene_param.strip())
        gene_plots.append((sequences_df, v_call_col, "IGLV Gene", is_v_highlighted))
        plots_rendered.append("v_gene")
    
    # J Gene distribution - always show for Light chains
    j_call_col = None
    for col in sequences_df.columns:
        if prefix:
            if col == f'{prefix}j_call' or (prefix == 'light_' and col == 'j_call_light'):
                j_call_col = col
                break
        else:
            if col == 'j_call':
                j_call_col = col
                break
    
    if j_call_col:
        # Check if J gene was used in search
        j_gene_param = search_params.get(f'{prefix}j') if prefix else search_params.get('light_j')
        is_j_highlighted = bool(j_gene_param and j_gene_param.strip())
        gene_plots.append((sequences_df, j_call_col, "IGLJ Gene", is_j_highlighted))
        plots_rendered.append("j_gene")
    
    # Display gene plots in a row if we have any
    if gene_plots:
        cols = st.columns(len(gene_plots))
        for i, plot_data in enumerate(gene_plots):
            with cols[i]:
                if len(plot_data) == 4:
                    df, col, title, is_highlighted = plot_data
                    plot_gene_distribution(
                        df,
                        col,
                        title,
                        is_highlighted=is_highlighted,
                        chain_type="light",
                        collector=collector
                    )
                else:
                    df, col, title = plot_data
                    plot_gene_distribution(
                        df,
                        col,
                        title,
                        chain_type="light",
                        collector=collector
                    )
    
    if not plots_rendered:
        st.info("No plots available (all filters specified).")


def plot_cdr_length_distribution(
    df: pd.DataFrame,
    column: str,
    title: str,
    is_highlighted: bool = False,
    chain_type: str = "heavy",
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None
) -> None:
    """
    Plot CDR length distribution as a bar chart with each length as a separate bar.
    
    Args:
        df: Dataframe with sequences
        column: Column name containing CDR length
        title: Title for the plot
        is_highlighted: Whether this parameter was used in the search (for highlighting)
    """
    if column not in df.columns:
        return
    
    # Filter out NaN values
    lengths = df[column].dropna()
    
    if len(lengths) == 0:
        return
    
    # Count occurrences of each length (each length gets its own bar)
    length_counts = lengths.value_counts().sort_index()
    
    # Prepare title with highlighting
    display_title = f"🔍 {title}" if is_highlighted else title
    title_config = {
        'text': display_title,
        'x': 0.5,
        'xanchor': 'center'
    }
    if is_highlighted:
        title_config['font'] = {'color': '#FF6B35', 'size': 16}  # Orange-red color for highlighting
    
    if chain_type == "light":
        color_scale = [
            (0.0, "#FFFFFF"),
            (0.5, "#F7D5DB"),
            (1.0, "#CB4154"),
        ]
    else:
        color_scale = [
            (0.0, "#FFFFFF"),
            (0.5, "#D8DEE9"),
            (1.0, "#4C6085"),
        ]

    # Create bar chart (not histogram) so each length is a separate bar
    fig = px.bar(
        x=length_counts.index,
        y=length_counts.values,
        title=display_title,
        labels={'x': 'Length (amino acids)', 'y': 'Frequency'},
        color=length_counts.values,
        color_continuous_scale=color_scale
    )
    
    fig.update_layout(
        height=300,
        showlegend=False,
        margin=dict(l=60, r=30, t=60, b=70),
        xaxis={'type': 'category'},  # Ensure discrete x-axis (each length is separate)
        title=title_config,
        xaxis_title="Length (amino acids)",
        yaxis_title="Frequency"
    )
    
    fig.update_coloraxes(colorscale=color_scale, showscale=False)

    st.plotly_chart(fig, use_container_width=True)

    if collector is not None:
        export_df = length_counts.reset_index()
        export_df.columns = ["cdr_length", "count"]
        export_df["chain_type"] = chain_type
        collector.append((f"{chain_type}_{title}", prepare_export_figure(fig), export_df.copy()))


def plot_gene_distribution(
    df: pd.DataFrame,
    column: str,
    title: str,
    max_genes: int = 15,
    is_highlighted: bool = False,
    chain_type: str = "heavy",
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None
) -> None:
    """
    Plot gene distribution as a bar chart (top N genes).
    
    Args:
        df: Dataframe with sequences
        column: Column name containing gene calls
        title: Title for the plot
        max_genes: Maximum number of genes to display (default: 15)
        is_highlighted: Whether this parameter was used in the search (for highlighting)
    """
    if column not in df.columns:
        return
    
    # Get gene counts
    gene_counts = df[column].value_counts().head(max_genes)
    
    if len(gene_counts) == 0:
        return
    
    # Prepare title with highlighting
    display_title = f"🔍 {title}" if is_highlighted else title
    title_config = {
        'text': display_title,
        'x': 0.5,
        'xanchor': 'center'
    }
    if is_highlighted:
        title_config['font'] = {'color': '#FF6B35', 'size': 16}  # Orange-red color for highlighting
    
    if chain_type == "light":
        color_scale = [
            (0.0, "#FFFFFF"),
            (0.5, "#F7D5DB"),
            (1.0, "#CB4154"),
        ]
    else:
        color_scale = [
            (0.0, "#FFFFFF"),
            (0.5, "#D8DEE9"),
            (1.0, "#4C6085"),
        ]

    # Create bar chart
    fig = px.bar(
        x=gene_counts.values,
        y=gene_counts.index,
        orientation='h',
        title=display_title,
        labels={'x': 'Count', 'y': 'Gene'},
        color=gene_counts.values,
        color_continuous_scale=color_scale
    )
    
    fig.update_layout(
        height=400,  # Fixed height for consistent display across all gene plots
        showlegend=False,
        margin=dict(l=120, r=40, t=60, b=70),
        yaxis={'categoryorder': 'total ascending'},
        title=title_config,
        xaxis_title="Count",
        yaxis_title="Gene"
    )
    
    fig.update_coloraxes(colorscale=color_scale, showscale=False)

    st.plotly_chart(fig, use_container_width=True)

    if collector is not None:
        export_df = gene_counts.reset_index()
        export_df.columns = ["gene", "count"]
        export_df["chain_type"] = chain_type
        collector.append((f"{chain_type}_{title}", prepare_export_figure(fig), export_df.copy()))


def render_subject_hits_boxplot(
    stats_df: pd.DataFrame,
    statistics: Dict[str, Any]
) -> None:
    """
    Render donor-level hits-per-million distribution as a box plot with jittered points.

    Args:
        stats_df: Statistics dataframe per subject
        statistics: Overall statistics dictionary for the current search
    """
    st.session_state.pop("latest_subject_hits_plot", None)
    statistics = statistics or {}

    # Handle case where stats_df might be None (from old API)
    if stats_df is None:
        st.info("Subject statistics not available.")
        return

    if stats_df.empty:
        st.info("No subject statistics available for plotting.")
        return

    total_hits = statistics.get("total_hits") or 0
    total_sequences = statistics.get("total_sequences") or 0

    if total_hits <= 0 or total_sequences <= 0:
        st.info("Insufficient overall statistics to render donor plot.")
        return

    overall_frequency = total_hits / total_sequences
    if overall_frequency <= 0:
        st.info("Overall frequency is zero; donor plot unavailable.")
        return

    required_sequences = 10 / overall_frequency

    filtered_df = stats_df.copy()

    # Normalize column names expected downstream
    column_aliases = {
        "per_million": "hits_per_million",
        "total": "total_sequences",
    }

    for source, target in column_aliases.items():
        if source in filtered_df.columns and target not in filtered_df.columns:
            filtered_df[target] = filtered_df[source]

    required_columns = {"total_sequences", "hits", "hits_per_million"}
    missing_columns = required_columns.difference(filtered_df.columns)
    if missing_columns:
        # Debug: Show what columns we actually have
        available_cols = list(filtered_df.columns)
        st.warning(
            f"Subject statistics missing required fields for donor plotting.\n"
            f"Required: {required_columns}\n"
            f"Available: {available_cols}\n"
            f"Missing: {missing_columns}"
        )
        return

    numeric_cols = ["total_sequences", "hits", "hits_per_million"]
    for col in numeric_cols:
        if col in filtered_df.columns:
            filtered_df[col] = pd.to_numeric(filtered_df[col], errors="coerce")

    filtered_df = filtered_df[filtered_df["total_sequences"] >= required_sequences]
    filtered_df = filtered_df[filtered_df["hits"] > 0]
    filtered_df = filtered_df[filtered_df["hits_per_million"] > 0]

    if filtered_df.empty:
        st.info("No donors meet the minimum sequence threshold for plotting.")
        return

    y_values = filtered_df["hits_per_million"].astype(float)
    donor_labels = filtered_df.get("subject", pd.Series(index=filtered_df.index, dtype=str)).fillna("Unknown")

    if not (y_values > 0).all():
        st.info("Cannot display donor distribution on a log scale due to non-positive values.")
        return

    # Calculate bounds with more padding to account for jittered points
    # Use more padding (1.5x) to ensure all jittered points are visible
    min_val = float(y_values.min())
    max_val = float(y_values.max())
    
    lower_bound = min_val * 0.8
    upper_bound = max_val * 1.5
    
    # Ensure lower_bound is positive (for log scale) but don't force a fixed minimum
    # Use a small fraction of the minimum value if needed to avoid log(0)
    if lower_bound <= 0:
        lower_bound = min_val * 0.1  # Use 10% of min if calculated bound is <= 0
    
    if upper_bound <= lower_bound:
        upper_bound = lower_bound * 2.0

    log_min = float(np.log10(lower_bound))
    log_max = float(np.log10(upper_bound))
    if log_max - log_min < 2.0:
        padding = (2.0 - (log_max - log_min)) / 2.0
        log_min -= padding
        log_max += padding
    yaxis_range = [log_min, log_max]

    tick_exponents = np.arange(np.floor(log_min), np.ceil(log_max) + 1, 1, dtype=int)
    tick_vals = np.power(10.0, tick_exponents)
    tick_text = [f"10^{exp}" for exp in tick_exponents]

    customdata = pd.DataFrame({
        "subject": donor_labels,
    }).to_numpy()

    fig = go.Figure()
    fig.add_trace(
        go.Box(
            y=y_values,
            name="Donors",
            boxpoints="all",
            jitter=0.2,
            pointpos=0,
            marker=dict(
                size=8, 
                color='rgba(31, 119, 180, 1.0)'  # Opaque blue points
            ),
            line=dict(color='rgba(31, 119, 180, 0.5)', width=1),  # Transparent line
            fillcolor='rgba(76, 96, 133, 0.2)',  # Transparent box fill
            customdata=customdata,
            hovertemplate=(
                "Subject: %{customdata[0]}<br>Hits/Million: %{y:,.2f}<extra></extra>"
            ),
        )
    )

    subtitle_text = (
        f"Showing donors with ≥ {required_sequences:,.0f} sequences "
        f"(threshold = 10 ÷ overall frequency)."
    )
    subtitle_html = (
        "<span style='font-weight: normal; font-size: 10px;'>"
        f"{subtitle_text}"
        "</span>"
    )

    fig.update_layout(
        title={
            "text": f"Per-Million Hits by Donor<br><sup>{subtitle_html}</sup>",
            "x": 0.5,
            "xanchor": "center",
        },
        showlegend=False,
        height=230,
        boxgroupgap=0.6,
        margin=dict(l=20, r=20, t=45, b=15),
        template="plotly_white",
        yaxis=dict(
            title="Hits per Million",
            type="log",
            range=yaxis_range,
            tickmode="array",
            tickvals=tick_vals,
            ticktext=tick_text,
        ),
    )

    st.plotly_chart(fig, use_container_width=True)

    export_df = filtered_df[["subject", "total_sequences", "hits", "hits_per_million"]].copy()
    export_df["hits_per_million_millions"] = export_df["hits_per_million"] / 1_000_000

    st.session_state["latest_subject_hits_plot"] = (
        "donor_per_million_hits",
        prepare_export_figure(fig),
        export_df
    )


def build_search_metadata(
    search_params: Dict[str, Any],
    statistics: Dict[str, Any],
    is_paired: bool,
    include_raw_data: bool
) -> Dict[str, Any]:
    """
    Build metadata dictionary describing the current search for inclusion in downloads.
    """
    statistics = statistics or {}
    selected_databases = st.session_state.get("selected_databases", [])

    metadata: Dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "is_paired": is_paired,
        "includes_raw_plotting_data": include_raw_data,
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

    return metadata


def create_plots_zip(
    plots: List[Tuple[str, go.Figure, Optional[pd.DataFrame]]],
    metadata: Dict[str, Any],
    include_raw_data: bool = False,
    progress_callback: Optional[Callable[[float], None]] = None
) -> bytes:
    """
    Create an in-memory ZIP archive containing PNG exports of the provided Plotly figures.

    Args:
        plots: List of (title, figure, dataframe) tuples representing charts to export.
        metadata: Dictionary containing search metadata to include in the archive.
        include_raw_data: Whether to include CSV exports of plotting data.
        progress_callback: Optional callable receiving progress (0-1) updates.

    Returns:
        Bytes of the ZIP archive.
    """
    if not plots:
        return b""

    metadata = dict(metadata)
    plot_entries: List[Dict[str, Any]] = []

    raw_entries = 0
    if include_raw_data:
        raw_entries = sum(
            1 for _, _, data in plots
            if isinstance(data, (pd.DataFrame, pd.Series)) or data is not None
        )

    total_steps = len(plots) + (raw_entries if include_raw_data else 0) + 1
    total_steps = max(total_steps, 1)
    current_step = 0

    def _emit_progress() -> None:
        if progress_callback is not None:
            progress = current_step / total_steps
            progress_callback(min(max(progress, 0.0), 1.0))

    if progress_callback is not None:
        progress_callback(0.0)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, (title, figure, data) in enumerate(plots, start=1):
            filename = _sanitize_plot_filename(title, index)
            image_bytes = figure.to_image(format="png", scale=2)
            zf.writestr(filename, image_bytes)
            current_step += 1
            _emit_progress()

            plot_record: Dict[str, Any] = {
                "title": title,
                "image_file": filename,
            }

            if include_raw_data and data is not None:
                if isinstance(data, pd.DataFrame):
                    export_df = data.copy()
                elif isinstance(data, pd.Series):
                    export_df = data.to_frame()
                else:
                    export_df = pd.DataFrame(data)

                raw_filename = filename.rsplit(".", 1)[0] + ".csv"
                raw_path = f"raw_data/{raw_filename}"
                csv_bytes = export_df.to_csv(index=False).encode("utf-8")
                zf.writestr(raw_path, csv_bytes)
                plot_record["raw_data_file"] = raw_path

                current_step += 1
                _emit_progress()

            plot_entries.append(plot_record)

        metadata["plots"] = plot_entries
        metadata["includes_raw_plotting_data"] = include_raw_data
        metadata_bytes = json.dumps(
            metadata,
            indent=2,
            sort_keys=True,
            default=_json_default
        ).encode("utf-8")
        zf.writestr("search_parameters.json", metadata_bytes)
        current_step += 1
        _emit_progress()

    buffer.seek(0)
    return buffer.getvalue()


def _sanitize_plot_filename(title: str, index: int) -> str:
    """
    Sanitize plot titles for use as filenames inside the ZIP archive.

    Args:
        title: Original title string.
        index: Sequential index to ensure uniqueness.

    Returns:
        Sanitized filename ending with .png
    """
    if not title:
        title = f"plot_{index:02d}"

    normalized = re.sub(r"[^\w\-]+", "_", title.strip())
    normalized = normalized.strip("_") or f"plot_{index:02d}"
    return f"{index:02d}_{normalized}.png"

def prepare_export_figure(fig: go.Figure) -> go.Figure:
    """
    Create a styled copy of the provided Plotly figure for downloads.

    Applies dark theme styling and adds attribution.
    """
    export_fig = go.Figure(fig)
    export_fig.update_layout(
        plot_bgcolor="#2a2a2a",
        paper_bgcolor="#2a2a2a",
        font=dict(color="#f5f5f5"),
    )
    export_fig.update_xaxes(color="#f5f5f5", title_font=dict(color="#f5f5f5"))
    export_fig.update_yaxes(color="#f5f5f5", title_font=dict(color="#f5f5f5"))
    export_fig.add_annotation(
        text="Created with ABHunter",
        x=1,
        xref="paper",
        y=0,
        yref="paper",
        xanchor="right",
        yanchor="bottom",
        showarrow=False,
        font=dict(color="#cccccc", size=11)
    )
    return export_fig


def _json_default(value: Any) -> Any:
    """
    Fallback JSON serializer for non-serializable objects.
    """
    if isinstance(value, (set, tuple)):
        return list(value)
    try:
        return str(value)
    except Exception:
        return repr(value)


