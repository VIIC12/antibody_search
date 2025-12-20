"""
Results rendering component for displaying search results.

This module provides functions to render search results including
statistics, sequences table, and download options.
"""

import streamlit as st
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from textwrap import dedent
import pandas as pd

from components.search.results_display import (
    format_results_dataframe,
    get_column_config,
    get_stats_column_config
)
from components.search.download_utils import (
    create_parquet_file,
    generate_filename_base,
    prepare_stats_download,
    prepare_full_results_download_background,
    prepare_fasta_download_background
)
from components.search.search_execution import execute_search
from components.search.results_plotting import (
    render_results_plots,
    render_subject_hits_boxplot,
)
from src.search_engine import AntibodySearchEngine
from components.search.styling import render_chain_heading




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

RESULTS_HEADING_SVG = dedent("""
<svg width="34" height="34" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect x="6" y="10" width="24" height="24" rx="6" stroke="#4F46E5" stroke-width="3"/>
<path d="M20 28L30 38" stroke="#4F46E5" stroke-width="3" stroke-linecap="round"/>
<circle cx="18" cy="22" r="6" stroke="#4F46E5" stroke-width="3"/>
<path d="M36 12L40 12C41.1046 12 42 12.8954 42 14L42 34C42 35.1046 41.1046 36 40 36L28 36" stroke="#4F46E5" stroke-width="3" stroke-linecap="round"/>
</svg>
""").strip()


def render_results_header() -> None:
    """
    Render the main search results heading with a custom SVG icon.
    """
    st.markdown(
        dedent(f"""
        <div style="display:flex;align-items:center;gap:0.75rem;margin:0.5rem 0 1rem;">
        {RESULTS_HEADING_SVG}
        <h2 style="margin:0;font-weight:600;color:inherit;">Search Results</h2>
        </div>
        """).strip(),
        unsafe_allow_html=True,
    )


def render_search_results(
    sequences_sample_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    statistics: Dict[str, Any],
    is_paired: bool,
    search_params: Dict[str, Any],
    engine: AntibodySearchEngine,
    show_toast: bool = True
) -> None:
    """
    Render complete search results including statistics, sequences, and downloads.
    
    Args:
        sequences_sample_df: Sample sequences dataframe
        stats_df: Statistics dataframe
        statistics: Statistics dictionary
        is_paired: Whether this is a paired search
        search_params: Search parameters dictionary
        engine: Search engine instance
        show_toast: Whether to show the success toast notification (default: True)
    """
    # Show success toast only if requested (i.e., for new searches, not cached results)
    if show_toast:
        st.toast(f"✅ Search completed! Found {statistics['total_hits']:,} sequences", icon="🎉")
    
    # Display results
    render_results_header()
    
    # Statistics metrics
    render_statistics_metrics(statistics)
    
    # Download buttons (Statistics CSV and Full Results) - above Sample Sequences
    render_full_download_button(
        sequences_sample_df, statistics, is_paired,
        search_params, engine, stats_df
    )
    
    # Section 1: Sample Sequences (table)
    render_sequences_table(
        sequences_sample_df, statistics, is_paired,
        search_params, engine, stats_df
    )

    # Section 2: Result Distributions (subject statistics + plots)
    st.markdown("### 📊 Result Distributions")
    render_subject_statistics(stats_df, statistics, heading_level=4)
    render_results_plots(
        sequences_sample_df,
        statistics,
        is_paired,
        search_params,
        engine,
        show_heading=False
    )
    
    # Search parameters expander
    render_search_parameters_expander(statistics, is_paired)


def render_statistics_metrics(statistics: Dict[str, Any]) -> None:
    """
    Render statistics metrics in columns.
    
    Args:
        statistics: Statistics dictionary
    """
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Total Hits", f"{statistics['total_hits']:,}")
    
    with col2:
        st.metric("Database Size", f"{statistics['total_sequences']:,}")
    
    with col3:
        st.metric("Hit Percentage", f"{statistics['percentage']}%")
    
    with col4:
        st.metric("Hits per Million", f"{statistics.get('per_million', 0):,.1f}")
    
    with col5:
        st.metric("Search Time", f"{statistics['search_time']}s")


def render_subject_statistics(
    stats_df: pd.DataFrame,
    statistics: Dict[str, Any],
    heading_level: int = 3
) -> None:
    """
    Render statistics by subject table with download button.
    
    Args:
        stats_df: Statistics dataframe
    """
    heading_level = max(1, min(6, heading_level))
    st.markdown(f"{'#' * heading_level} 📊 Statistics by Subject")
    
    content_col, plot_col = st.columns([5, 1])

    with content_col:
        if not stats_df.empty:
            # Sort by percentage descending (high to low)
            display_df = stats_df.copy()
            if 'percentage' in display_df.columns:
                display_df = display_df.sort_values('percentage', ascending=False, na_position='last')
            
            column_config = get_stats_column_config()
            st.dataframe(
                display_df,
                width='stretch',
                height=200,
                column_config=column_config
            )
        else:
            st.info("No results found matching your criteria.")

    with plot_col:
        render_subject_hits_boxplot(stats_df, statistics)


def render_sequences_table(
    sequences_sample_df: pd.DataFrame,
    statistics: Dict[str, Any],
    is_paired: bool,
    search_params: Dict[str, Any] = None,
    engine: AntibodySearchEngine = None,
    stats_df: Optional[pd.DataFrame] = None
) -> None:
    """
    Render sample sequences table.
    
    Args:
        sequences_sample_df: Sample sequences dataframe
        statistics: Statistics dictionary
        is_paired: Whether this is a paired search
        search_params: Search parameters dictionary (optional, needed for download button)
        engine: Search engine instance (optional, needed for download button)
        stats_df: Optional statistics dataframe for CSV download controls
    """
    # Header for sample sequences
    total_hits = statistics.get('total_hits', 0)
    if total_hits > 0:
        st.markdown(
            f"### 🔬 Sample Sequences "
            f"(showing {len(sequences_sample_df)} of {total_hits:,} total hits)"
        )
    else:
        st.markdown("### 🔬 Sample Sequences")
    
    if not sequences_sample_df.empty:
        # Format dataframe for display
        sequences_display = format_results_dataframe(sequences_sample_df, is_paired)
        column_config = get_column_config(is_paired)
        
        st.dataframe(
            sequences_display,
            width='stretch',
            height=200,
            column_config=column_config
        )
    else:
        if total_hits == 0:
            st.info("🔍 **No sequences found matching your search criteria.** Try adjusting your search parameters.")
        else:
            st.info("No sequence data available.")


def render_stats_download_button(
    stats_df: pd.DataFrame,
    search_params: Dict[str, Any],
    is_paired: bool,
    statistics: Optional[Dict[str, Any]] = None
) -> None:
    """
    Render download button for statistics CSV (as ZIP with search parameters).
    
    Args:
        stats_df: Statistics dataframe
        search_params: Search parameters dictionary (including metadata)
        is_paired: Whether the search is paired
        statistics: Optional statistics dictionary for metadata
    """
    if stats_df.empty:
        st.button(
            "📊 Download Statistics (ZIP)",
            disabled=True,
            use_container_width=True,
            type="primary"
        )
        return
    
    # Get selected databases from session state
    selected_databases = st.session_state.get("selected_databases", [])
    stats_zip, filename = prepare_stats_download(
        stats_df, search_params, is_paired, statistics, selected_databases
    )
    
    st.download_button(
        label="⬇ Download Statistics (ZIP)",
        data=stats_zip,
        file_name=filename,
        mime="application/zip",
        use_container_width=True
    )


def render_full_download_button(
    sequences_sample_df: pd.DataFrame,
    statistics: Dict[str, Any],
    is_paired: bool,
    search_params: Dict[str, Any],
    engine: AntibodySearchEngine,
    stats_df: Optional[pd.DataFrame] = None,
    key_suffix: str = ""
) -> None:
    """
    Render buttons for downloading statistics CSV and full dataset as Parquet (async background processing).
    Buttons show status and transform into download buttons when ready.
    
    Args:
        sequences_sample_df: Sample sequences dataframe
        statistics: Statistics dictionary
        is_paired: Whether this is a paired search
        search_params: Search parameters dictionary
        engine: Search engine instance
        stats_df: Statistics dataframe for CSV download
        key_suffix: Optional suffix for session state keys
    """
    import concurrent.futures
    import time
    from streamlit_autorefresh import st_autorefresh
    
    # Inject CSS for spinner animation and consistent button heights
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
    
    /* Ensure consistent button heights across all states */
    .download-button-container {
        width: 100%;
        min-height: 38.4px;
        display: flex;
        align-items: center;
    }
    
    .download-button-container button {
        min-height: 38.4px;
        box-sizing: border-box;
    }
    
    /* Ensure column containers maintain consistent heights for button alignment */
    div[data-testid="column"] {
        display: flex;
        flex-direction: column;
    }
    
    /* Target Streamlit button wrapper divs to maintain consistent height */
    div[data-testid="column"] > div > button[kind="secondary"],
    div[data-testid="column"] > div > button[kind="primary"],
    div[data-testid="column"] > div > button[data-testid="baseButton-secondary"],
    div[data-testid="column"] > div > button[data-testid="baseButton-primary"] {
        min-height: 38.4px;
        box-sizing: border-box;
    }
    </style>
    """, unsafe_allow_html=True)
    
    if not sequences_sample_df.empty:
        base_search_params = dict(search_params or {})
        selected_databases_formatted = []
        session_selected_dbs = st.session_state.get('selected_databases', [])
        loadable_databases = st.session_state.get('loadable_databases_active', []) or session_selected_dbs
        
        for db_path in session_selected_dbs:
            try:
                path_obj = Path(db_path)
                selected_databases_formatted.append(f"{path_obj.parent.name}/{path_obj.name}")
            except Exception:
                selected_databases_formatted.append(str(db_path))
        selected_databases_formatted.sort()

        search_params_with_metadata = dict(base_search_params)
        search_params_with_metadata["selected_databases"] = selected_databases_formatted

        if is_paired:
            chain_label = "paired"
        else:
            chain_label = "heavy"
            if any("Light" in db for db in selected_databases_formatted):
                chain_label = "light"
            else:
                light_keys = [key for key in base_search_params.keys() if key.startswith("light_")]
                if any(light_keys):
                    chain_label = "light"

        download_key_seed = {
            "search_params": base_search_params,
            "selected_databases": selected_databases_formatted,
            "is_paired": is_paired,
            "chain_label": chain_label
        }
        suffix = f"{key_suffix}_" if key_suffix else ""
        download_key = f"{suffix}full_results_{statistics['total_hits']}_{hash(str(download_key_seed))}"
        
        # Session state keys for async full results download
        full_future_key = f"{download_key}_future"
        full_status_key = f"{download_key}_status"
        full_result_key = f"{download_key}_result"
        full_start_time_key = f"{download_key}_start_time"
        
        # Initialize session state
        if full_status_key not in st.session_state:
            st.session_state[full_status_key] = "idle"  # idle, running, completed, failed
        if full_result_key not in st.session_state:
            st.session_state[full_result_key] = None
        if full_start_time_key not in st.session_state:
            st.session_state[full_start_time_key] = None
        
        # Get or create executor (recreate if broken)
        executor_key = f"{download_key}_executor"
        
        def get_or_create_executor():
            executor = st.session_state.get(executor_key)
            if executor is None:
                executor = concurrent.futures.ProcessPoolExecutor(max_workers=2)
                st.session_state[executor_key] = executor
            return executor
        
        executor = get_or_create_executor()
        
        # Check task status (non-blocking)
        def check_full_results_status():
            future = st.session_state.get(full_future_key)
            if future is not None and future.done():
                try:
                    result = future.result()
                    st.session_state[full_future_key] = None
                    st.session_state[full_result_key] = result
                    if result.get('success'):
                        st.session_state[full_status_key] = "completed"
                        st.toast("Full results table is ready for download!", icon="⬇")
                    else:
                        st.session_state[full_status_key] = "failed"
                    return result
                except (concurrent.futures.process.BrokenProcessPool, Exception) as e:
                    # Clear broken executor
                    if executor_key in st.session_state:
                        try:
                            executor = st.session_state[executor_key]
                            executor.shutdown(wait=False)
                        except:
                            pass
                        del st.session_state[executor_key]
                    st.session_state[full_future_key] = None
                    st.session_state[full_status_key] = "failed"
                    st.session_state[full_result_key] = {'success': False, 'error': str(e)}
            return None
        
        # Check status on every run
        check_full_results_status()
        
        # Auto-refresh when generation is running
        if st.session_state[full_status_key] == "running":
            st_autorefresh(interval=2000, key=f"full_results_refresh_{download_key}")
        
        status = st.session_state[full_status_key]
        
        # Estimate phase based on elapsed time
        def estimate_phase(elapsed: float) -> str:
            if elapsed < 3:
                return "Initializing..."
            elif elapsed < 10:
                return "Searching database..."
            elif elapsed < 30:
                return "Processing results..."
            elif elapsed < 60:
                return "Creating Parquet file..."
            else:
                return "Finalizing..."
        
        # Button labels
        button_label = "⬇ Download Full Results Table"
        new_button_label = "⬇ Download FASTA"
        
        # Session state keys for async new download (FASTA)
        new_download_key = f"{suffix}new_download_{statistics['total_hits']}_{hash(str(download_key_seed))}"
        new_future_key = f"{new_download_key}_future"
        new_status_key = f"{new_download_key}_status"
        new_result_key = f"{new_download_key}_result"
        new_start_time_key = f"{new_download_key}_start_time"
        
        # Initialize session state for FASTA download
        if new_status_key not in st.session_state:
            st.session_state[new_status_key] = "idle"  # idle, running, completed, failed
        if new_result_key not in st.session_state:
            st.session_state[new_result_key] = None
        if new_start_time_key not in st.session_state:
            st.session_state[new_start_time_key] = None
        
        # Get or create executor for FASTA (recreate if broken)
        fasta_executor_key = f"{new_download_key}_executor"
        
        def get_or_create_fasta_executor():
            executor = st.session_state.get(fasta_executor_key)
            if executor is None:
                executor = concurrent.futures.ProcessPoolExecutor(max_workers=2)
                st.session_state[fasta_executor_key] = executor
            return executor
        
        # Check task status for FASTA download (non-blocking)
        def check_new_download_status():
            future = st.session_state.get(new_future_key)
            if future is not None and future.done():
                try:
                    result = future.result()
                    st.session_state[new_future_key] = None
                    st.session_state[new_result_key] = result
                    if result.get('success'):
                        st.session_state[new_status_key] = "completed"
                        st.toast("New download is ready!", icon="⬇")
                    else:
                        st.session_state[new_status_key] = "failed"
                    return result
                except (concurrent.futures.process.BrokenProcessPool, Exception) as e:
                    # Clear broken executor
                    if fasta_executor_key in st.session_state:
                        try:
                            executor = st.session_state[fasta_executor_key]
                            executor.shutdown(wait=False)
                        except:
                            pass
                        del st.session_state[fasta_executor_key]
                    st.session_state[new_future_key] = None
                    st.session_state[new_status_key] = "failed"
                    st.session_state[new_result_key] = {'success': False, 'error': str(e)}
            return None
        
        # Check status on every run
        check_new_download_status()
        
        # Auto-refresh when FASTA generation is running
        if st.session_state[new_status_key] == "running":
            st_autorefresh(interval=2000, key=f"new_download_refresh_{new_download_key}")
        
        new_status = st.session_state[new_status_key]
        
        # Estimate phase based on elapsed time for FASTA
        def estimate_new_phase(elapsed: float) -> str:
            if elapsed < 3:
                return "Initializing..."
            elif elapsed < 10:
                return "Processing..."
            elif elapsed < 30:
                return "Generating..."
            elif elapsed < 60:
                return "Finalizing..."
            else:
                return "Almost done..."
        
        # Use column layout to place Statistics CSV, Full Results, and new button side by side
        col_stats, col_full, col_new, _spacer = st.columns([1.5, 1.5, 1.5, 5.5])
        
        # Statistics CSV download button (left column)
        with col_stats:
            render_stats_download_button(stats_df, search_params, is_paired, statistics)
        
        # Full Results download button (middle column)
        with col_full:
            if status == "idle":
                if st.button(
                    button_label,
                    use_container_width=True,
                    key=f"{download_key}_button"
                ):
                    # Get fresh executor (in case previous one was broken)
                    executor = get_or_create_executor()
                    try:
                        # Submit background task (pass search_params with metadata)
                        future = executor.submit(
                            prepare_full_results_download_background,
                            loadable_databases,
                            search_params_with_metadata,  # Includes selected_databases
                            is_paired,
                            chain_label
                        )
                        st.session_state[full_future_key] = future
                        st.session_state[full_start_time_key] = time.time()
                        st.session_state[full_status_key] = "running"
                        st.rerun()
                    except concurrent.futures.process.BrokenProcessPool:
                        # Recreate executor and retry
                        if executor_key in st.session_state:
                            try:
                                old_executor = st.session_state[executor_key]
                                old_executor.shutdown(wait=False)
                            except:
                                pass
                            del st.session_state[executor_key]
                        executor = get_or_create_executor()
                        future = executor.submit(
                            prepare_full_results_download_background,
                            loadable_databases,
                            search_params_with_metadata,
                            is_paired,
                            chain_label
                        )
                        st.session_state[full_future_key] = future
                        st.session_state[full_start_time_key] = time.time()
                        st.session_state[full_status_key] = "running"
                        st.rerun()
            
            elif status == "running":
                elapsed = time.time() - st.session_state[full_start_time_key] if st.session_state[full_start_time_key] else 0
                phase = estimate_phase(elapsed)
                
                # Custom button with CSS spinner
                st.markdown(f"""
                <div style="width: 100%; min-height: 38.4px; display: flex; align-items: center;">
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
                        min-height: 38.4px;
                        box-sizing: border-box;
                    ">
                        <div class="spinner-dark"></div>
                        <span>{phase}</span>
                    </button>
                </div>
                """, unsafe_allow_html=True)
            
            elif status == "completed":
                result = st.session_state[full_result_key]
                if result and result.get('success'):
                    file_size_mb = result.get('file_size_bytes', 0) / 1024 / 1024
                    
                    # The original button becomes the download button
                    st.download_button(
                        label=f"⬇ Download Full Results ({file_size_mb:.2f} MB)",
                        data=result.get('parquet_data', b''),
                        file_name=result.get('filename', 'sequences.parquet'),
                        mime="application/octet-stream",
                        use_container_width=True,
                        type="primary",
                        key=f"download_{download_key}"
                    )
                else:
                    st.button("❌ Generation Failed", disabled=True, key=f"{download_key}_failed", use_container_width=True)
                    error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
                    st.error(f"❌ {error_msg}")
            
            elif status == "failed":
                result = st.session_state[full_result_key]
                error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
                if st.button("🔄 Retry", key=f"{download_key}_retry", use_container_width=True):
                    # Clear broken executor if it exists
                    if executor_key in st.session_state:
                        try:
                            old_executor = st.session_state[executor_key]
                            old_executor.shutdown(wait=False)
                        except:
                            pass
                        del st.session_state[executor_key]
                    st.session_state[full_status_key] = "idle"
                    st.session_state[full_result_key] = None
                    st.session_state[full_start_time_key] = None
                    st.session_state[full_future_key] = None
                    st.rerun()
                else:
                    st.error(f"❌ {error_msg}")
        
        # FASTA download button (right column)
        with col_new:
            if new_status == "idle":
                if st.button(
                    new_button_label,
                    use_container_width=True,
                    key=f"{new_download_key}_button"
                ):
                    # Get fresh executor (in case previous one was broken)
                    fasta_executor = get_or_create_fasta_executor()
                    try:
                        # Submit background task
                        future = fasta_executor.submit(
                            prepare_fasta_download_background,
                            loadable_databases,
                            search_params_with_metadata,
                            is_paired,
                            chain_label
                        )
                        st.session_state[new_future_key] = future
                        st.session_state[new_start_time_key] = time.time()
                        st.session_state[new_status_key] = "running"
                        st.rerun()
                    except concurrent.futures.process.BrokenProcessPool:
                        # Recreate executor and retry
                        if fasta_executor_key in st.session_state:
                            try:
                                old_executor = st.session_state[fasta_executor_key]
                                old_executor.shutdown(wait=False)
                            except:
                                pass
                            del st.session_state[fasta_executor_key]
                        fasta_executor = get_or_create_fasta_executor()
                        future = fasta_executor.submit(
                            prepare_fasta_download_background,
                            loadable_databases,
                            search_params_with_metadata,
                            is_paired,
                            chain_label
                        )
                        st.session_state[new_future_key] = future
                        st.session_state[new_start_time_key] = time.time()
                        st.session_state[new_status_key] = "running"
                        st.rerun()
            
            elif new_status == "running":
                elapsed = time.time() - st.session_state[new_start_time_key] if st.session_state[new_start_time_key] else 0
                phase = estimate_new_phase(elapsed)
                
                # Custom button with CSS spinner
                st.markdown(f"""
                <div style="width: 100%; min-height: 38.4px; display: flex; align-items: center;">
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
                        min-height: 38.4px;
                        box-sizing: border-box;
                    ">
                        <div class="spinner-dark"></div>
                        <span>{phase}</span>
                    </button>
                </div>
                """, unsafe_allow_html=True)
            
            elif new_status == "completed":
                result = st.session_state[new_result_key]
                if result and result.get('success'):
                    file_size_mb = result.get('file_size_bytes', 0) / 1024 / 1024
                    sequence_count = result.get('sequence_count', 0)
                    
                    # The original button becomes the download button
                    st.download_button(
                        label=f"⬇ Download FASTA ({file_size_mb:.2f} MB" if file_size_mb > 0 else f"⬇ Download FASTA ({sequence_count:,} seq)",
                        data=result.get('data', b''),
                        file_name=result.get('filename', 'sequences.fasta.zip'),
                        mime="application/zip",
                        use_container_width=True,
                        type="primary",
                        key=f"download_{new_download_key}"
                    )
                else:
                    st.button("❌ Generation Failed", disabled=True, key=f"{new_download_key}_failed", use_container_width=True)
                    error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
                    st.error(f"❌ {error_msg}")
            
            elif new_status == "failed":
                result = st.session_state[new_result_key]
                error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
                if st.button("🔄 Retry", key=f"{new_download_key}_retry", use_container_width=True):
                    # Clear broken executor if it exists
                    if fasta_executor_key in st.session_state:
                        try:
                            old_executor = st.session_state[fasta_executor_key]
                            old_executor.shutdown(wait=False)
                        except:
                            pass
                        del st.session_state[fasta_executor_key]
                    st.session_state[new_status_key] = "idle"
                    st.session_state[new_result_key] = None
                    st.session_state[new_start_time_key] = None
                    st.session_state[new_future_key] = None
                    st.rerun()
                else:
                    st.error(f"❌ {error_msg}")


def render_search_criteria_display(search_params: Dict[str, Any], is_paired: bool) -> None:
    """
    Render search criteria in a compact format showing the last performed search.
    
    Args:
        search_params: Search parameters dictionary
        is_paired: Whether this is a paired search
    """
    # Handle None or empty search_params
    if not search_params:
        search_params = {}
    
    # Add divider above
    st.divider()
    
    # Show visible notification
    st.info("💡 **You are currently viewing results from the search below.** Modify search parameters above to perform a new search.")
    
    # Use an expander to make it compact and collapsible
    with st.expander("📋 Last Search Parameters", expanded=True):
        # Show selected databases in a compact format
        selected_databases = st.session_state.get('selected_databases', [])
        if selected_databases:
            db_names = []
            for db_path in selected_databases:
                db_name = Path(db_path).name
                parent_name = Path(db_path).parent.name
                db_names.append(f"{parent_name}/{db_name}")
            # Display databases once after building the list
            st.markdown(f"**Databases:** {', '.join(db_names)}")
        
        if is_paired:
            # Paired search - show Heavy and Light chain parameters in columns
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**🧬 Heavy Chain:**")
                _render_chain_criteria_compact(search_params, "heavy_", chain_type="Heavy")
            
            with col2:
                st.markdown("**🔬 Light Chain:**")
                _render_chain_criteria_compact(search_params, "light_", chain_type="Light")
        else:
            # Unpaired search - determine chain type from search_params or databases
            chain_type = _determine_unpaired_chain_type(search_params, selected_databases)
            display_params = dict(search_params)
            st.markdown(f"**{'🧬' if chain_type == 'Heavy' else '🔬'} {chain_type} Chain:**")
            prefix = "heavy_" if chain_type == "Heavy" else "light_"
            _render_chain_criteria_compact(display_params, prefix, chain_type=chain_type)


def _render_chain_criteria(search_params: Dict[str, Any], prefix: str, chain_type: str = "Heavy") -> None:
    """
    Render criteria for a single chain (Heavy or Light).
    
    Args:
        search_params: Search parameters dictionary
        prefix: Prefix for parameter keys ("heavy_", "light_", or "")
    """
    params = []
    
    # V Gene
    v_gene = search_params.get(f'{prefix}v', '')
    if v_gene:
        if chain_type == "Light":
            params.append(f"**V Gene (IGLV/KV):** {v_gene}")
        else:
            params.append(f"**V Gene:** {v_gene}")
    
    # D Gene (only for Heavy chain)
    if prefix in ["heavy_", ""] and chain_type != "Light":
        d_gene = search_params.get(f'{prefix}d', '')
        if d_gene:
            params.append(f"**D Gene:** {d_gene}")

    # J Gene
    j_gene = search_params.get(f'{prefix}j', '')
    if j_gene:
        if chain_type == "Light":
            params.append(f"**J Gene (IGLJ/KJ):** {j_gene}")
        else:
            params.append(f"**J Gene:** {j_gene}")
    
    # CDR Lengths
    for cdr in [1, 2, 3]:
        length_key = f'{prefix}cdr{cdr}_length'
        length = search_params.get(length_key)
        if length is not None:
            params.append(f"**CDR{cdr} Length:** {length}")
    
    # CDR Motifs
    for cdr in [1, 2, 3]:
        motif_key = f'{prefix}cdr{cdr}_motif'
        motif = search_params.get(motif_key, '')
        if motif:
            similarity = search_params.get(f'{prefix}cdr{cdr}_similarity', False)
            mismatches = search_params.get(f'{prefix}cdr{cdr}_mismatches', 0)
            motif_str = f"**CDR{cdr} Motif:** {motif}"
            if similarity:
                motif_str += f" (Similarity search, max {mismatches} mismatches)"
            params.append(motif_str)
    
    if params:
        for param in params:
            st.write(param)
    else:
        st.info("No search criteria specified for this chain.")


def _render_chain_criteria_compact(search_params: Dict[str, Any], prefix: str, chain_type: str = "Heavy") -> None:
    """
    Render criteria for a single chain in a compact format (for expander display).
    
    Args:
        search_params: Search parameters dictionary
        prefix: Prefix for parameter keys ("heavy_", "light_", or "")
        chain_type: Chain type ("Heavy" or "Light")
    """
    params = []
    
    # V Gene
    v_gene = search_params.get(f'{prefix}v', '')
    if v_gene:
        if chain_type == "Light":
            params.append(f"V Gene: {v_gene}")
        else:
            params.append(f"V Gene: {v_gene}")
    
    # D Gene (only for Heavy chain)
    if prefix in ["heavy_", ""] and chain_type != "Light":
        d_gene = search_params.get(f'{prefix}d', '')
        if d_gene:
            params.append(f"D Gene: {d_gene}")

    # J Gene
    j_gene = search_params.get(f'{prefix}j', '')
    if j_gene:
        if chain_type == "Light":
            params.append(f"J Gene: {j_gene}")
        else:
            params.append(f"J Gene: {j_gene}")
    
    # CDR Lengths
    for cdr in [1, 2, 3]:
        length_key = f'{prefix}cdr{cdr}_length'
        length = search_params.get(length_key)
        if length is not None:
            params.append(f"CDR{cdr} Length: {length}")
    
    # CDR Motifs
    for cdr in [1, 2, 3]:
        motif_key = f'{prefix}cdr{cdr}_motif'
        motif = search_params.get(motif_key, '')
        if motif:
            similarity = search_params.get(f'{prefix}cdr{cdr}_similarity', False)
            mismatches = search_params.get(f'{prefix}cdr{cdr}_mismatches', 0)
            motif_str = f"CDR{cdr} Motif: {motif}"
            if similarity:
                motif_str += f" (similarity, max {mismatches} mismatches)"
            params.append(motif_str)
    
    if params:
        # Display as comma-separated list for compactness
        st.caption(" • ".join(params))
    else:
        st.caption("No criteria specified")


def render_search_parameters_expander(statistics: Dict[str, Any], is_paired: bool) -> None:
    """
    Render expander showing search parameters.
    
    Args:
        statistics: Statistics dictionary containing query_params
    """
    with st.expander("🔍 Search Parameters"):
        # Add selected databases information
        st.markdown("**Selected Databases:**")
        selected_databases = st.session_state.get('selected_databases', [])
        for db_path in selected_databases:
            db_name = Path(db_path).name
            parent_name = Path(db_path).parent.name
            st.write(f"• {parent_name}/{db_name}")
        
        st.markdown("**Query Parameters:**")
        formatted_params = _format_query_params_for_display(statistics.get('query_params', {}), is_paired)
        st.json(formatted_params)


def _determine_unpaired_chain_type(search_params: Dict[str, Any], selected_databases: List[str]) -> str:
    """Determine whether an unpaired search should be treated as Heavy or Light."""
    chain_type = (search_params.get('chain_type')
                  or search_params.get('unpaired_chain_type')
                  or ("Light" if any('/Light/' in str(db) for db in selected_databases) else "Heavy"))
    chain_type = chain_type.capitalize()
    if chain_type not in ("Heavy", "Light"):
        chain_type = "Heavy"
    if chain_type == "Light":
        return "Light"
    # Fallbacks if chain_type not explicitly provided
    if search_params.get('light_v') or search_params.get('light_j'):
        return "Light"
    if selected_databases and any('/Light/' in str(db) for db in selected_databases):
        return "Light"
    return "Heavy"


def _format_query_params_for_display(query_params: Dict[str, Any], is_paired: bool) -> Dict[str, Any]:
    """Create a user-friendly copy of query parameters for display."""
    if not query_params:
        return {}
    
    formatted = dict(query_params)
    chain_type = formatted.get('chain_type') or formatted.get('unpaired_chain_type') or "Heavy"
    chain_type = chain_type.capitalize()
    
    if is_paired:
        formatted.pop('chain_type', None)
        formatted.pop('unpaired_chain_type', None)
        return formatted
    
    formatted.pop('unpaired_chain_type', None)
    formatted['chain_type'] = chain_type
    
    if chain_type == "Light":
        formatted = {
            key: value
            for key, value in formatted.items()
            if key.startswith('light_') or key == 'chain_type'
        }
    else:
        formatted = {
            key: value
            for key, value in formatted.items()
            if key.startswith('heavy_') or key == 'chain_type'
        }
    
    return formatted


def render_dual_search_criteria_display(
    heavy_statistics: Dict[str, Any],
    light_statistics: Dict[str, Any]
) -> None:
    """Render search criteria for dual unpaired searches."""
    heavy_params = _format_query_params_for_display(heavy_statistics.get('query_params', {}), False)
    light_params = _format_query_params_for_display(light_statistics.get('query_params', {}), False)
    
    st.markdown("## 🔍 Search Criteria")
    st.divider()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 🧬 Heavy Chain")
        _render_chain_criteria(heavy_params, "heavy_", chain_type="Heavy")
    
    with col2:
        st.markdown("#### 🔬 Light Chain")
        _render_chain_criteria(light_params, "light_", chain_type="Light")


def render_dual_search_parameters_expander(
    heavy_statistics: Dict[str, Any],
    light_statistics: Dict[str, Any]
) -> None:
    """Render expander showing heavy and light search parameters."""
    with st.expander("🔍 Search Parameters"):
        st.markdown("**Selected Databases:**")
        selected_databases = st.session_state.get('selected_databases', [])
        for db_path in selected_databases:
            db_name = Path(db_path).name
            parent_name = Path(db_path).parent.name
            st.write(f"• {parent_name}/{db_name}")
        
        st.markdown("**Heavy Chain Parameters:**")
        heavy_formatted = _format_query_params_for_display(heavy_statistics.get('query_params', {}), False)
        heavy_formatted.pop('chain_type', None)
        heavy_filtered = {key: value for key, value in heavy_formatted.items() if key.startswith('heavy_')}
        st.json(heavy_filtered)
        
        st.markdown("**Light Chain Parameters:**")
        light_query_params = light_statistics.get('query_params', {})
        light_formatted = _format_query_params_for_display(light_query_params, False)
        light_formatted.pop('chain_type', None)
        light_filtered = {key: value for key, value in light_formatted.items() if key.startswith('light_')}
        if not light_filtered:
            # Fallback: map generic keys to light-prefixed ones if no dedicated keys exist
            for base_key, prefix in (('ighv', 'light_v'), ('ighj', 'light_j'), ('cdr1_length', 'light_cdr1_length'),
                                     ('cdr2_length', 'light_cdr2_length'), ('cdr3_length', 'light_cdr3_length'),
                                     ('cdr1_motif', 'light_cdr1_motif'), ('cdr2_motif', 'light_cdr2_motif'),
                                     ('cdr3_motif', 'light_cdr3_motif'),
                                     ('cdr1_similarity', 'light_cdr1_similarity'), ('cdr2_similarity', 'light_cdr2_similarity'),
                                     ('cdr3_similarity', 'light_cdr3_similarity'),
                                     ('cdr1_mismatches', 'light_cdr1_mismatches'), ('cdr2_mismatches', 'light_cdr2_mismatches'),
                                     ('cdr3_mismatches', 'light_cdr3_mismatches')):
                if base_key in light_query_params:
                    light_filtered[prefix] = light_query_params[base_key]
        st.json(light_filtered)


def render_dual_unpaired_results(
    heavy_result: Dict[str, Any],
    light_result: Dict[str, Any],
    engine: AntibodySearchEngine,
    show_toast: bool = False
) -> None:
    """Render results for simultaneous unpaired heavy and light searches."""
    if show_toast:
        st.toast("✅ Heavy and Light searches completed!", icon="🎉")
    
    st.markdown("---")
    render_results_header()
    
    # Heavy section
    render_chain_heading("Heavy Chain Results", "heavy", level=3, icon="🧬")
    render_statistics_metrics(heavy_result['statistics'])
    render_sequences_table(
        heavy_result['sequences_sample_df'],
        heavy_result['statistics'],
        is_paired=False,
        search_params=heavy_result['search_params'],
        engine=engine,
        stats_df=heavy_result['stats_df']
    )
    render_subject_statistics(heavy_result['stats_df'], heavy_result['statistics'], heading_level=4)
    render_results_plots(
        heavy_result['sequences_sample_df'],
        heavy_result['statistics'],
        is_paired=False,
        search_params=heavy_result['search_params'],
        engine=engine
    )
    st.markdown("---")
    
    # Light section
    render_chain_heading("Light Chain Results", "light", level=3, icon="🔬")
    render_statistics_metrics(light_result['statistics'])
    render_sequences_table(
        light_result['sequences_sample_df'],
        light_result['statistics'],
        is_paired=False,
        search_params=light_result['search_params'],
        engine=engine,
        stats_df=light_result['stats_df']
    )
    render_subject_statistics(light_result['stats_df'], light_result['statistics'], heading_level=4)
    render_results_plots(
        light_result['sequences_sample_df'],
        light_result['statistics'],
        is_paired=False,
        search_params=light_result['search_params'],
        engine=engine
    )
    render_dual_search_parameters_expander(
        heavy_result['statistics'],
        light_result['statistics']
    )



