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
    prepare_stats_download,
    prepare_full_results_download_background,
    prepare_fasta_download_background
)
from components.search.search_execution import execute_search
from components.search.results_plotting import (
    render_results_plots,
    render_subject_hits_boxplot,
    prepare_donor_plot_data,
    compute_donor_plot_summary_stats,
)
from src.search_engine import AntibodySearchEngine
from components.search.styling import icon_heading




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

def render_search_results(
    sequences_sample_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    statistics: Dict[str, Any],
    is_paired: bool,
    search_params: Dict[str, Any],
    engine: AntibodySearchEngine,
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
    """
    
    # Visual separation from the search criteria section
    st.markdown("---")
    
    # Display results
    st.markdown("# :material/search_insights: Search Results")
    
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
    
    render_subject_statistics(stats_df, statistics)
    render_results_plots(
        sequences_sample_df,
        statistics,
        is_paired,
        search_params,
        engine
    )
    
    # Search parameters expander
    render_search_parameters_expander(statistics, is_paired)


def _format_hit_percentage(statistics: Dict[str, Any]) -> str:
    """Format overall hit percentage; show <0.01% when tiny but non-zero."""
    try:
        percentage = float(statistics.get("percentage") or 0)
    except (TypeError, ValueError):
        percentage = 0.0
    try:
        total_hits = int(statistics.get("total_hits") or 0)
    except (TypeError, ValueError):
        total_hits = 0

    if total_hits > 0 and percentage < 0.01:
        return "<0.01%"
    return f"{percentage}%"


def render_statistics_metrics(statistics: Dict[str, Any]) -> None:
    """
    Render statistics metrics in columns.
    
    Args:
        statistics: Statistics dictionary
    """
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Database Size", f"{statistics['total_sequences']:,}")
    
    with col2:
        st.metric("Total Hits", f"{statistics['total_hits']:,}")
    
    with col3:
        st.metric("Hit Percentage", _format_hit_percentage(statistics))
    
    with col4:
        st.metric("Search Time", f"{statistics['search_time']}s")

def render_subject_statistics(
    stats_df: pd.DataFrame,
    statistics: Dict[str, Any],
    widget_key_prefix: str = "donor_plot",
) -> None:
    """
    Render statistics by subject, plot summary metrics, and the donor HPM plot.
    
    Args:
        stats_df: Statistics dataframe
        statistics: Overall statistics dictionary for the current search
        widget_key_prefix: Prefix for Streamlit widget keys (unique per chain in dual mode)
    """
    zero_hit_toggle_key = f"{widget_key_prefix}_include_zero_hits"
    threshold_toggle_key = f"{widget_key_prefix}_apply_sequence_threshold"
    if zero_hit_toggle_key not in st.session_state:
        st.session_state[zero_hit_toggle_key] = True
    if threshold_toggle_key not in st.session_state:
        st.session_state[threshold_toggle_key] = True
    include_zero_hit_donors = bool(st.session_state[zero_hit_toggle_key])
    apply_sequence_threshold = bool(st.session_state[threshold_toggle_key])

    plot_filtered_df = None
    plot_meta: Dict[str, Any] = {}
    plot_summary_df = pd.DataFrame(columns=["Metric", "Value"])

    if stats_df is not None and not stats_df.empty:
        working_df = stats_df.copy()
        for source, target in (
            ("per_million", "hits_per_million"),
            ("total", "total_sequences"),
        ):
            if source in working_df.columns and target not in working_df.columns:
                working_df[target] = working_df[source]

        if {"total_sequences", "hits"}.issubset(working_df.columns):
            plot_filtered_df, plot_meta = prepare_donor_plot_data(
                working_df,
                statistics or {},
                include_zero_hit_donors=include_zero_hit_donors,
                apply_sequence_threshold=apply_sequence_threshold,
            )
            if not plot_meta.get("error") and plot_filtered_df is not None and not plot_filtered_df.empty:
                plot_summary_df = compute_donor_plot_summary_stats(
                    plot_filtered_df, plot_meta
                )

    head_subj, head_sum, head_plot = st.columns([4, 2, 1.5])
    with head_subj:
        st.markdown("#### :material/group: Statistics by Subject")
    with head_sum:
        st.markdown("#### :material/analytics: Plot Summary")
    with head_plot:
        st.markdown("#### :material/candlestick_chart: Precursor Frequency")

    content_col, summary_col, plot_col = st.columns([4, 2, 1.5])

    with content_col:
        if stats_df is not None and not stats_df.empty:
            column_config = get_stats_column_config()
            desired_order = [
                "subject",
                "total_sequences",
                "hits",
                "percentage",
                "per_million",
            ]
            ordered_columns = [col for col in desired_order if col in stats_df.columns]
            stats_df_display = stats_df[ordered_columns] if ordered_columns else stats_df
            if "percentage" in stats_df_display.columns:
                stats_df_display = stats_df_display.sort_values(
                    "percentage", ascending=False, kind="mergesort"
                ).reset_index(drop=True)
            st.dataframe(
                stats_df_display,
                width='stretch',
                height=380,
                hide_index=True,
                column_config=column_config
            )
        else:
            st.info("No results found matching your criteria.")

    with summary_col:
        if not plot_summary_df.empty:
            st.dataframe(
                plot_summary_df,
                width="stretch",
                height=250,
                hide_index=True,
                column_config={
                    "Metric": st.column_config.TextColumn("Metric", width="small"),
                    "Value": st.column_config.TextColumn("Value", width="medium"),
                },
            )
        elif plot_meta.get("error"):
            st.info(plot_meta["error"])
        else:
            st.info("Plot summary unavailable (no donors pass the sequence threshold).")

        toggle_col1, toggle_col2 = st.columns(2)
        # Lock while search/plots are busy — toggling mid-run can crash the Streamlit server
        donor_plot_toggles_locked = (
            st.session_state.get("search_status") == "running"
            or bool(st.session_state.get("plotting_controls_locked", False))
        )
        with toggle_col1:
            st.toggle(
                "Apply sequence threshold",
                key=threshold_toggle_key,
                disabled=donor_plot_toggles_locked,
                help=(
                    "When enabled, only donors with enough sequences "
                    "(⌈10 ÷ overall frequency⌉) are included in the plot and Plot Summary. "
                    "When disabled, all donors with >0 sequences are used."
                    + (" Locked while a search or plot load is in progress." if donor_plot_toggles_locked else "")
                ),
            )
        with toggle_col2:
            st.toggle(
                "Include zero-hit donors",
                key=zero_hit_toggle_key,
                disabled=donor_plot_toggles_locked,
                help=(
                    "When enabled, donors in the selected set with zero hits "
                    "are included in the precursor-frequency plot and Plot Summary "
                    "(shown at ≤0.01). When disabled, only donors with ≥1 hit are shown."
                    + (" Locked while a search or plot load is in progress." if donor_plot_toggles_locked else "")
                ),
            )

    with plot_col:
        render_subject_hits_boxplot(
            stats_df,
            statistics,
            filtered_df=plot_filtered_df,
            meta=plot_meta,
        )


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
            f"### :material/table: Sample Sequences "
            f"(showing {len(sequences_sample_df)} of {total_hits:,} total hits)"
        )
    else:
        st.markdown("### :material/table: Sample Sequences")
    
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
            st.info(":material/search_off: **No sequences found matching your search criteria.** Try adjusting your search parameters.")
        else:
            st.info("No sequence data available.")


def render_stats_download_button(
    stats_df: pd.DataFrame,
    search_params: Dict[str, Any],
    is_paired: bool,
    statistics: Optional[Dict[str, Any]] = None,
    key: Optional[str] = None,
) -> None:
    """
    Render download button for statistics CSV (as ZIP with search parameters).

    Args:
        stats_df: Statistics dataframe
        search_params: Search parameters dictionary (including metadata)
        is_paired: Whether the search is paired
        statistics: Optional statistics dictionary for metadata
        key: Optional unique Streamlit key to avoid duplicate element ID when rendered multiple times.
    """
    # Unique key to avoid StreamlitDuplicateElementId when multiple result sets are rendered
    widget_key = key or f"stats_download_{(statistics or {}).get('total_hits', 0)}_{hash(str(search_params))}"

    if stats_df.empty:
        st.button(
            "⬇ Download Statistics (ZIP)",
            disabled=True,
            width='stretch',
            type="primary",
            key=f"{widget_key}_disabled",
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
        width='stretch',
        key=widget_key,
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
        
        # Session state keys for full results download
        full_status_key = f"{download_key}_status"
        full_result_key = f"{download_key}_result"
        
        # Initialize session state
        if full_status_key not in st.session_state:
            st.session_state[full_status_key] = "idle"  # idle, completed, failed
        if full_result_key not in st.session_state:
            st.session_state[full_result_key] = None
        
        status = st.session_state[full_status_key]
        
        # Button labels
        button_label = "⬇ Download Full Results Table"
        new_button_label = "⬇ Download FASTA"
        
        # Session state keys for FASTA download
        new_download_key = f"{suffix}new_download_{statistics['total_hits']}_{hash(str(download_key_seed))}"
        new_status_key = f"{new_download_key}_status"
        new_result_key = f"{new_download_key}_result"
        
        # Initialize session state for FASTA download
        if new_status_key not in st.session_state:
            st.session_state[new_status_key] = "idle"  # idle, completed, failed
        if new_result_key not in st.session_state:
            st.session_state[new_result_key] = None
        
        new_status = st.session_state[new_status_key]
        
        # Use column layout to place Statistics CSV, Full Results, and new button side by side
        col_stats, col_full, col_new, _spacer = st.columns([1.5, 1.5, 1.5, 5.5])
        
        # Statistics CSV download button (left column)
        with col_stats:
            render_stats_download_button(
                stats_df, search_params, is_paired, statistics, key=f"{download_key}_stats"
            )
        
        # Full Results download button (middle column)
        with col_full:
            if status == "idle":
                if st.button(
                    button_label,
                    width='stretch',
                    key=f"{download_key}_button"
                ):
                    with st.spinner("Preparing full results download..."):
                        result = prepare_full_results_download_background(
                            loadable_databases,
                            search_params_with_metadata,
                            is_paired,
                            chain_label
                        )
                    st.session_state[full_result_key] = result
                    st.session_state[full_status_key] = "completed" if result.get("success") else "failed"
                    if result.get("success"):
                        st.toast("Full results table is ready for download!", icon="⬇")
                    st.rerun()
            
            elif status == "completed":
                result = st.session_state[full_result_key]
                if result and result.get('success'):
                    file_size_mb = result.get('file_size_bytes', 0) / 1024 / 1024
                    
                    # Check if this is a large file with download URL
                    if result.get('download_url'):
                        # Large file: redirect to static download link
                        download_url = result.get('download_url')
                        st.markdown(
                            f'<a href="{download_url}" target="_blank" style="text-decoration: none;">'
                            f'<button style="width: 100%; padding: 0.5rem 1rem; background-color: rgb(19, 124, 189); '
                            f'color: white; border: none; border-radius: 0.25rem; cursor: pointer; font-size: 0.875rem;">'
                            f'⬇ Download Full Results ({file_size_mb:.2f} MB) - Opens in new tab</button></a>',
                            unsafe_allow_html=True
                        )
                    else:
                        # Small file: use direct download button
                        st.download_button(
                            label=f"⬇ Download Full Results ({file_size_mb:.2f} MB)",
                            data=result.get('parquet_data', b''),
                            file_name=result.get('filename', 'sequences.csv.gz'),
                            mime="application/octet-stream",
                            width='stretch',
                            type="primary",
                            key=f"download_{download_key}"
                        )
                else:
                    st.button("❌ Generation Failed", disabled=True, key=f"{download_key}_failed", width='stretch')
                    error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
                    st.error(f"❌ {error_msg}")
            
            elif status == "failed":
                result = st.session_state[full_result_key]
                error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
                if st.button("🔄 Retry", key=f"{download_key}_retry", width='stretch'):
                    st.session_state[full_status_key] = "idle"
                    st.session_state[full_result_key] = None
                    st.rerun()
                else:
                    st.error(f"❌ {error_msg}")
        
        # FASTA download button (right column)
        with col_new:
            if new_status == "idle":
                if st.button(
                    new_button_label,
                    width='stretch',
                    key=f"{new_download_key}_button"
                ):
                    with st.spinner("Preparing FASTA download..."):
                        result = prepare_fasta_download_background(
                            loadable_databases,
                            search_params_with_metadata,
                            is_paired,
                            chain_label
                        )
                    st.session_state[new_result_key] = result
                    st.session_state[new_status_key] = "completed" if result.get("success") else "failed"
                    if result.get("success"):
                        st.toast("FASTA download is ready!", icon="⬇")
                    st.rerun()
            
            elif new_status == "completed":
                result = st.session_state[new_result_key]
                if result and result.get('success'):
                    file_size_mb = result.get('file_size_bytes', 0) / 1024 / 1024
                    sequence_count = result.get('sequence_count', 0)
                    
                    # Check if this is a large file with download URL
                    if result.get('download_url'):
                        # Large file: redirect to static download link
                        download_url = result.get('download_url')
                        label = f"⬇ Download FASTA ({file_size_mb:.2f} MB)" if file_size_mb > 0 else f"⬇ Download FASTA ({sequence_count:,} seq)"
                        st.markdown(
                            f'<a href="{download_url}" target="_blank" style="text-decoration: none;">'
                            f'<button style="width: 100%; padding: 0.5rem 1rem; background-color: rgb(19, 124, 189); '
                            f'color: white; border: none; border-radius: 0.25rem; cursor: pointer; font-size: 0.875rem;">'
                            f'{label} - Opens in new tab</button></a>',
                            unsafe_allow_html=True
                        )
                    else:
                        # Small file: use direct download button
                        label = f"⬇ Download FASTA ({file_size_mb:.2f} MB)" if file_size_mb > 0 else f"⬇ Download FASTA ({sequence_count:,} seq)"
                        st.download_button(
                            label=label,
                            data=result.get('data', b''),
                            file_name=result.get('filename', 'sequences.fasta.zip'),
                            mime="application/zip",
                            width='stretch',
                            type="primary",
                            key=f"download_{new_download_key}"
                        )
                else:
                    st.button("❌ Generation Failed", disabled=True, key=f"{new_download_key}_failed", width='stretch')
                    error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
                    st.error(f"❌ {error_msg}")
            
            elif new_status == "failed":
                result = st.session_state[new_result_key]
                error_msg = result.get('error', 'Unknown error') if result else 'Unknown error'
                if st.button("🔄 Retry", key=f"{new_download_key}_retry", width='stretch'):
                    st.session_state[new_status_key] = "idle"
                    st.session_state[new_result_key] = None
                    st.rerun()
                else:
                    st.error(f"❌ {error_msg}")


LAST_SEARCH_INFO_MESSAGE = (
    ":material/info: **You are currently viewing results from the search below.** "
    "Modify the search parameters above to perform a new search."
)


def _render_last_search_header(show_info: bool = True) -> None:
    """Render consistent header for last search criteria sections."""
    st.markdown("## :material/search_gear: Last performed Search Criteria")
    if show_info:
        st.info(LAST_SEARCH_INFO_MESSAGE)


def _render_selected_databases_summary(selected_databases: Optional[List[Any]]) -> None:
    """Show a compact list of the databases used for the rendered search."""
    if not selected_databases:
        return
    
    db_names = []
    for db_path in selected_databases:
        path_obj = Path(str(db_path))
        parent_name = path_obj.parent.name
        db_names.append(f"{parent_name}/{path_obj.name}")
    
    st.caption(f"Databases: {', '.join(db_names)}")


def render_search_criteria_display(
    search_params: Dict[str, Any],
    is_paired: bool,
    selected_databases: Optional[List[Any]] = None
) -> None:
    """
    Render search criteria summary showing the last performed search.
    
    Args:
        search_params: Search parameters dictionary
        is_paired: Whether this is a paired search
        selected_databases: Optional list of database identifiers used for the search
    """
    # Handle None or empty search_params
    if not search_params:
        search_params = {}
    
    if selected_databases is None:
        selected_databases = st.session_state.get('selected_databases', [])
    _render_last_search_header()
    _render_selected_databases_summary(selected_databases)
    
    if is_paired:
        formatted_params = _format_query_params_for_display(search_params, True)
        col1, col2 = st.columns(2)
        
        with col1:
            icon_heading("heavy", "Heavy Chain", 4, margin_top=0.5)
            _render_chain_criteria(formatted_params, "heavy_", chain_type="Heavy")
        
        with col2:  
            icon_heading("light", "Light Chain", 4, margin_top=0.5)
            _render_chain_criteria(formatted_params, "light_", chain_type="Light")
        return
    
    chain_type = _determine_unpaired_chain_type(search_params, selected_databases)
    formatted_params = _format_query_params_for_display(search_params, False)
    prefix = "heavy_" if chain_type == "Heavy" else "light_"
    icon_heading(f"{chain_type.lower()}", f"{chain_type} Chain", 4, margin_top=0.5)
    _render_chain_criteria(formatted_params, prefix, chain_type=chain_type)


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
        st.markdown("No search criteria specified for this chain.")


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
    with st.expander(":material/search: Search Parameters"):
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
    light_statistics: Dict[str, Any],
    selected_databases: Optional[List[Any]] = None
) -> None:
    """Render search criteria for dual unpaired searches."""
    heavy_params = _format_query_params_for_display(heavy_statistics.get('query_params', {}), False)
    light_params = _format_query_params_for_display(light_statistics.get('query_params', {}), False)
    
    if selected_databases is None:
        selected_databases = st.session_state.get('selected_databases', [])
    _render_last_search_header()
    _render_selected_databases_summary(selected_databases)
    
    col1, col2 = st.columns(2)
    
    with col1:
        icon_heading("heavy", "Heavy Chain", 4, margin_top=0.5)
        _render_chain_criteria(heavy_params, "heavy_", chain_type="Heavy")
    
    with col2:
        icon_heading("light", "Light Chain", 4, margin_top=0.5)
        _render_chain_criteria(light_params, "light_", chain_type="Light")


def render_dual_search_parameters_expander(
    heavy_statistics: Dict[str, Any],
    light_statistics: Dict[str, Any]
) -> None:
    """Render expander showing heavy and light search parameters."""
    with st.expander(":material/search: Search Parameters"):
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
) -> None:
    """Render results for simultaneous unpaired heavy and light searches."""
    st.markdown("---")
    st.markdown("# :material/search_insights: Search Results")
    
    # Heavy section
    icon_heading("heavy", "Heavy Chain Results", 3, margin_top=0.5)
    render_statistics_metrics(heavy_result['statistics'])
    # Download buttons (Statistics CSV and Full Results) - above Sample Sequences
    render_full_download_button(
        heavy_result['sequences_sample_df'],
        heavy_result['statistics'],
        is_paired=False,
        search_params=heavy_result['search_params'],
        engine=engine,
        stats_df=heavy_result['stats_df'],
        key_suffix="heavy"
    )
    render_sequences_table(
        heavy_result['sequences_sample_df'],
        heavy_result['statistics'],
        is_paired=False,
        search_params=heavy_result['search_params'],
        engine=engine,
        stats_df=heavy_result['stats_df']
    )
    render_subject_statistics(
        heavy_result['stats_df'],
        heavy_result['statistics'],
        widget_key_prefix="heavy_donor_plot",
    )
    render_results_plots(
        heavy_result['sequences_sample_df'],
        heavy_result['statistics'],
        is_paired=False,
        search_params=heavy_result['search_params'],
        engine=engine
    )
    st.markdown("---")
    
    # Light section
    icon_heading("light", "Light Chain Results", 3, margin_top=0.5)
    render_statistics_metrics(light_result['statistics'])
    # Download buttons (Statistics CSV and Full Results) - above Sample Sequences
    render_full_download_button(
        light_result['sequences_sample_df'],
        light_result['statistics'],
        is_paired=False,
        search_params=light_result['search_params'],
        engine=engine,
        stats_df=light_result['stats_df'],
        key_suffix="light"
    )
    render_sequences_table(
        light_result['sequences_sample_df'],
        light_result['statistics'],
        is_paired=False,
        search_params=light_result['search_params'],
        engine=engine,
        stats_df=light_result['stats_df']
    )
    render_subject_statistics(
        light_result['stats_df'],
        light_result['statistics'],
        widget_key_prefix="light_donor_plot",
    )
    render_results_plots(
        light_result['sequences_sample_df'],
        light_result['statistics'],
        is_paired=False,
        search_params=light_result['search_params'],
        engine=engine,
        show_spider_toggle=False,
    )
    render_dual_search_parameters_expander(
        heavy_result['statistics'],
        light_result['statistics']
    )



