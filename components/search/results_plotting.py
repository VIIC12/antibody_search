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

from components.search.styling import icon_heading
import pandas as pd
import numpy as np
from datetime import datetime
from src.search_engine import AntibodySearchEngine

PLOTLY_DISPLAY_CONFIG = {
    "displayModeBar": False,
    
}

# Global configuration for plotting limits
# Maximum number of sequences to fetch for CDR length, V/D/J gene distribution plots
# This limit balances accuracy of distributions with memory usage and query performance
PLOTTING_DATA_LIMIT = 1000000

# Threshold for showing warning message about large result sets
# If total_hits exceeds this, a message is shown indicating plots use a sample
PLOTTING_WARNING_THRESHOLD = 1_000_000

# Keys used to temporarily lock the search form while expensive plotting queries
# are running. This prevents users from modifying the search mask mid-render,
# which can otherwise lead to crashes or inconsistent state.
PLOTTING_LOCK_KEY = "plotting_controls_locked"
PLOTTING_LOCK_REASON_KEY = "plotting_controls_locked_reason"
PLOTTING_LOCK_REASON_PLOTS = "plots_loading"


def render_results_plots(
    sequences_sample_df: pd.DataFrame,
    statistics: Dict[str, Any],
    is_paired: bool,
    search_params: Dict[str, Any],
    engine: AntibodySearchEngine,
    show_spider_toggle: bool = True,
    show_gene_group_control: bool = True,
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
    """
    if sequences_sample_df.empty:
        return
    
    st.markdown("### :material/bar_chart_4_bars: Result Distributions")

    # Check if we have a very large result set (will be sampled)
    total_hits = statistics.get('total_hits', 0)
    
    if total_hits > PLOTTING_WARNING_THRESHOLD:
        st.info(
            f"**Large result set detected** ({total_hits:,} hits). "
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
    sequences_full_df = None
    aa_distributions = {}
    if cached_data is not None:
        if isinstance(cached_data, tuple):
            sequences_full_df, aa_distributions = cached_data
        else:
            sequences_full_df = cached_data
    
    if sequences_full_df is None:
        lock_active = st.session_state.get(PLOTTING_LOCK_KEY, False)
        # First rerun: lock the search controls so the form renders as disabled
        if not lock_active:
            st.session_state[PLOTTING_LOCK_KEY] = True
            st.session_state[PLOTTING_LOCK_REASON_KEY] = PLOTTING_LOCK_REASON_PLOTS
            st.rerun()
        
        fetch_successful = False
        try:
            # Fetch plotting data (sequences + CDR AA distributions for spider plots)
            with st.spinner("Loading data for plotting..."):
                sequences_full_df, aa_distributions = fetch_plotting_data(
                    engine,
                    search_params,
                    is_paired,
                    unpaired_chain_type
                )
            fetch_successful = True
            # Cache the fetched data
            st.session_state[cache_key] = (sequences_full_df, aa_distributions)
        finally:
            st.session_state[PLOTTING_LOCK_KEY] = False
            st.session_state.pop(PLOTTING_LOCK_REASON_KEY, None)
        
        if fetch_successful:
            # Second rerun: re-enable controls and render plots with cached data
            st.rerun()
        return
    
    if sequences_full_df.empty:
        st.info("No results available for plotting.")
        return
    
    collected_plots: List[Tuple[str, go.Figure, Optional[pd.DataFrame]]] = []
    spider_mode = "per_aa"

    # Determine which plots to show based on search type and parameters
    if is_paired:
        render_paired_plots(
            sequences_full_df, search_params, collected_plots,
            aa_distributions=aa_distributions,
            spider_mode=spider_mode,
        )
    else:
        render_unpaired_plots(
            sequences_full_df,
            search_params,
            collected_plots,
            chain_type=unpaired_chain_type,
            engine=engine,
            statistics=statistics,
            aa_distributions=aa_distributions,
            spider_mode=spider_mode,
            show_spider_toggle=show_spider_toggle,
            show_gene_group_control=show_gene_group_control,
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
                "⬇ Download Figures",
                key=f"{download_key}_button_figures",
                width='stretch'
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
                
                # Check if this is a large file with download URL
                if result.get('download_url'):
                    # Large file: redirect to static download link
                    download_url = result.get('download_url')
                    st.markdown(
                        f'<a href="{download_url}" target="_blank" style="text-decoration: none;">'
                        f'<button style="width: 100%; padding: 0.5rem 1rem; background-color: rgb(19, 124, 189); '
                        f'color: white; border: none; border-radius: 0.25rem; cursor: pointer; font-size: 0.875rem;">'
                        f'✅ Download Figures ({file_size_mb:.2f} MB) - Opens in new tab</button></a>',
                        unsafe_allow_html=True
                    )
                else:
                    # Small file: use direct download button
                    st.download_button(
                        label=f"✅ Download Figures ({file_size_mb:.2f} MB)",
                        data=result.get('zip_data', b''),
                        file_name=result.get('filename', 'plots.zip'),
                        mime="application/zip",
                        width='stretch',
                        type="primary",
                        key=f"download_{download_key}_figures"
                    )
            else:
                st.button("❌ Generation Failed", disabled=True, key=f"{download_key}_failed_figures", width='stretch')
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
                "⬇ Download Figures + Raw Data",
                key=f"{download_key}_button_raw",
                width='stretch'
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
                
                # Check if this is a large file with download URL
                if result.get('download_url'):
                    # Large file: redirect to static download link
                    download_url = result.get('download_url')
                    st.markdown(
                        f'<a href="{download_url}" target="_blank" style="text-decoration: none;">'
                        f'<button style="width: 100%; padding: 0.5rem 1rem; background-color: rgb(19, 124, 189); '
                        f'color: white; border: none; border-radius: 0.25rem; cursor: pointer; font-size: 0.875rem;">'
                        f'✅ Download Figures + Raw Data ({file_size_mb:.2f} MB) - Opens in new tab</button></a>',
                        unsafe_allow_html=True
                    )
                else:
                    # Small file: use direct download button
                    st.download_button(
                        label=f"✅ Download Figures + Raw Data ({file_size_mb:.2f} MB)",
                        data=result.get('zip_data', b''),
                        file_name=result.get('filename', 'plots_raw.zip'),
                        mime="application/zip",
                        width='stretch',
                        type="primary",
                        key=f"download_{download_key}_raw"
                    )
            else:
                st.button("❌ Generation Failed", disabled=True, key=f"{download_key}_failed_raw", width='stretch')
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
    Only the columns needed for plots (CDR lengths, V/D/J gene calls) are requested from the engine,
    reducing I/O and memory versus loading 1M full rows. Limits results to PLOTTING_DATA_LIMIT.
    
    Args:
        engine: Search engine instance
        search_params: Search parameters dictionary
        is_paired: Whether this is a paired search
        unpaired_chain_type: Chain type for unpaired searches ("Heavy" or "Light")
        
    Returns:
        Tuple of (sequences_df, aa_distributions). sequences_df has columns for plotting;
        aa_distributions is a dict mapping CDR keys (e.g. 'cdr1_heavy', 'cdr3') to DataFrames
        with aa/percent for spider plots.
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
    
    # Determine which columns we need for plotting (CDR lengths, V/D/J genes only)
    # Passing these to search() reduces I/O and memory vs loading 1M full rows
    # Light chains have no D gene - exclude d_call when querying light chain view
    chain_base_cols = ['v_call', 'j_call'] if (not is_paired and unpaired_chain_type.lower() == 'light') else ['v_call', 'd_call', 'j_call']
    plotting_columns = []
    for base_col in ['cdr1_length', 'cdr2_length', 'cdr3_length']:
        if base_col in engine.schema.get('length_columns', {}):
            plotting_columns.extend(engine.schema['length_columns'][base_col])
    for base_col in chain_base_cols:
        if base_col in engine.schema.get('chain_columns', {}):
            plotting_columns.extend(engine.schema['chain_columns'][base_col])
    # Restrict to columns that exist in the schema (for post-search selection)
    available_columns = [c for c in plotting_columns if c in engine.schema.get('available_columns', [])]
    if not available_columns:
        available_columns = None

    # Execute search with full_results=True and limit (do not pass columns= to avoid engine compatibility issues)
    sequences_df, _, _ = engine.search(
        **search_kwargs,
        full_results=True,
        limit=PLOTTING_DATA_LIMIT,
    )

    if sequences_df.empty:
        return sequences_df, {}
    # Keep only plotting columns to reduce memory for downstream
    if available_columns:
        cols = [c for c in available_columns if c in sequences_df.columns]
        if cols:
            sequences_df = sequences_df[cols].copy()

    # Fetch CDR AA distributions (overall per CDR, not per V-family) for spider plots
    aa_distributions = fetch_cdr_aa_distribution(
        engine, search_params, is_paired, unpaired_chain_type
    )

    return sequences_df, aa_distributions


# Standard 20 amino acids for CDR AA distribution
_CDR_AA_VALID = ("A", "R", "N", "D", "C", "E", "Q", "G", "H", "I", "L", "K", "M", "F", "P", "S", "T", "W", "Y", "V")

# AA property groups for spider plot "by property" view (from TODO_v_gen_aa_distribution.ipynb)
_AA_PROPERTY_GROUPS: Dict[str, Tuple[str, ...]] = {
    "Hydrophobic": ("A", "V", "L", "I", "M", "F", "W"),
    "Small/Polar": ("G", "S", "T", "Y", "N", "Q"),
    "Positively Charged": ("K", "R", "H"),
    "Negatively Charged": ("D", "E"),
    "Proline": ("P",),
    "Cysteine": ("C",),
}

SPIDER_PLOT_MODE_KEY = "cdr_spider_plot_mode"
GENE_GROUP_MODE_KEY = "gene_plot_group_mode"
GENE_GROUP_MODE_OPTIONS = ("Allele", "Subfamily", "Family")
GENE_GROUP_MODE_TO_VALUE = {
    "Allele": "allele",
    "Subfamily": "subfamily",
    "Family": "family",
}
GENE_GROUP_VALUE_TO_LABEL = {v: k for k, v in GENE_GROUP_MODE_TO_VALUE.items()}


def _get_gene_group_mode() -> str:
    """Return current gene plot grouping mode: allele | subfamily | family."""
    mode = st.session_state.get(GENE_GROUP_MODE_KEY, "allele")
    if mode not in ("allele", "subfamily", "family"):
        return "allele"
    return mode


def _extract_gene_subfamily(gene_name: Any) -> Optional[str]:
    """Strip allele suffix: IGHV3-23*01 -> IGHV3-23."""
    if gene_name is None or (isinstance(gene_name, float) and pd.isna(gene_name)):
        return None
    text = str(gene_name).strip()
    if not text:
        return None
    return text.split("*", 1)[0]


def _extract_gene_family_label(gene_name: Any) -> Optional[str]:
    """Family label: IGHV3-23*01 / IGHV3-21*02 -> IGHV3."""
    if gene_name is None or (isinstance(gene_name, float) and pd.isna(gene_name)):
        return None
    family = AntibodySearchEngine._extract_v_family(str(gene_name))
    if family:
        return family
    # Fallback for unexpected formats
    return _extract_gene_subfamily(gene_name)


def _map_gene_to_group_label(gene_name: Any, group_mode: str) -> str:
    """Map a gene call to the label used for the selected grouping mode."""
    if group_mode == "subfamily":
        return _extract_gene_subfamily(gene_name) or "Unknown"
    if group_mode == "family":
        return _extract_gene_family_label(gene_name) or "Unknown"
    if gene_name is None or (isinstance(gene_name, float) and pd.isna(gene_name)):
        return "Unknown"
    text = str(gene_name).strip()
    return text or "Unknown"


def _gene_plot_title_for_mode(title: str, group_mode: str) -> str:
    """Adjust gene plot title for subfamily/family grouping."""
    if group_mode == "subfamily":
        return title.replace("Gene", "Subfamily")
    if group_mode == "family":
        return title.replace("Gene", "Family")
    return title


def _sync_gene_group_mode_from_widget(
    widget_key: str = "gene_plot_group_mode_control",
) -> str:
    """Apply widget selection (from a prior run) before gene plots are drawn."""
    if GENE_GROUP_MODE_KEY not in st.session_state:
        st.session_state[GENE_GROUP_MODE_KEY] = "allele"
    selected = st.session_state.get(widget_key)
    if selected in GENE_GROUP_MODE_TO_VALUE:
        st.session_state[GENE_GROUP_MODE_KEY] = GENE_GROUP_MODE_TO_VALUE[selected]
    return _get_gene_group_mode()


def _render_gene_group_control(*, widget_key: str = "gene_plot_group_mode_control") -> str:
    """
    Render grouping control below V/D/J gene plots.
    Returns the active mode (allele | subfamily | family).
    """
    if GENE_GROUP_MODE_KEY not in st.session_state:
        st.session_state[GENE_GROUP_MODE_KEY] = "allele"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = GENE_GROUP_VALUE_TO_LABEL.get(
            st.session_state[GENE_GROUP_MODE_KEY],
            "Allele",
        )

    selected = st.segmented_control(
        "Group genes by",
        options=list(GENE_GROUP_MODE_OPTIONS),
        key=widget_key,
        help=(
            "Allele: full gene calls (e.g. IGHV3-23*01). "
            "Subfamily: alleles collapsed (e.g. IGHV3-23*01 + IGHV3-23*02 → IGHV3-23). "
            "Family: genes collapsed (e.g. IGHV3-23 + IGHV3-21 → IGHV3)."
        ),
    )
    if selected is None:
        selected = st.session_state.get(widget_key, "Allele")
    mode = GENE_GROUP_MODE_TO_VALUE.get(selected, "allele")
    st.session_state[GENE_GROUP_MODE_KEY] = mode
    return mode


def fetch_cdr_aa_distribution(
    engine: AntibodySearchEngine,
    search_params: Dict[str, Any],
    is_paired: bool,
    unpaired_chain_type: str = "Heavy",
    limit: int = PLOTTING_DATA_LIMIT,
) -> Dict[str, pd.DataFrame]:
    """
    Fetch amino acid distribution per CDR region for search hits via SQL aggregation.
    Returns overall distribution (no per-V-family breakdown) for each CDR type.
    Uses the same WHERE clause as the search; limit matches plotting limit.
    """
    where_clause = build_plotting_where_clause(
        engine, search_params, is_paired, unpaired_chain_type
    )
    table_name = "antibodies"
    if not is_paired:
        table_name = engine.chain_views.get(unpaired_chain_type, "antibodies")

    # CDR AA columns to query: (column_name, result_key)
    if is_paired:
        cdr_specs = [
            ("cdr1_aa_heavy", "cdr1_heavy"),
            ("cdr2_aa_heavy", "cdr2_heavy"),
            ("cdr3_aa_heavy", "cdr3_heavy"),
            ("cdr1_aa_light", "cdr1_light"),
            ("cdr2_aa_light", "cdr2_light"),
            ("cdr3_aa_light", "cdr3_light"),
        ]
    else:
        cdr_specs = [
            ("cdr1_aa", "cdr1"),
            ("cdr2_aa", "cdr2"),
            ("cdr3_aa", "cdr3"),
        ]

    valid_aa_list = "','".join(_CDR_AA_VALID)
    result: Dict[str, pd.DataFrame] = {}

    available = set(engine.schema.get("available_columns", []))
    for cdr_col, key in cdr_specs:
        if available and cdr_col not in available:
            continue
        query = f"""
        WITH limited AS (
            SELECT {cdr_col} AS cdr_aa
            FROM {table_name}
            WHERE {where_clause} AND {cdr_col} IS NOT NULL AND length({cdr_col}) > 0
            LIMIT {limit}
        ),
        expanded AS (
            SELECT unnest(str_split(cdr_aa, '')) AS aa FROM limited
        )
        SELECT aa, COUNT(*)::BIGINT AS cnt
        FROM expanded
        WHERE aa IN ('{valid_aa_list}')
        GROUP BY aa
        """
        try:
            df = engine.conn.execute(query).df()
            if df.empty:
                continue
            total = df["cnt"].sum()
            df["percent"] = (df["cnt"] / total * 100).round(2) if total > 0 else 0.0
            result[key] = df
        except Exception:
            continue

    return result


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
    statistics: Optional[Dict[str, Any]] = None,
    aa_distributions: Optional[Dict[str, pd.DataFrame]] = None,
    spider_mode: str = "per_aa",
    show_spider_toggle: bool = True,
    show_gene_group_control: bool = True,
) -> None:
    """
    Render plots for unpaired search results.
    
    Args:
        sequences_df: Sequences dataframe
        search_params: Search parameters dictionary
    """
    aa_distributions = aa_distributions or {}
    if chain_type.lower() == "light":
        render_light_chain_plots(
            sequences_df, search_params, prefix="", collector=collector,
            aa_distributions=aa_distributions,
            spider_mode=spider_mode,
            show_toggle=show_spider_toggle,
            show_gene_group_control=show_gene_group_control,
        )
    else:
        render_heavy_chain_plots(
            sequences_df, search_params, prefix="", collector=collector,
            aa_distributions=aa_distributions,
            spider_mode=spider_mode,
            show_gene_group_control=show_gene_group_control,
        )

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


def _apply_heatmap_axis_outline(fig: go.Figure) -> go.Figure:
    """Draw a black box outline around a heatmap (same as paired V/J pairing plots)."""
    fig.update_xaxes(showline=True, linewidth=1, linecolor="black", mirror=True)
    fig.update_yaxes(showline=True, linewidth=1, linecolor="black", mirror=True)
    return fig


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
    heading_icon = ":material/genetics:" if chain_type == "Heavy" else "🧬"
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
        icon_heading("paired", f"Inferred {heading_chain} chain Gene Families", level=4)
        
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
                    _apply_heatmap_axis_outline(fig)
                    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_DISPLAY_CONFIG, key=f"inferred_{chain_type.lower()}_v_plot")
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
                    _apply_heatmap_axis_outline(fig)
                    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_DISPLAY_CONFIG, key=f"inferred_{chain_type.lower()}_j_plot")
    else:
        # Light chain: V, J gene plots (2 columns)
        # V inferred plot in column 0, J inferred plot in column 1
        icon_heading("paired", f"Inferred {heading_chain} Gene Families", level=4)

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
                _apply_heatmap_axis_outline(fig)
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_DISPLAY_CONFIG, key=f"inferred_light_{gene_type.lower()}_plot_{i}")

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
            _apply_heatmap_axis_outline(fig)
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
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None,
    aa_distributions: Optional[Dict[str, pd.DataFrame]] = None,
    spider_mode: str = "per_aa",
) -> None:
    """
    Render plots for paired search results.
    
    Args:
        sequences_df: Sequences dataframe
        search_params: Search parameters dictionary
    """
    _sync_gene_group_mode_from_widget()
    col1, col2 = st.columns(2)
    
    aa_distributions = aa_distributions or {}
    with col1:
        icon_heading("heavy", "Heavy Chain", level=4, margin_top=0.5)
        render_heavy_chain_plots(
            sequences_df, search_params, prefix="heavy_", collector=collector,
            aa_distributions=aa_distributions,
            spider_mode=spider_mode,
            show_gene_group_control=False,
        )
    
    with col2:
        icon_heading("light", "Light Chain", level=4, margin_top=0.5)
        render_light_chain_plots(
            sequences_df, search_params, prefix="light_", collector=collector,
            aa_distributions=aa_distributions,
            spider_mode=spider_mode,
            show_toggle=False,
            show_gene_group_control=False,
        )

    _render_gene_group_control()

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

    # Heatmpap VHxVL
    fig = px.imshow(
        heatmap_df,
        labels=dict(x="Light V Gene", y="Heavy V Gene", color="Pair Count"),
        color_continuous_scale=[(0.0, "#F8F8F8"), (0.5, "#D8DEE9"), (1.0, "#4C6085")],
        aspect="auto"
    )

    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=True)
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=True)

    fig.update_layout(
        title={
            "text": "V<sub>H</sub> × V<sub>L</sub> Gene Pairing",
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 18}
        },
        margin=dict(l=60, r=60, t=60, b=60),
        xaxis=dict(side="bottom"),
        yaxis=dict(autorange="reversed"),
        coloraxis_colorbar=dict(title="Pairs")
    )
    icon_heading("paired", "Heavy × Light V Gene Pairing", level=4, margin_top=0.5)

    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_DISPLAY_CONFIG)

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
        color_continuous_scale=[(0.0, "#F8F8F8"), (0.5, "#F7D5DB"), (1.0, "#CB4154")],
        aspect="auto"
    )

    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=True)
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=True)

    fig.update_layout(
        title={
            "text": "J<sub>H</sub> × J<sub>L</sub> Gene Pairing",
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 18}
        },
        margin=dict(l=60, r=60, t=60, b=60),
        xaxis=dict(side="bottom"),
        yaxis=dict(autorange="reversed"),
        coloraxis_colorbar=dict(title="Pairs")
    )

    icon_heading("paired", "Heavy × Light J Gene Pairing", level=4, margin_top=0.5)
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_DISPLAY_CONFIG)

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
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None,
    aa_distributions: Optional[Dict[str, pd.DataFrame]] = None,
    spider_mode: str = "per_aa",
    show_gene_group_control: bool = True,
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
    aa_distributions = aa_distributions or {}
    has_spiders = any(
        _cdr_length_col_to_aa_key(p[1], prefix) in aa_distributions
        for p in cdr_plots
    )
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
        # Toggle directly above spider plots (below histograms); only in Heavy to avoid duplicate key
        if has_spiders:
            if SPIDER_PLOT_MODE_KEY not in st.session_state:
                st.session_state[SPIDER_PLOT_MODE_KEY] = "per_aa"
            by_property = st.toggle(
                "Group by property",
                value=(st.session_state.get(SPIDER_PLOT_MODE_KEY, "per_aa") == "by_property"),
                key="cdr_spider_plot_mode_toggle",
            )
            spider_mode = "by_property" if by_property else "per_aa"
            st.session_state[SPIDER_PLOT_MODE_KEY] = spider_mode
            st.markdown("<div style='margin-top: -0.5rem;'></div>", unsafe_allow_html=True)
        for i, plot_data in enumerate(cdr_plots):
            df, col, title = plot_data[:3]
            aa_key = _cdr_length_col_to_aa_key(col, prefix)
            if aa_key and aa_key in aa_distributions:
                with cols[i]:
                    plot_cdr_aa_spider(
                        aa_distributions[aa_key],
                        f"{title} AA Composition",
                        chain_type="heavy",
                        collector=collector,
                        spider_mode=spider_mode,
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
        group_mode = _sync_gene_group_mode_from_widget()
        cols = st.columns(len(gene_plots))
        for i, plot_data in enumerate(gene_plots):
            with cols[i]:
                if len(plot_data) == 4:
                    df, col, title, is_highlighted = plot_data
                    plot_gene_distribution(
                        df,
                        col,
                        _gene_plot_title_for_mode(title, group_mode),
                        is_highlighted=is_highlighted,
                        chain_type="heavy",
                        collector=collector,
                        group_mode=group_mode,
                    )
                else:
                    df, col, title = plot_data
                    plot_gene_distribution(
                        df,
                        col,
                        _gene_plot_title_for_mode(title, group_mode),
                        chain_type="heavy",
                        collector=collector,
                        group_mode=group_mode,
                    )
        if show_gene_group_control:
            _render_gene_group_control()
    
    if not plots_rendered:
        st.info("No plots available (all filters specified).")


def render_light_chain_plots(
    sequences_df: pd.DataFrame,
    search_params: Dict[str, Any],
    prefix: str = "light_",
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None,
    aa_distributions: Optional[Dict[str, pd.DataFrame]] = None,
    spider_mode: str = "per_aa",
    show_toggle: bool = False,
    show_gene_group_control: bool = True,
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
    aa_distributions = aa_distributions or {}
    has_spiders = any(
        _cdr_length_col_to_aa_key(p[1], prefix) in aa_distributions
        for p in cdr_plots
    )
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
        # Toggle (unpaired Light) or placeholder (paired, to align with Heavy's toggle)
        if has_spiders:
            if show_toggle:
                if SPIDER_PLOT_MODE_KEY not in st.session_state:
                    st.session_state[SPIDER_PLOT_MODE_KEY] = "per_aa"
                by_property = st.toggle(
                    "Group by property",
                    value=(st.session_state.get(SPIDER_PLOT_MODE_KEY, "per_aa") == "by_property"),
                    key="cdr_spider_plot_mode_toggle",
                )
                spider_mode = "by_property" if by_property else "per_aa"
                st.session_state[SPIDER_PLOT_MODE_KEY] = spider_mode
                st.markdown("<div style='margin-top: -0.5rem;'></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='height: 36px;'></div>", unsafe_allow_html=True)
            spider_mode = st.session_state.get(SPIDER_PLOT_MODE_KEY, "per_aa")
        for i, (df, col, title) in enumerate(cdr_plots):
            aa_key = _cdr_length_col_to_aa_key(col, prefix)
            if aa_key and aa_key in aa_distributions:
                if has_spiders:
                    spider_mode = st.session_state.get(SPIDER_PLOT_MODE_KEY, "per_aa")
                with cols[i]:
                    plot_cdr_aa_spider(
                        aa_distributions[aa_key],
                        f"{title} AA Composition",
                        chain_type="light",
                        collector=collector,
                        spider_mode=spider_mode,
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
        group_mode = _sync_gene_group_mode_from_widget()
        cols = st.columns(len(gene_plots))
        for i, plot_data in enumerate(gene_plots):
            with cols[i]:
                if len(plot_data) == 4:
                    df, col, title, is_highlighted = plot_data
                    plot_gene_distribution(
                        df,
                        col,
                        _gene_plot_title_for_mode(title, group_mode),
                        is_highlighted=is_highlighted,
                        chain_type="light",
                        collector=collector,
                        group_mode=group_mode,
                    )
                else:
                    df, col, title = plot_data
                    plot_gene_distribution(
                        df,
                        col,
                        _gene_plot_title_for_mode(title, group_mode),
                        chain_type="light",
                        collector=collector,
                        group_mode=group_mode,
                    )
        if show_gene_group_control:
            _render_gene_group_control()
    
    if not plots_rendered:
        st.info("No plots available (all filters specified).")


def _cdr_length_col_to_aa_key(col: str, prefix: str) -> str:
    """Map CDR length column name to aa_distributions key."""
    if col == "cdr1_length_heavy" or (col.endswith("_heavy") and "cdr1" in col):
        return "cdr1_heavy"
    if col == "cdr2_length_heavy" or (col.endswith("_heavy") and "cdr2" in col):
        return "cdr2_heavy"
    if col == "cdr3_length_heavy" or (col.endswith("_heavy") and "cdr3" in col):
        return "cdr3_heavy"
    if col == "cdr1_length_light" or (col.endswith("_light") and "cdr1" in col):
        return "cdr1_light"
    if col == "cdr2_length_light" or (col.endswith("_light") and "cdr2" in col):
        return "cdr2_light"
    if col == "cdr3_length_light" or (col.endswith("_light") and "cdr3" in col):
        return "cdr3_light"
    if col == "cdr1_length":
        return "cdr1"
    if col == "cdr2_length":
        return "cdr2"
    if col == "cdr3_length":
        return "cdr3"
    return ""


def _aggregate_aa_by_property(aa_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-AA percentages into property groups."""
    if aa_df is None or aa_df.empty or "aa" not in aa_df.columns:
        return pd.DataFrame()
    if "percent" not in aa_df.columns and "cnt" in aa_df.columns:
        total = aa_df["cnt"].sum()
        aa_df = aa_df.copy()
        aa_df["percent"] = (aa_df["cnt"] / total * 100).round(2) if total > 0 else 0.0
    pct_map = aa_df.set_index("aa")["percent"].to_dict() if "percent" in aa_df.columns else {}
    rows = []
    for group_name, aas in _AA_PROPERTY_GROUPS.items():
        pct = sum(float(pct_map.get(a, 0)) for a in aas)
        rows.append({"group": group_name, "percent": round(pct, 2)})
    return pd.DataFrame(rows)


def plot_cdr_aa_spider(
    aa_df: pd.DataFrame,
    title: str,
    chain_type: str = "heavy",
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None,
    spider_mode: str = "per_aa",
) -> None:
    """
    Plot CDR amino acid distribution as a radar/spider chart.
    aa_df must have columns 'aa' and 'percent' (or 'cnt' to compute percent).
    spider_mode: 'per_aa' for individual AAs, 'by_property' for property groups.
    """
    if aa_df is None or aa_df.empty or "aa" not in aa_df.columns:
        return
    if "percent" not in aa_df.columns and "cnt" in aa_df.columns:
        total = aa_df["cnt"].sum()
        aa_df = aa_df.copy()
        aa_df["percent"] = (aa_df["cnt"] / total * 100).round(2) if total > 0 else 0.0
    if "percent" not in aa_df.columns:
        return

    if spider_mode == "by_property":
        plot_df = _aggregate_aa_by_property(aa_df)
        if plot_df.empty:
            return
        theta = list(plot_df["group"])
        r = list(plot_df["percent"])
    else:
        # Per AA: ensure all 20 AAs in consistent order; fill missing with 0
        pct_map = aa_df.set_index("aa")["percent"].to_dict()
        theta = list(_CDR_AA_VALID)
        r = [float(pct_map.get(a, 0)) for a in theta]
    fig = go.Figure(data=go.Scatterpolar(
        r=r,
        theta=theta,
        fill="toself",
        name=title,
    ))
    if chain_type == "light":
        color = "#CB4154"
    else:
        color = "#4C6085"
    fig.update_traces(
        line_color=color,
        fillcolor=color,
        opacity=0.4,
    )
    max_r = max(r) * 1.1 if r else 10
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, max_r])),
        showlegend=False,
        title=dict(text=title, x=0.5, xanchor="center"),
        height=260,
        margin=dict(l=60, r=60, t=50, b=40),
    )
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_DISPLAY_CONFIG)
    if collector is not None:
        collector.append((f"aa_spider_{title.replace(' ', '_')}", prepare_export_figure(fig), aa_df.copy()))


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
    display_title = f"{title}" if is_highlighted else title
    title_config = {
        'text': display_title,
        'x': 0.5,
        'xanchor': 'center'
    }
    if is_highlighted:
        title_config['font'] = {'color': '#B4DCEA', 'size': 16}
    
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

    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_DISPLAY_CONFIG)

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
    collector: Optional[List[Tuple[str, go.Figure, Optional[pd.DataFrame]]]] = None,
    group_mode: str = "allele",
) -> None:
    """
    Plot gene distribution as a bar chart (top N genes).
    
    Args:
        df: Dataframe with sequences
        column: Column name containing gene calls
        title: Title for the plot
        max_genes: Maximum number of genes to display (default: 15)
        is_highlighted: Whether this parameter was used in the search (for highlighting)
        group_mode: allele | subfamily | family aggregation level
    """
    if column not in df.columns:
        return
    
    # Get gene counts (optionally aggregated by subfamily/family)
    if group_mode in ("subfamily", "family"):
        grouped = df[column].map(lambda g: _map_gene_to_group_label(g, group_mode))
        gene_counts = grouped.value_counts().head(max_genes)
        y_label = "Subfamily" if group_mode == "subfamily" else "Family"
    else:
        gene_counts = df[column].value_counts().head(max_genes)
        y_label = "Gene"
    
    if len(gene_counts) == 0:
        return
    
    # Prepare title with highlighting
    display_title = f"{title}" if is_highlighted else title
    title_config = {
        'text': display_title,
        'x': 0.5,
        'xanchor': 'center'
    }
    if is_highlighted:
        title_config['font'] = {'color': '#B4DCEA', 'size': 16}  # Orange-red color for highlighting
    
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

    # Anchor color scale at 0 so the top count always maps to the dark end.
    # Without this, a single bar (e.g. one family after grouping) sits mid-scale.
    max_count = float(gene_counts.max()) if len(gene_counts) else 1.0
    color_range_max = max_count if max_count > 0 else 1.0

    # Create bar chart
    fig = px.bar(
        x=gene_counts.values,
        y=gene_counts.index,
        orientation='h',
        title=display_title,
        labels={'x': 'Count', 'y': y_label},
        color=gene_counts.values,
        color_continuous_scale=color_scale,
        range_color=[0, color_range_max],
    )
    
    fig.update_layout(
        height=400,  # Fixed height for consistent display across all gene plots
        showlegend=False,
        margin=dict(l=120, r=40, t=60, b=70),
        yaxis={'categoryorder': 'total ascending'},
        title=title_config,
        xaxis_title="Count",
        yaxis_title=y_label
    )
    
    fig.update_coloraxes(
        colorscale=color_scale,
        showscale=False,
        cmin=0,
        cmax=color_range_max,
    )

    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_DISPLAY_CONFIG)

    if collector is not None:
        export_df = gene_counts.reset_index()
        export_df.columns = [y_label.lower(), "count"]
        export_df["chain_type"] = chain_type
        export_df["group_mode"] = group_mode
        collector.append((f"{chain_type}_{title}", prepare_export_figure(fig), export_df.copy()))


# --- Donor precursor-frequency boxplot (publication-style axis + site box styling) ---

DONOR_HPM_BIN_LABEL = "≤0.01"
DONOR_HPM_BIN_VALUE = -2.0  # log10(0.01)
DONOR_HPM_DEFAULT_Y_RANGE = (DONOR_HPM_BIN_VALUE - 0.10, 4.0)


def _normalize_donor_stats_columns(stats_df: pd.DataFrame) -> pd.DataFrame:
    df = stats_df.copy()
    aliases = {"per_million": "hits_per_million", "total": "total_sequences"}
    for source, target in aliases.items():
        if source in df.columns and target not in df.columns:
            df[target] = df[source]
    for col in ("total_sequences", "hits", "hits_per_million", "per_million"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def prepare_donor_plot_data(
    stats_df: pd.DataFrame,
    statistics: Dict[str, Any],
    *,
    include_zero_hit_donors: bool = True,
    apply_sequence_threshold: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Prepare donor-level HPM data for the precursor-frequency plot.

    Optionally keeps only donors above the sequence threshold and/or includes
    zero-hit donors. Bins log10(HPM) <= -2 onto DONOR_HPM_BIN_VALUE (≤0.01).
    """
    statistics = statistics or {}
    total_hits = statistics.get("total_hits") or 0
    total_sequences = statistics.get("total_sequences") or 0
    if total_hits <= 0 or total_sequences <= 0:
        return pd.DataFrame(), {"error": "Insufficient overall statistics"}

    overall_frequency = total_hits / total_sequences
    required_sequences = int(np.ceil(10 / overall_frequency))

    df = _normalize_donor_stats_columns(stats_df)
    if "total_sequences" in df.columns:
        df = df[df["total_sequences"] > 0].copy()

    if apply_sequence_threshold:
        filtered = df[df["total_sequences"] >= required_sequences].copy()
    else:
        filtered = df.copy()

    n_zero_in_pool = int((filtered["hits"] == 0).sum()) if "hits" in filtered.columns else 0

    if not include_zero_hit_donors and "hits" in filtered.columns:
        filtered = filtered[filtered["hits"] > 0].copy()

    filtered["hits_per_million"] = np.where(
        filtered["total_sequences"] > 0,
        filtered["hits"].astype(float) / filtered["total_sequences"].astype(float) * 1e6,
        np.nan,
    )

    hpm = filtered["hits_per_million"].astype(float).to_numpy()
    log_vals = np.full(hpm.shape, float("-inf"), dtype=float)
    positive = hpm > 0
    log_vals[positive] = np.log10(hpm[positive])
    filtered["orig_log10_hits"] = log_vals
    filtered["is_binned"] = log_vals <= DONOR_HPM_BIN_VALUE
    filtered["log10_hits"] = np.where(filtered["is_binned"], DONOR_HPM_BIN_VALUE, log_vals)

    meta = {
        "overall_frequency": overall_frequency,
        "required_sequences": required_sequences,
        "apply_sequence_threshold": apply_sequence_threshold,
        "n_input": len(df),
        "n_after_threshold": int((df["total_sequences"] >= required_sequences).sum()),
        "n_plotted": len(filtered),
        "n_zero_hit_included": int((filtered["hits"] == 0).sum()) if "hits" in filtered.columns else 0,
        "n_zero_hit_above_threshold": n_zero_in_pool,
        "include_zero_hit_donors": include_zero_hit_donors,
        "n_binned_le_0_01": int(filtered["is_binned"].sum()) if len(filtered) else 0,
        "bin_label": DONOR_HPM_BIN_LABEL,
        "bin_value": DONOR_HPM_BIN_VALUE,
        "y_range": DONOR_HPM_DEFAULT_Y_RANGE,
    }
    return filtered, meta


def _fmt_donor_hpm(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    if value == 0:
        return "0"
    if abs(value) >= 1000:
        return f"{value:,.4g}"
    return f"{value:.4g}"


def compute_donor_plot_summary_stats(
    filtered_df: pd.DataFrame,
    meta: Dict[str, Any],
) -> pd.DataFrame:
    """Summary metrics for donors included in the precursor-frequency plot."""
    if filtered_df is None or filtered_df.empty:
        return pd.DataFrame(columns=["Metric", "Value"])

    n = len(filtered_df)
    n_zero = int((filtered_df["hits"] == 0).sum()) if "hits" in filtered_df.columns else 0
    zero_pct = (100.0 * n_zero / n) if n else 0.0
    threshold = meta.get("required_sequences", float("nan"))
    include_zeros = meta.get("include_zero_hit_donors", True)
    n_zero_above = meta.get("n_zero_hit_above_threshold", n_zero)

    linear = filtered_df["hits_per_million"].astype(float).to_numpy()
    lin_mean = float(np.nanmean(linear))
    lin_median = float(np.nanmedian(linear))
    lin_q1, lin_q3 = [float(x) for x in np.nanpercentile(linear, [25, 75])]
    lin_iqr = lin_q3 - lin_q1

    if include_zeros:
        zero_hit_value = f"{n_zero:,} ({zero_pct:.1f}%)"
    else:
        zero_hit_value = f"excluded ({n_zero_above:,})"

    apply_threshold = meta.get("apply_sequence_threshold", True)
    if apply_threshold and np.isfinite(threshold):
        threshold_value = f"≥ {int(threshold):,} sequences"
    elif np.isfinite(threshold):
        threshold_value = f"not applied (all donors; ref. ≥ {int(threshold):,})"
    else:
        threshold_value = "—"

    rows = [
        ("Donors in plot", f"{n:,}"),
        ("Sequence threshold", threshold_value),
        ("Zero-hit donors", zero_hit_value),
        ("Mean", f"{_fmt_donor_hpm(lin_mean)} /M"),
        ("Median", f"{_fmt_donor_hpm(lin_median)} /M"),
        (
            "IQR",
            f"{_fmt_donor_hpm(lin_iqr)}  [Q1={_fmt_donor_hpm(lin_q1)}, Q3={_fmt_donor_hpm(lin_q3)}]",
        ),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def _donor_hpm_tick_label(log_val: float) -> str:
    if int(round(log_val)) == int(DONOR_HPM_BIN_VALUE):
        return DONOR_HPM_BIN_LABEL
    ival = int(round(log_val))
    if ival == -1:
        return "0.1"
    if ival == 0:
        return "1"
    if ival > 0:
        return f"{10 ** ival:,}"
    return ""


def _resolve_donor_hpm_y_axis_range(
    log10_hits: np.ndarray,
    *,
    min_upper: float = 2.0,
) -> Tuple[float, float]:
    """Floor at ≤0.01; upper ≥100, expanding when data exceeds that."""
    finite = np.asarray(log10_hits, dtype=float)
    finite = finite[np.isfinite(finite)]
    data_max = float(np.max(finite)) if finite.size else DONOR_HPM_BIN_VALUE
    upper = max(float(min_upper), float(np.ceil(data_max - 1e-12)))
    return (DONOR_HPM_BIN_VALUE - 0.10, upper)


def build_donor_hits_figure(
    filtered_df: pd.DataFrame,
    meta: Dict[str, Any],
    *,
    title: Optional[str] = None,
    height: int = 420,
    margin: Optional[Dict[str, int]] = None,
    dynamic_y_max: bool = True,
    chain_type: str = "Heavy",
) -> Optional[go.Figure]:
    """Build the precursor-frequency donor boxplot (log10 axis with ≤0.01 bin)."""
    if filtered_df is None or filtered_df.empty:
        return None

    y_values = filtered_df["log10_hits"].astype(float)
    donor_labels = filtered_df.get("subject", pd.Series(index=filtered_df.index, dtype=str)).fillna("Unknown")
    hpm = filtered_df["hits_per_million"].astype(float)

    required = meta.get("required_sequences", 0)
    if dynamic_y_max:
        y_axis_range = _resolve_donor_hpm_y_axis_range(y_values.to_numpy())
    else:
        y_axis_range = DONOR_HPM_DEFAULT_Y_RANGE
    upper = int(y_axis_range[1])
    yticks = [DONOR_HPM_BIN_VALUE] + list(range(int(DONOR_HPM_BIN_VALUE) + 1, upper + 1))
    ticktext = [_donor_hpm_tick_label(v) for v in yticks]

    if title is None:
        title = (
            f"Precursor Frequency by Donor"
            f"<br><sup>Donors with ≥ {required:,} sequences</sup>"
        )

    # Match heavy/light plot palette used elsewhere (gene bars, spiders)
    if (chain_type or "Heavy").lower() == "light":
        marker_color = "rgb(203, 65, 84)"       # #CB4154
        line_color = "rgba(203, 65, 84, 0.5)"
        fill_color = "rgba(203, 65, 84, 0.2)"
    else:
        marker_color = "rgb(76, 96, 133)"       # #4C6085
        line_color = "rgba(76, 96, 133, 0.5)"
        fill_color = "rgba(76, 96, 133, 0.2)"

    fig = go.Figure()
    fig.add_trace(
        go.Box(
            y=y_values,
            name="Donors",
            boxpoints="all",
            jitter=0.4,
            pointpos=0,
            marker=dict(
                size=8,
                opacity=0.85,
                line=dict(width=0.2, color="grey"),
                color=marker_color,
            ),
            line=dict(color=line_color, width=1),
            fillcolor=fill_color,
            customdata=np.column_stack(
                [
                    donor_labels.to_numpy(),
                    hpm.to_numpy(),
                ]
            ),
            hovertemplate=(
                "Subject: %{customdata[0]}<br>"
                "Hits/Million: %{customdata[1]:,.4g}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title={
            "text": title,
            "x": 0.5,
            "xanchor": "center",
        },
        showlegend=False,
        height=height,
        boxgroupgap=0.3,
        margin=margin or dict(l=70, r=20, t=70, b=30),
        template="plotly_white",
        yaxis=dict(
            title="Precursor Frequency (Per Million)",
            type="linear",
            range=list(y_axis_range),
            tickmode="array",
            tickvals=yticks,
            ticktext=ticktext,
            gridcolor="rgba(0,0,0,0.15)",
            zeroline=False,
        ),
    )
    return fig


def render_subject_hits_boxplot(
    stats_df: pd.DataFrame,
    statistics: Dict[str, Any],
    filtered_df: Optional[pd.DataFrame] = None,
    meta: Optional[Dict[str, Any]] = None,
    chain_type: str = "Heavy",
) -> None:
    """
    Render donor-level hits-per-million distribution.

    Keeps zero-hit donors that pass the sequence threshold (when enabled),
    recomputes HPM, bins values ≤0.01 onto a fixed log10 axis, and shows a
    box + jittered points.

    Args:
        stats_df: Statistics dataframe per subject
        statistics: Overall statistics dictionary for the current search
        filtered_df: Optional precomputed plot-ready donor frame
        meta: Optional metadata from prepare_donor_plot_data
        chain_type: "Heavy" or "Light" — sets marker/box colors
    """
    st.session_state.pop("latest_subject_hits_plot", None)
    statistics = statistics or {}

    # Handle case where stats_df might be None (from old API)
    if stats_df is None and filtered_df is None:
        st.info("Subject statistics not available.")
        return

    if filtered_df is None:
        if stats_df is None or stats_df.empty:
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

        # Need at least subject/hits/total_sequences; HPM is recomputed for the plot
        working_df = stats_df.copy()
        column_aliases = {
            "per_million": "hits_per_million",
            "total": "total_sequences",
        }
        for source, target in column_aliases.items():
            if source in working_df.columns and target not in working_df.columns:
                working_df[target] = working_df[source]

        required_columns = {"total_sequences", "hits"}
        missing_columns = required_columns.difference(working_df.columns)
        if missing_columns:
            available_cols = list(working_df.columns)
            st.warning(
                f"Subject statistics missing required fields for donor plotting.\n"
                f"Required: {required_columns}\n"
                f"Available: {available_cols}\n"
                f"Missing: {missing_columns}"
            )
            return

        filtered_df, meta = prepare_donor_plot_data(working_df, statistics)
        if meta.get("error"):
            st.info(meta["error"])
            return

    meta = meta or {}
    if meta.get("error"):
        st.info(meta["error"])
        return

    if filtered_df is None or filtered_df.empty:
        st.info("No donors meet the minimum sequence threshold for plotting.")
        return

    fig = build_donor_hits_figure(
        filtered_df,
        meta,
        title="Precursor Frequency by Donor",
        height=380,
        margin=dict(l=50, r=20, t=45, b=15),
        chain_type=chain_type,
    )
    if fig is None:
        st.info("Unable to render donor plot.")
        return

    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_DISPLAY_CONFIG)

    export_cols = [
        c for c in [
            "subject",
            "total_sequences",
            "hits",
            "hits_per_million",
            "log10_hits",
            "is_binned",
        ]
        if c in filtered_df.columns
    ]
    export_df = filtered_df[export_cols].copy()
    if "hits_per_million" in export_df.columns:
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


