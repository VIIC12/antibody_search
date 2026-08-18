"""
Database selection UI component for antibody search.

This module provides the database selection interface with checkboxes
for Heavy, Light, and Paired databases, along with database initialization
and status display.
"""

import streamlit as st
from pathlib import Path
from typing import List, Tuple, Optional
import logging

from components.search.database_utils import (
    init_search_engine,
    check_metadata_freshness,
    get_database_structure
)
from components.search.styling import icon_heading

logger = logging.getLogger(__name__)

DB_SELECTION_LOCK_MESSAGE = (
    ":material/hourglass: Database selection is temporarily locked while a search or plotting task is running."
)


def _is_inferred_path(path: str) -> bool:
    """Return True if the provided database path points to an inferred overlay."""
    try:
        return Path(path).name.lower() == "inferred"
    except Exception:
        return False


def render_database_selection(
    db_structure: dict,
    disabled: bool = False
) -> Tuple[Optional[List[str]], Optional[str], bool]:
    """
    Render database selection UI with checkboxes for Heavy, Light, and Paired databases.
    
    Args:
        db_structure: Dictionary with database structure from get_database_structure()
        disabled: When True, all database selection controls are locked (used during
                  running searches or plotting tasks)
        
    Returns:
        Tuple of (selected_databases, selected_db, is_ready)
        - selected_databases: List of active database paths (loadable datasets + overlays)
        - selected_db: Primary database path (first loadable dataset)
        - is_ready: True if database is loaded and ready, False otherwise
    """
    selection_locked = bool(disabled)
    
    # Database selection interface with checkboxes
    st.markdown("### :material/storage: Database Selection")
    if selection_locked:
        st.info(DB_SELECTION_LOCK_MESSAGE)
    
    # Cache structure for downstream consumers (e.g., inferred fallback loading)
    st.session_state['database_structure_cache'] = db_structure

    # Initialize session state for selected databases if not exists
    # Note: We preserve selected_databases from session state when navigating between pages
    if 'selected_databases' not in st.session_state:
        st.session_state['selected_databases'] = []
    
    # Create columns for each category
    col1, col2, col3 = st.columns(3)
    
    # Start with empty list - will be rebuilt from checkbox states
    # Checkboxes preserve their state automatically via Streamlit's key parameter
    selected_databases = []
    
    heavy_total_sequences = sum(info['sequence_count'] for info in db_structure['Heavy'].values())
    light_total_sequences = sum(info['sequence_count'] for info in db_structure['Light'].values())
    paired_real_sequences = sum(
        info['sequence_count']
        for info in db_structure['Paired'].values()
        if not info.get('is_inferred', False)
    )
    # Check if inferred overlay exists (now in data/Inferred/ directly)
    has_inferred_overlay = (
        'Inferred' in db_structure and 
        len(db_structure['Inferred']) > 0 and
        any(info.get('is_inferred', False) for info in db_structure['Inferred'].values())
    )
    
    # Check current selection state to determine what should be disabled
    # We need to check session state before rendering to know what to disable
    paired_currently_selected = st.session_state.get('paired_main', False)
    heavy_currently_selected = st.session_state.get('heavy_main', False)
    light_currently_selected = st.session_state.get('light_main', False)
    prev_heavy_selected = st.session_state.get('heavy_main_prev', False)
    prev_light_selected = st.session_state.get('light_main_prev', False)

    # Exactly one mode: Paired XOR Heavy XOR Light
    heavy_conflict_disabled = paired_currently_selected or light_currently_selected
    light_conflict_disabled = paired_currently_selected or heavy_currently_selected
    paired_conflict_disabled = heavy_currently_selected or light_currently_selected
    
    heavy_disabled = heavy_conflict_disabled or selection_locked
    light_disabled = light_conflict_disabled or selection_locked
    paired_disabled = paired_conflict_disabled or selection_locked
    
    # Auto-uncheck incompatible selections
    if not selection_locked:
        if paired_currently_selected:
            if heavy_currently_selected:
                st.session_state['heavy_main'] = False
                for subdir in db_structure['Heavy'].keys():
                    st.session_state[f"heavy_{subdir}"] = False
                heavy_currently_selected = False
            if light_currently_selected:
                st.session_state['light_main'] = False
                for subdir in db_structure['Light'].keys():
                    st.session_state[f"light_{subdir}"] = False
                light_currently_selected = False
        
        # If Heavy or Light is selected, uncheck Paired
        if (heavy_currently_selected or light_currently_selected) and paired_currently_selected:
            st.session_state['paired_main'] = False
            st.session_state['paired_real_bundle'] = False
            paired_currently_selected = False

        # Heavy and Light are mutually exclusive: keep the most recently enabled one
        if heavy_currently_selected and light_currently_selected:
            heavy_just_enabled = heavy_currently_selected and not prev_heavy_selected
            light_just_enabled = light_currently_selected and not prev_light_selected
            if light_just_enabled and not heavy_just_enabled:
                st.session_state['heavy_main'] = False
                for subdir in db_structure['Heavy'].keys():
                    st.session_state[f"heavy_{subdir}"] = False
                heavy_currently_selected = False
            else:
                # Prefer Heavy when both were already on or Heavy was just enabled
                st.session_state['light_main'] = False
                for subdir in db_structure['Light'].keys():
                    st.session_state[f"light_{subdir}"] = False
                light_currently_selected = False

        # Recompute disabled flags after auto-uncheck
        heavy_conflict_disabled = paired_currently_selected or light_currently_selected
        light_conflict_disabled = paired_currently_selected or heavy_currently_selected
        paired_conflict_disabled = heavy_currently_selected or light_currently_selected
        heavy_disabled = heavy_conflict_disabled or selection_locked
        light_disabled = light_conflict_disabled or selection_locked
        paired_disabled = paired_conflict_disabled or selection_locked
    
    # Heavy Chain selection
    with col1:
        prev_heavy_selected = st.session_state.get('heavy_main_prev', False)
        icon_heading("heavy", "Heavy Chain", level=3)
        # Build label with inferred indicator if available
        heavy_label = f"Heavy Chain ({heavy_total_sequences:,} sequences)"
        if has_inferred_overlay:
            heavy_label += " + Inferred V/J Light Chain"
        # Checkbox state is automatically preserved via session state (key parameter)
        if selection_locked:
            heavy_help = DB_SELECTION_LOCK_MESSAGE
        elif heavy_conflict_disabled:
            heavy_help = (
                "Disabled when Paired or Light is selected. "
                "Choose Heavy, Light, or Paired."
            )
        else:
            heavy_help = "Inferred data is automatically included when searching Heavy or Light chains." if has_inferred_overlay else None
        
        heavy_selected = st.checkbox(
            heavy_label,
            key="heavy_main",
            disabled=heavy_disabled,
            help=heavy_help
        )
        # If main checkbox is checked, ensure subdirectories are included
        if heavy_selected:
            if len(db_structure['Heavy']) == 1:
                # Auto-select the single subdirectory
                subdir, info = next(iter(db_structure['Heavy'].items()))
                selected_databases.append(info['path'])
            else:
                # For multiple subdirectories, auto-select all by default
                # Always set all subdirectories to True only when toggled on
                if not prev_heavy_selected:
                    for subdir in db_structure['Heavy'].keys():
                        checkbox_key = f"heavy_{subdir}"
                        st.session_state[checkbox_key] = True
                
                # Show checkboxes for multiple subdirectories in a 3x2 grid
                subdirs = list(db_structure['Heavy'].items())
                cols_per_row = 3
                for row_start in range(0, len(subdirs), cols_per_row):
                    row_items = subdirs[row_start : row_start + cols_per_row]
                    sub_cols = st.columns(cols_per_row)
                    for (subdir, info), col in zip(row_items, sub_cols):
                        with col:
                            checkbox_key = f"heavy_{subdir}"
                            checkbox_help = DB_SELECTION_LOCK_MESSAGE if selection_locked else f"Files: {info['parquet_count']} | Sequences: {info['sequence_count']:,}"
                            checkbox_value = st.checkbox(
                                f"{subdir}",
                                key=checkbox_key,
                                disabled=heavy_disabled,
                                help=checkbox_help
                            )
                            if checkbox_value:
                                selected_databases.append(info['path'])
        else:
            # Uncheck all heavy subdirectories if main category is unchecked
            for subdir in db_structure['Heavy'].keys():
                st.session_state[f"heavy_{subdir}"] = False
        
        st.session_state['heavy_main_prev'] = heavy_selected
    
    # Light Chain selection
    with col2:
        prev_light_selected = st.session_state.get('light_main_prev', False)
        light_total_sequences = sum(info['sequence_count'] for info in db_structure['Light'].values())
        icon_heading("light", "Light Chain", level=3)
        # Build label with inferred indicator if available
        light_label = f"Light Chain ({light_total_sequences:,} sequences)"
        if has_inferred_overlay:
            light_label += " + Inferred V/J Heavy Chain"
        if selection_locked:
            light_help = DB_SELECTION_LOCK_MESSAGE
        elif light_conflict_disabled:
            light_help = (
                "Disabled when Paired or Heavy is selected. "
                "Choose Heavy, Light, or Paired."
            )
        else:
            light_help = "Inferred data is automatically included when searching Heavy or Light chains." if has_inferred_overlay else None
        
        light_selected = st.checkbox(
            light_label,
            key="light_main",
            disabled=light_disabled,
            help=light_help
        )
        if light_selected:
            if len(db_structure['Light']) == 1:
                # Auto-select the single subdirectory
                subdir, info = next(iter(db_structure['Light'].items()))
                selected_databases.append(info['path'])
            else:
                # For multiple subdirectories, auto-select all by default
                # Always set all subdirectories to True when main is selected
                if not prev_light_selected:
                    for subdir in db_structure['Light'].keys():
                        checkbox_key = f"light_{subdir}"
                        st.session_state[checkbox_key] = True
                
                # Show checkboxes for multiple subdirectories
                sub_col1, sub_col2 = st.columns(2)
                subdirs = list(db_structure['Light'].items())
                for i, (subdir, info) in enumerate(subdirs):
                    col = sub_col1 if i % 2 == 0 else sub_col2
                    with col:
                        checkbox_key = f"light_{subdir}"
                        # Streamlit will use session state value automatically if key exists
                        checkbox_help = DB_SELECTION_LOCK_MESSAGE if selection_locked else f"Files: {info['parquet_count']} | Sequences: {info['sequence_count']:,}"
                        checkbox_value = st.checkbox(
                            f"{subdir}",
                            key=checkbox_key,
                            disabled=light_disabled,
                            help=checkbox_help
                        )
                        # Add to selected if checkbox is checked
                        if checkbox_value:
                            selected_databases.append(info['path'])
        else:
            # Uncheck all light subdirectories if main category is unchecked
            for subdir in db_structure['Light'].keys():
                st.session_state[f"light_{subdir}"] = False

        st.session_state['light_main_prev'] = light_selected
    
    prev_paired_selected = st.session_state.get('paired_main_prev', False)
    
    # Paired selection
    with col3:
        icon_heading("paired", "Paired", level=3)
        if selection_locked:
            paired_help = DB_SELECTION_LOCK_MESSAGE
        elif paired_conflict_disabled:
            paired_help = "Disabled when Heavy or Light is selected"
        else:
            paired_help = None
        
        paired_selected = st.checkbox(
            f"Paired ({paired_real_sequences:,} sequences)",
            key="paired_main",
            disabled=paired_disabled,
            help=paired_help
        )
        if paired_selected:
            paired_real_entries = [
                (subdir, info) for subdir, info in db_structure['Paired'].items()
                if not info.get('is_inferred', False)
            ]
            
            # Auto-select if only one subdirectory (like Light Chain)
            if len(paired_real_entries) == 1:
                subdir, info = paired_real_entries[0]
                selected_databases.append(info['path'])
            elif paired_real_entries:
                if not prev_paired_selected:
                        st.session_state['paired_real_bundle'] = True
            
                real_sequence_total = sum(info['sequence_count'] for _, info in paired_real_entries)
                real_label = "Paired"
                real_help_parts = []
                if len(paired_real_entries) > 1:
                    real_help_parts.append(
                        "Includes subdirectories: " + ", ".join(name for name, _ in paired_real_entries)
                    )
                real_help_parts.append(f"Sequences: {real_sequence_total:,}")
                real_help_text = " | ".join(real_help_parts)
                checkbox_help = DB_SELECTION_LOCK_MESSAGE if selection_locked else real_help_text
                
                real_selected = st.checkbox(
                    real_label,
                    key="paired_real_bundle",
                    disabled=paired_disabled,
                    help=checkbox_help
                )
                if real_selected:
                    for _, info in paired_real_entries:
                        selected_databases.append(info['path'])
        else:
            st.session_state['paired_real_bundle'] = False
    
    st.session_state['paired_main_prev'] = paired_selected

    st.session_state['selected_databases_raw'] = list(selected_databases)
    previous_selected_databases = st.session_state.get('selected_databases', [])
    
    # Check if at least one database is selected
    if not selected_databases:
        st.warning("Please select at least one database to search", icon=":material/warning:")
        return None, None, False
    
    loadable_databases = [db for db in selected_databases if not _is_inferred_path(db)]
    selected_db = loadable_databases[0] if loadable_databases else (selected_databases[0] if selected_databases else None)
    
    # Initialize database if needed
    is_ready = initialize_database(selected_databases)
    
    if not is_ready:
        return selected_databases, selected_db, False
    
    loadable_active = st.session_state.get('loadable_databases_active', [])
    overlay_active = st.session_state.get('overlay_databases_active', [])
    effective_selected = st.session_state.get('effective_selected_databases', selected_databases)
    current_primary_db = st.session_state.get('current_db', selected_db)
    
    # Display database status metrics
    display_database_status(loadable_active, overlay_active, current_primary_db)
    
    return effective_selected, current_primary_db, True


def initialize_database(
    selected_databases: List[str]
) -> bool:
    """
    Initialize search engine for selected databases.
    
    Args:
        selected_databases: List of user-selected database paths (may include overlays)
        
    Returns:
        True if database is ready, False otherwise
    """
    struct_cache = st.session_state.get('database_structure_cache', {})
    current_db = st.session_state.get('current_db')

    loadable_databases = [db for db in selected_databases if not _is_inferred_path(db)]
    overlay_databases = [db for db in selected_databases if _is_inferred_path(db)]

    # If only inferred overlay is selected, fall back to heavy and light datasets
    if not loadable_databases and overlay_databases:
        fallback_dirs = []
        for category in ('Heavy', 'Light'):
            for info in struct_cache.get(category, {}).values():
                fallback_dirs.append(info['path'])
        loadable_databases = fallback_dirs

    # Automatically include inferred directory for unpaired searches if it exists
    # Check if we have unpaired databases (Heavy or Light) and no paired databases
    has_unpaired = any(
        'Heavy' in db or 'Light' in db
        for db in loadable_databases
    )
    has_paired = any(
        'Paired' in db and 'Inferred' not in db
        for db in loadable_databases
    )
    
    if has_unpaired and not has_paired:
        # Look for inferred directory directly in data/Inferred/
        inferred_path = None
        if 'Inferred' in struct_cache:
            for subdir_name, info in struct_cache['Inferred'].items():
                if info.get('is_inferred', False):
                    inferred_path = info.get('path')
                break
        
        # Add inferred directory to overlays if it exists and isn't already included
        if inferred_path and inferred_path not in overlay_databases:
            overlay_databases.append(inferred_path)

    loadable_databases = list(dict.fromkeys(loadable_databases))
    overlay_databases = list(dict.fromkeys(overlay_databases))

    if not loadable_databases:
        st.error("No searchable datasets selected.")
        return False

    primary_db = loadable_databases[0]

    previous_loadable = st.session_state.get('loadable_databases_active', [])
    previous_overlays = st.session_state.get('overlay_databases_active', [])
    databases_changed = set(previous_loadable) != set(loadable_databases)
    overlay_changed = set(previous_overlays) != set(overlay_databases)
    primary_db_changed = current_db != primary_db

    need_reinit = databases_changed or primary_db_changed or current_db is None

    if need_reinit:
        # Validate datasets before loading
        for db_path in loadable_databases:
            parquet_files = list(Path(db_path).glob('*.parquet'))
            metadata_fresh = True #check_metadata_freshness(db_path)
            if not parquet_files or not metadata_fresh:
                st.error(f"Database files not found or metadata is outdated for {db_path}.")
                return False

        with st.spinner("Loading database..."):
            engine = init_search_engine(loadable_databases)
            st.session_state['search_engine'] = engine
            st.session_state['current_db'] = primary_db
            st.session_state['loadable_databases_active'] = loadable_databases
            st.session_state['overlay_databases_active'] = overlay_databases
            effective_selection = list(dict.fromkeys(loadable_databases + overlay_databases))
            st.session_state['effective_selected_databases'] = effective_selection
            st.session_state['selected_databases'] = effective_selection
            st.session_state['inferred_overlay_dirs'] = overlay_databases
            st.session_state['inferred_overlay_active'] = bool(overlay_databases)
            if hasattr(engine, "load_inferred_pairs"):
                engine.load_inferred_pairs(overlay_databases)
            if databases_changed or primary_db_changed:
                for key in ('last_search_results', 'last_search_params'):
                    if key in st.session_state:
                        del st.session_state[key]
        st.rerun()
        return False

    # If engine already exists, ensure overlay cache is up to date
    engine = st.session_state.get('search_engine')
    if engine is None:
        st.warning("Please wait for the database to load...")
        return False

    if overlay_changed and hasattr(engine, "load_inferred_pairs"):
        engine.load_inferred_pairs(overlay_databases)

    st.session_state['current_db'] = primary_db
    st.session_state['loadable_databases_active'] = loadable_databases
    st.session_state['overlay_databases_active'] = overlay_databases
    st.session_state['effective_selected_databases'] = list(dict.fromkeys(loadable_databases + overlay_databases))
    st.session_state['selected_databases'] = st.session_state['effective_selected_databases']
    st.session_state['inferred_overlay_dirs'] = overlay_databases
    st.session_state['inferred_overlay_active'] = bool(overlay_databases)

    return True


def display_database_status(
    loadable_databases: List[str],
    overlay_databases: List[str],
    selected_db: Optional[str]
) -> None:
    """
    Display database status metrics (total sequences).
    
    Args:
        loadable_databases: List of core database paths loaded into DuckDB
        overlay_databases: List of inferred overlay directories
        selected_db: Primary database path
    """
    # Calculate total sequences from all selected databases
    total_selected_sequences = 0
    for db_path in loadable_databases:
        try:
            # Get sequence count from metadata file
            metadata_file = Path(db_path) / "metadata.parquet"
            if metadata_file.exists():
                import pandas as pd
                metadata_df = pd.read_parquet(metadata_file)
                if 'total_sequences' in metadata_df.columns:
                    total_selected_sequences += metadata_df['total_sequences'].sum()
        except Exception as e:
            logger.warning(f"Could not read sequence count from {db_path}: {e}")
    
    # Create tooltip with selected databases info
    selected_db_info = []
    for db_path in loadable_databases:
        db_name = Path(db_path).name
        parent_name = Path(db_path).parent.name
        selected_db_info.append(f"• {parent_name}/{db_name}")
    if overlay_databases:
        selected_db_info.append("• Paired/Inferred (overlay)")
    
    st.metric("Total Selected Sequences", f"{total_selected_sequences:,}")
    
    # Additional sidebar content for database management
    with st.sidebar:
        # Show status messages
        if selected_db:
            parquet_files = list(Path(selected_db).glob('*.parquet'))
            if not parquet_files:
                st.error("No Parquet files found in this database.")
            elif not check_metadata_freshness(selected_db):
                st.warning("🔄 Database files have been updated!")

