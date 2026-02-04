import streamlit as st
from typing import Dict, Any, Optional

from components.search.search_forms import create_heavy_chain_form, create_light_chain_form
from components.search.database_utils import (
    get_database_structure
)
from components.search.database_selection import render_database_selection
from components.search.search_execution import (
    validate_search_criteria,
    execute_search_with_stats
)
from components.search.results_rendering import (
    render_search_results,
    render_dual_unpaired_results,
    render_dual_search_criteria_display,
    render_search_criteria_display
)
from components.search.styling import render_chain_heading


# Override page title (inherits other settings from app.py)
st.set_page_config(page_title="ABHunter - Database Search")

def create_unpaired_search_form(selected_databases: list) -> Dict[str, Any]:
    """
    Create search form for unpaired data (Heavy or Light).
    Determines which chain type based on selected databases.
    """
    validation_errors = []
    
    # Determine chain type from selected databases
    chain_type = None
    for db_path in selected_databases:
        db_path_str = str(db_path)
        if '/Heavy/' in db_path_str:
            chain_type = 'Heavy'
            break
        elif '/Light/' in db_path_str:
            chain_type = 'Light'
            break
    
    # Default to Heavy if can't determine
    if chain_type is None:
        chain_type = 'Heavy'
    
    if chain_type == 'Heavy':
        render_chain_heading("Heavy Chain", "heavy", level=4, icon="🧬")
        params, errors, valid = create_heavy_chain_form(prefix="", show_title=False)
        validation_errors.extend(errors)
        
        return {
            'heavy_v': params.get('ighv', ''),
            'heavy_d': params.get('ighd', ''),
            'heavy_j': params.get('ighj', ''),
            'heavy_cdr1_length': params.get('cdr1_length'),
            'heavy_cdr2_length': params.get('cdr2_length'),
            'heavy_cdr3_length': params.get('cdr3_length'),
            'heavy_cdr1_motif': params.get('cdr1_motif', ''),
            'heavy_cdr2_motif': params.get('cdr2_motif', ''),
            'heavy_cdr3_motif': params.get('cdr3_motif', ''),
            'heavy_cdr1_similarity': params.get('cdr1_similarity', False),
            'heavy_cdr2_similarity': params.get('cdr2_similarity', False),
            'heavy_cdr3_similarity': params.get('cdr3_similarity', False),
            'heavy_cdr1_mismatches': params.get('cdr1_mismatches', 0),
            'heavy_cdr2_mismatches': params.get('cdr2_mismatches', 0),
            'heavy_cdr3_mismatches': params.get('cdr3_mismatches', 0),
            'chain_type': 'Heavy',
            'valid': valid,
            'validation_errors': validation_errors
        }
    else:  # Light
        render_chain_heading("Light Chain", "light", level=4, icon="🔬")
        params, errors, valid = create_light_chain_form(prefix="light_", show_title=False)
        validation_errors.extend(errors)
        
        return {
            'light_v': params.get('light_v', ''),
            'light_j': params.get('light_j', ''),
            'light_cdr1_length': params.get('light_cdr1_length'),
            'light_cdr2_length': params.get('light_cdr2_length'),
            'light_cdr3_length': params.get('light_cdr3_length'),
            'light_cdr1_motif': params.get('light_cdr1_motif', ''),
            'light_cdr2_motif': params.get('light_cdr2_motif', ''),
            'light_cdr3_motif': params.get('light_cdr3_motif', ''),
            'light_cdr1_similarity': params.get('light_cdr1_similarity', False),
            'light_cdr2_similarity': params.get('light_cdr2_similarity', False),
            'light_cdr3_similarity': params.get('light_cdr3_similarity', False),
            'light_cdr1_mismatches': params.get('light_cdr1_mismatches', 0),
            'light_cdr2_mismatches': params.get('light_cdr2_mismatches', 0),
            'light_cdr3_mismatches': params.get('light_cdr3_mismatches', 0),
            'chain_type': 'Light',
            'valid': valid,
            'validation_errors': validation_errors
        }

def create_dual_unpaired_search_form() -> Dict[str, Any]:
    """
    Create search form for dual unpaired searches (Heavy + Light).
    Returns heavy and light parameter sets with validation info.
    """
    validation_errors: list[str] = []
    
    heavy_params_raw, heavy_errors, heavy_valid = create_heavy_chain_form(
        prefix="dual_heavy_", show_title=True
    )
    light_params_raw, light_errors, light_valid = create_light_chain_form(
        prefix="dual_light_", show_title=True
    )
    
    validation_errors.extend(heavy_errors)
    validation_errors.extend(light_errors)
    
    heavy_search_params = {
        'heavy_v': heavy_params_raw.get('dual_heavy_v', ''),
        'heavy_d': heavy_params_raw.get('dual_heavy_d', ''),
        'heavy_j': heavy_params_raw.get('dual_heavy_j', ''),
        'heavy_cdr1_length': heavy_params_raw.get('dual_heavy_cdr1_length'),
        'heavy_cdr2_length': heavy_params_raw.get('dual_heavy_cdr2_length'),
        'heavy_cdr3_length': heavy_params_raw.get('dual_heavy_cdr3_length'),
        'heavy_cdr1_motif': heavy_params_raw.get('dual_heavy_cdr1_motif', ''),
        'heavy_cdr2_motif': heavy_params_raw.get('dual_heavy_cdr2_motif', ''),
        'heavy_cdr3_motif': heavy_params_raw.get('dual_heavy_cdr3_motif', ''),
        'heavy_cdr1_similarity': heavy_params_raw.get('dual_heavy_cdr1_similarity', False),
        'heavy_cdr2_similarity': heavy_params_raw.get('dual_heavy_cdr2_similarity', False),
        'heavy_cdr3_similarity': heavy_params_raw.get('dual_heavy_cdr3_similarity', False),
        'heavy_cdr1_mismatches': heavy_params_raw.get('dual_heavy_cdr1_mismatches', 0),
        'heavy_cdr2_mismatches': heavy_params_raw.get('dual_heavy_cdr2_mismatches', 0),
        'heavy_cdr3_mismatches': heavy_params_raw.get('dual_heavy_cdr3_mismatches', 0),
        'chain_type': 'Heavy'
    }
    
    light_search_params = {
        'light_v': light_params_raw.get('dual_light_v', ''),
        'light_j': light_params_raw.get('dual_light_j', ''),
        'light_cdr1_length': light_params_raw.get('dual_light_cdr1_length'),
        'light_cdr2_length': light_params_raw.get('dual_light_cdr2_length'),
        'light_cdr3_length': light_params_raw.get('dual_light_cdr3_length'),
        'light_cdr1_motif': light_params_raw.get('dual_light_cdr1_motif', ''),
        'light_cdr2_motif': light_params_raw.get('dual_light_cdr2_motif', ''),
        'light_cdr3_motif': light_params_raw.get('dual_light_cdr3_motif', ''),
        'light_cdr1_similarity': light_params_raw.get('dual_light_cdr1_similarity', False),
        'light_cdr2_similarity': light_params_raw.get('dual_light_cdr2_similarity', False),
        'light_cdr3_similarity': light_params_raw.get('dual_light_cdr3_similarity', False),
        'light_cdr1_mismatches': light_params_raw.get('dual_light_cdr1_mismatches', 0),
        'light_cdr2_mismatches': light_params_raw.get('dual_light_cdr2_mismatches', 0),
        'light_cdr3_mismatches': light_params_raw.get('dual_light_cdr3_mismatches', 0),
        'chain_type': 'Light'
    }
    
    heavy_display_params = {key: value for key, value in heavy_search_params.items() if key != 'chain_type'}
    light_display_params = {key: value for key, value in light_search_params.items() if key != 'chain_type'}
    
    return {
        'heavy': {
            'search_params': heavy_search_params,
            'display_params': heavy_display_params,
            'valid': heavy_valid,
            'validation_errors': heavy_errors
        },
        'light': {
            'search_params': light_search_params,
            'display_params': light_display_params,
            'valid': light_valid,
            'validation_errors': light_errors
        },
        'valid': heavy_valid and light_valid,
        'validation_errors': validation_errors
    }

def create_paired_search_form() -> Dict[str, Any]:
    """Create search form for paired data with separate heavy and light chain fields."""
    validation_errors = []
    
    # Heavy Chain Section
    heavy_params, heavy_errors, heavy_valid = create_heavy_chain_form(prefix="heavy_", show_title=True)
    validation_errors.extend(heavy_errors)
    
    # Light Chain Section
    light_params, light_errors, light_valid = create_light_chain_form(prefix="light_", show_title=True)
    validation_errors.extend(light_errors)
    
    return {
        # Heavy chain parameters
        **heavy_params,
        # Light chain parameters
        **light_params,
        # Validation
        'valid': heavy_valid and light_valid,
        'validation_errors': validation_errors
    }

def search_page_content():
    """Main search page content."""
    st.markdown("# :blue[🔬 AntibodyHunter]")
    st.markdown("#### :grey[High-Performance Antibody Database Search]")
    
    db_structure = get_database_structure()
    total_databases = sum(len(category) for category in db_structure.values())
    if total_databases == 0:
        st.error("No databases found! Please run the data conversion script first.")
        st.stop()
    
    search_status = st.session_state.get('search_status', 'idle')
    is_plotting_locked = st.session_state.get('plotting_controls_locked', False)
    disable_db_selection = (search_status == "running") or is_plotting_locked
    selected_databases, selected_db, is_ready = render_database_selection(
        db_structure,
        disabled=disable_db_selection
    )
    if selected_databases is None:
        selected_databases = []
    
    loadable_databases = st.session_state.get('loadable_databases_active', []) or selected_databases
    overlay_databases = st.session_state.get('overlay_databases_active', [])
    
    # Determine database types in a single pass
    has_paired = False
    has_light = False
    has_heavy = False
    for db_path in loadable_databases:
        db_path_str = str(db_path)
        if '/Paired/' in db_path_str:
            has_paired = True
        elif '/Light/' in db_path_str:
            has_light = True
        elif '/Heavy/' in db_path_str:
            has_heavy = True
    
    def render_cached_results_for_mode(cached_results: Dict[str, Any], current_mode: Optional[str] = None) -> bool:
        engine_obj = st.session_state.get('search_engine')
        if engine_obj is None or not cached_results:
            return False
        
        mode = cached_results.get('mode')
        if mode == 'dual_unpaired':
            if current_mode and current_mode != 'dual_unpaired':
                return False
            heavy_result = cached_results.get('heavy')
            light_result = cached_results.get('light')
            if not heavy_result or not light_result:
                return False
            render_dual_search_criteria_display(
                heavy_result.get('statistics', {}),
                light_result.get('statistics', {})
            )
            render_dual_unpaired_results(
                heavy_result,
                light_result,
                engine_obj,
                show_toast=False
            )
            return True
        
        if current_mode == 'dual_unpaired':
            return False
        
        is_cached_paired = cached_results.get('is_paired', mode == 'paired')
        if current_mode == 'paired' and not is_cached_paired:
            return False
        if current_mode in ('unpaired_heavy', 'unpaired_light') and is_cached_paired:
            return False
        
        sequences_sample_df = cached_results.get('sequences_sample_df')
        statistics = cached_results.get('statistics')
        stats_df = cached_results.get('stats_df')
        search_params = cached_results.get('search_params', {})
        
        # Handle old cached results that might not have stats_df
        # Create empty stats_df if missing (from old API format)
        if stats_df is None:
            import pandas as pd  # Import only when needed
            stats_df = pd.DataFrame()
        
        if sequences_sample_df is None or statistics is None:
            return False
        
        render_search_criteria_display(search_params, is_cached_paired)
        render_search_results(
            sequences_sample_df,
            stats_df,
            statistics,
            is_cached_paired,
            search_params,
            engine_obj,
            show_toast=False
        )
        return True
    
    st.session_state['inferred_overlay_active'] = bool(overlay_databases)
    
    if has_paired:
        search_mode = 'paired'
    elif has_heavy and has_light:
        search_mode = 'dual_unpaired'
    elif has_heavy:
        search_mode = 'unpaired_heavy'
    elif has_light:
        search_mode = 'unpaired_light'
    else:
        search_mode = 'unpaired_heavy'
    
    if not loadable_databases and not overlay_databases:
        if 'last_search_results' in st.session_state:
            cached_results = st.session_state['last_search_results']
            if render_cached_results_for_mode(cached_results):
                st.info("💡 **Tip:** Select databases above to perform a new search. Your previous results are shown below.")
        return
    
    if not is_ready:
        if 'last_search_results' in st.session_state:
            cached_results = st.session_state['last_search_results']
            if render_cached_results_for_mode(cached_results, current_mode=search_mode):
                st.warning("⚠️ Database is loading. Showing cached results below.")
        return
    
    if not selected_db:
        st.warning("⚠️ Please select at least one database to search")
        return
    
    engine = st.session_state['search_engine']
    is_paired = search_mode == 'paired'

    
    st.markdown("## 🔍 Search Criteria")
    st.divider()
    
    if search_mode == 'paired':
        form_data = create_paired_search_form()
        search_params = form_data
        dual_form_data = None
    elif search_mode == 'dual_unpaired':
        form_data = create_dual_unpaired_search_form()
        search_params = None
        dual_form_data = form_data
    else:
        form_data = create_unpaired_search_form(loadable_databases)
        search_params = form_data
        dual_form_data = None
    
    sample_limit = 100
    
    if search_mode == 'dual_unpaired':
        has_validation_errors = not dual_form_data.get('valid', True)
        validation_errors = dual_form_data.get('validation_errors', [])
    else:
        has_validation_errors = not search_params.get('valid', True)
        validation_errors = search_params.get('validation_errors', [])
    
    with st.form("search_form"):
        if validation_errors:
            st.error(f"❌ **Please fix the following errors before searching:** {', '.join(validation_errors)}")
        
        search_submitted = st.form_submit_button(
            "🔍 Search Database",
            type="primary",
            disabled=has_validation_errors,
            width='content'
        )
    
    results_container = st.empty()
    
    if not search_submitted and 'last_search_results' in st.session_state:
        cached_results = st.session_state['last_search_results']
        with results_container.container():
            render_cached_results_for_mode(cached_results, current_mode=search_mode)
    
    if not search_submitted:
        return
    
    if search_mode == 'dual_unpaired':
        heavy_info = dual_form_data['heavy']
        light_info = dual_form_data['light']
        
        if not heavy_info.get('valid', True) or not light_info.get('valid', True):
            st.error("❌ Please fix the invalid inputs (marked in red) before searching")
            return
        
        heavy_valid, heavy_error = validate_search_criteria(heavy_info['search_params'], False)
        light_valid, light_error = validate_search_criteria(light_info['search_params'], False)
        if not heavy_valid or not light_valid:
            if not heavy_valid and heavy_error:
                st.warning(f"Heavy Chain: {heavy_error}")
            if not light_valid and light_error:
                st.warning(f"Light Chain: {light_error}")
            return
        
        with st.spinner("Searching databases..."):
            try:
                heavy_sequences_df, heavy_stats_df, heavy_statistics = execute_search_with_stats(
                    engine, heavy_info['search_params'], False, sample_limit
                )
                light_sequences_df, light_stats_df, light_statistics = execute_search_with_stats(
                    engine, light_info['search_params'], False, sample_limit
                )
            except Exception as e:
                st.error(f"Search failed: {e}")
                st.exception(e)
                return
        
        heavy_result = {
            'sequences_sample_df': heavy_sequences_df,
            'stats_df': heavy_stats_df,
            'statistics': heavy_statistics,
            'search_params': heavy_info['search_params']
        }
        light_result = {
            'sequences_sample_df': light_sequences_df,
            'stats_df': light_stats_df,
            'statistics': light_statistics,
            'search_params': light_info['search_params']
        }
        
        st.session_state['last_search_results'] = {
            'mode': 'dual_unpaired',
            'heavy': heavy_result,
            'light': light_result
        }
        
        with results_container.container():
            render_dual_unpaired_results(heavy_result, light_result, engine, show_toast=True)
        return
    
    if not search_params.get('valid', True):
        st.error("❌ Please fix the invalid inputs (marked in red) before searching")
        return
    
    is_valid, error_message = validate_search_criteria(search_params, is_paired)
    if not is_valid:
        if error_message:
            st.warning(error_message)
        return
    
    with st.spinner("Searching database..."):
        try:
            sequences_sample_df, stats_df, statistics = execute_search_with_stats(
                engine, search_params, is_paired, sample_limit
            )
        except Exception as e:
            st.error(f"Search failed: {e}")
            st.exception(e)
            return
    
    st.session_state['last_search_results'] = {
        'mode': 'paired' if is_paired else search_mode,
        'sequences_sample_df': sequences_sample_df,
        'statistics': statistics,
        'stats_df': stats_df,
        'is_paired': is_paired,
        'search_params': search_params
    }
    
    with results_container.container():
        render_search_results(
            sequences_sample_df,
            stats_df,
            statistics,
            is_paired,
            search_params,
            engine,
            show_toast=True
        )

search_page_content()