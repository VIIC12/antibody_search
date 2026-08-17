import streamlit as st
import concurrent.futures
import time
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from streamlit_autorefresh import st_autorefresh

import components.search.results_rendering as _results_rendering
from components.search.search_forms import (
    create_heavy_chain_form,
    create_light_chain_form,
)
from components.search.database_utils import get_database_structure
from components.search.database_selection import render_database_selection
from components.search.search_execution import validate_search_criteria
from components.test_utils import (
    perform_database_search_background,
    perform_dual_unpaired_search_background,
)

logger = logging.getLogger(__name__)

render_search_results = _results_rendering.render_search_results
render_dual_unpaired_results = _results_rendering.render_dual_unpaired_results
render_dual_search_criteria_display = (
    _results_rendering.render_dual_search_criteria_display
)
render_search_criteria_display = (
    _results_rendering.render_search_criteria_display
)

# Inject CSS for spinner animation and hide disabled form buttons
st.markdown(
    """
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

/* Hide all disabled form submit buttons globally */
div[data-testid="stForm"] button[kind="formSubmit"]:disabled,
button[kind="formSubmit"]:disabled {
    display: none !important;
    visibility: hidden !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# Initialize session state for background search tasks
if "search_future" not in st.session_state:
    st.session_state.search_future = None
if "search_result" not in st.session_state:
    st.session_state.search_result = None
if "search_start_time" not in st.session_state:
    st.session_state.search_start_time = None
if "search_status" not in st.session_state:
    st.session_state.search_status = "idle"  # idle, running, completed, failed


# Get or create executor
@st.cache_resource
def get_search_executor():
    return concurrent.futures.ProcessPoolExecutor(max_workers=2)


executor = get_search_executor()


# Status checking function (non-blocking)
def check_search_status():
    """Check search task status without blocking - updates session state"""
    if st.session_state.search_future is not None:
        if st.session_state.search_future.done():
            try:
                result = st.session_state.search_future.result()
                st.session_state.search_result = result
                st.session_state.search_future = None
                st.session_state.search_start_time = None

                # Debug: Log result status
                if result and not result.get("success"):
                    error_msg = result.get("error", "Unknown error")
                    error_type = result.get("error_type", "Unknown")
                    import sys

                    print(
                        f"[DEBUG] Search failed: {error_type}: {error_msg}",
                        file=sys.stderr,
                    )

                if result.get("success"):
                    st.session_state.search_status = "completed"
                else:
                    st.session_state.search_status = "failed"
                return True, result
            except Exception as e:
                import sys
                import traceback

                error_str = str(e)
                traceback_str = traceback.format_exc()
                print(
                    f"[DEBUG] Exception in check_search_status: {error_str}",
                    file=sys.stderr,
                )
                print(f"[DEBUG] Traceback:\n{traceback_str}", file=sys.stderr)

                st.session_state.search_future = None
                st.session_state.search_start_time = None
                st.session_state.search_status = "failed"
                st.session_state.search_result = {
                    "success": False,
                    "error": error_str,
                    "error_type": type(e).__name__,
                    "traceback": traceback_str,
                }
                return False, str(e)
    return None, None


# Check status on every run (non-blocking check)
check_search_status()

# Auto-refresh when search task is running (every 2 seconds)
if st.session_state.search_status == "running":
    st_autorefresh(interval=2000, key="search_task_refresh")


def create_unpaired_search_form(
    selected_databases: list, disabled: bool = False
) -> Dict[str, Any]:
    """
    Create search form for unpaired data (Heavy or Light).
    Determines which chain type based on selected databases.
    """
    validation_errors = []

    # Determine chain type from selected databases
    chain_type = None
    for db_path in selected_databases:
        db_path_str = str(db_path)
        if "/Heavy/" in db_path_str:
            chain_type = "Heavy"
            break
        elif "/Light/" in db_path_str:
            chain_type = "Light"
            break

    # Default to Heavy if can't determine
    if chain_type is None:
        chain_type = "Heavy"

    if chain_type == "Heavy":
        params, errors, valid = create_heavy_chain_form(
            prefix="", disabled=disabled
        )
        validation_errors.extend(errors)

        return {
            "heavy_v": params.get("ighv", ""),
            "heavy_d": params.get("ighd", ""),
            "heavy_j": params.get("ighj", ""),
            "heavy_cdr1_length": params.get("cdr1_length"),
            "heavy_cdr2_length": params.get("cdr2_length"),
            "heavy_cdr3_length": params.get("cdr3_length"),
            "heavy_cdr1_motif": params.get("cdr1_motif", ""),
            "heavy_cdr2_motif": params.get("cdr2_motif", ""),
            "heavy_cdr3_motif": params.get("cdr3_motif", ""),
            "heavy_cdr1_similarity": params.get("cdr1_similarity", False),
            "heavy_cdr2_similarity": params.get("cdr2_similarity", False),
            "heavy_cdr3_similarity": params.get("cdr3_similarity", False),
            "heavy_cdr1_mismatches": params.get("cdr1_mismatches", 0),
            "heavy_cdr2_mismatches": params.get("cdr2_mismatches", 0),
            "heavy_cdr3_mismatches": params.get("cdr3_mismatches", 0),
            "chain_type": "Heavy",
            "valid": valid,
            "validation_errors": validation_errors,
        }
    else:  # Light
        params, errors, valid = create_light_chain_form(
            prefix="light_", disabled=disabled
        )
        validation_errors.extend(errors)

        return {
            "light_v": params.get("light_v", ""),
            "light_j": params.get("light_j", ""),
            "light_cdr1_length": params.get("light_cdr1_length"),
            "light_cdr2_length": params.get("light_cdr2_length"),
            "light_cdr3_length": params.get("light_cdr3_length"),
            "light_cdr1_motif": params.get("light_cdr1_motif", ""),
            "light_cdr2_motif": params.get("light_cdr2_motif", ""),
            "light_cdr3_motif": params.get("light_cdr3_motif", ""),
            "light_cdr1_similarity": params.get("light_cdr1_similarity", False),
            "light_cdr2_similarity": params.get("light_cdr2_similarity", False),
            "light_cdr3_similarity": params.get("light_cdr3_similarity", False),
            "light_cdr1_mismatches": params.get("light_cdr1_mismatches", 0),
            "light_cdr2_mismatches": params.get("light_cdr2_mismatches", 0),
            "light_cdr3_mismatches": params.get("light_cdr3_mismatches", 0),
            "chain_type": "Light",
            "valid": valid,
            "validation_errors": validation_errors,
        }


def create_dual_unpaired_search_form(disabled: bool = False) -> Dict[str, Any]:
    """
    Create search form for dual unpaired searches (Heavy + Light).
    Returns heavy and light parameter sets with validation info.
    """
    validation_errors: list[str] = []

    heavy_params_raw, heavy_errors, heavy_valid = create_heavy_chain_form(
        prefix="dual_heavy_", disabled=disabled
    )
    light_params_raw, light_errors, light_valid = create_light_chain_form(
        prefix="dual_light_", disabled=disabled
    )

    validation_errors.extend(heavy_errors)
    validation_errors.extend(light_errors)

    heavy_search_params = {
        "heavy_v": heavy_params_raw.get("dual_heavy_v", ""),
        "heavy_d": heavy_params_raw.get("dual_heavy_d", ""),
        "heavy_j": heavy_params_raw.get("dual_heavy_j", ""),
        "heavy_cdr1_length": heavy_params_raw.get("dual_heavy_cdr1_length"),
        "heavy_cdr2_length": heavy_params_raw.get("dual_heavy_cdr2_length"),
        "heavy_cdr3_length": heavy_params_raw.get("dual_heavy_cdr3_length"),
        "heavy_cdr1_motif": heavy_params_raw.get("dual_heavy_cdr1_motif", ""),
        "heavy_cdr2_motif": heavy_params_raw.get("dual_heavy_cdr2_motif", ""),
        "heavy_cdr3_motif": heavy_params_raw.get("dual_heavy_cdr3_motif", ""),
        "heavy_cdr1_similarity": heavy_params_raw.get(
            "dual_heavy_cdr1_similarity", False
        ),
        "heavy_cdr2_similarity": heavy_params_raw.get(
            "dual_heavy_cdr2_similarity", False
        ),
        "heavy_cdr3_similarity": heavy_params_raw.get(
            "dual_heavy_cdr3_similarity", False
        ),
        "heavy_cdr1_mismatches": heavy_params_raw.get(
            "dual_heavy_cdr1_mismatches", 0
        ),
        "heavy_cdr2_mismatches": heavy_params_raw.get(
            "dual_heavy_cdr2_mismatches", 0
        ),
        "heavy_cdr3_mismatches": heavy_params_raw.get(
            "dual_heavy_cdr3_mismatches", 0
        ),
        "chain_type": "Heavy",
    }

    light_search_params = {
        "light_v": light_params_raw.get("dual_light_v", ""),
        "light_j": light_params_raw.get("dual_light_j", ""),
        "light_cdr1_length": light_params_raw.get("dual_light_cdr1_length"),
        "light_cdr2_length": light_params_raw.get("dual_light_cdr2_length"),
        "light_cdr3_length": light_params_raw.get("dual_light_cdr3_length"),
        "light_cdr1_motif": light_params_raw.get("dual_light_cdr1_motif", ""),
        "light_cdr2_motif": light_params_raw.get("dual_light_cdr2_motif", ""),
        "light_cdr3_motif": light_params_raw.get("dual_light_cdr3_motif", ""),
        "light_cdr1_similarity": light_params_raw.get(
            "dual_light_cdr1_similarity", False
        ),
        "light_cdr2_similarity": light_params_raw.get(
            "dual_light_cdr2_similarity", False
        ),
        "light_cdr3_similarity": light_params_raw.get(
            "dual_light_cdr3_similarity", False
        ),
        "light_cdr1_mismatches": light_params_raw.get(
            "dual_light_cdr1_mismatches", 0
        ),
        "light_cdr2_mismatches": light_params_raw.get(
            "dual_light_cdr2_mismatches", 0
        ),
        "light_cdr3_mismatches": light_params_raw.get(
            "dual_light_cdr3_mismatches", 0
        ),
        "chain_type": "Light",
    }

    heavy_display_params = {
        key: value
        for key, value in heavy_search_params.items()
        if key != "chain_type"
    }
    light_display_params = {
        key: value
        for key, value in light_search_params.items()
        if key != "chain_type"
    }

    return {
        "heavy": {
            "search_params": heavy_search_params,
            "display_params": heavy_display_params,
            "valid": heavy_valid,
            "validation_errors": heavy_errors,
        },
        "light": {
            "search_params": light_search_params,
            "display_params": light_display_params,
            "valid": light_valid,
            "validation_errors": light_errors,
        },
        "valid": heavy_valid and light_valid,
        "validation_errors": validation_errors,
    }


def create_paired_search_form(disabled: bool = False) -> Dict[str, Any]:
    """Create search form for paired data with separate heavy and light chain fields."""
    validation_errors = []

    # Heavy Chain Section
    heavy_params, heavy_errors, heavy_valid = create_heavy_chain_form(
        prefix="heavy_", disabled=disabled
    )
    validation_errors.extend(heavy_errors)

    # Light Chain Section
    light_params, light_errors, light_valid = create_light_chain_form(
        prefix="light_", disabled=disabled
    )
    validation_errors.extend(light_errors)

    return {
        # Heavy chain parameters
        **heavy_params,
        # Light chain parameters
        **light_params,
        # Validation
        "valid": heavy_valid and light_valid,
        "validation_errors": validation_errors,
    }


def search_page_content():
    """Main search page content."""
    st.title(":material/vaccines: ABHunter")
    st.markdown(
        "#### :grey[Explore and filter the antibody repertoire of healthy-humans from the OAS database in real-time]"
    )

    # Print database path once when server starts (only on first call)
    if "db_path_printed" not in st.session_state:
        abhunter_db_path = os.getenv("ABHUNTER_DB_PATH")
        if abhunter_db_path:
            db_path = Path(abhunter_db_path).absolute()
            print(f"Database path: {db_path}")
        else:
            project_root = Path(__file__).parent.parent.parent
            db_path = (project_root / "data").absolute()
            print(f"Database path: {db_path} (default)")
        st.session_state["db_path_printed"] = True

    db_structure = get_database_structure()
    total_databases = sum(len(category) for category in db_structure.values())
    if total_databases == 0:
        # Determine which path was checked
        abhunter_db_path = os.getenv("ABHUNTER_DB_PATH")
        if abhunter_db_path:
            checked_path = Path(abhunter_db_path).absolute()
        else:
            # Match the logic in get_database_structure()
            project_root = Path(__file__).parent.parent.parent
            checked_path = (project_root / "data").absolute()

        st.error(
            f"**Database directory not found!**\n\n"
            f"Checked path: `{checked_path}`\n\n"
            f"To set a custom database path, use the `ABHUNTER_DB_PATH` environment variable:\n"
            f"```bash\n"
            f'export ABHUNTER_DB_PATH="/path/to/your/database"\n'
            f"```\n\n"
            f"For more information, please refer to the documentation."
        )
        st.stop()

    # Apply IgBLAST prefill once: set form keys and database selection, then clear prefill
    prefill = st.session_state.pop("search_prefill_from_igblast", None)
    if prefill is not None:
        mode = prefill.get("mode", "")
        heavy = prefill.get("heavy") or {}
        light = prefill.get("light") or {}
        db_struct = db_structure
        if mode == "unpaired_heavy" and heavy:
            st.session_state["ighv_input"] = heavy.get("v", "")
            st.session_state["ighd_input"] = heavy.get("d", "")
            st.session_state["ighj_input"] = heavy.get("j", "")
            st.session_state["cdr1_length_input"] = (
                heavy.get("cdr1_length") or ""
            )
            st.session_state["cdr2_length_input"] = (
                heavy.get("cdr2_length") or ""
            )
            st.session_state["cdr3_length_input"] = (
                heavy.get("cdr3_length") or ""
            )
            st.session_state["cdr1_motif_input"] = heavy.get("cdr1_motif") or ""
            st.session_state["cdr2_motif_input"] = heavy.get("cdr2_motif") or ""
            st.session_state["cdr3_motif_input"] = heavy.get("cdr3_motif") or ""
            st.session_state["heavy_main"] = True
            st.session_state["light_main"] = False
            st.session_state["paired_main"] = False
            for subdir in db_struct.get("Heavy", {}).keys():
                st.session_state[f"heavy_{subdir}"] = True
            for subdir in db_struct.get("Light", {}).keys():
                st.session_state[f"light_{subdir}"] = False
            st.session_state["paired_real_bundle"] = False
            st.session_state["search_prefill_message"] = (
                "Search criteria pre-filled from IgBLAST (unpaired heavy). Select databases and run your search."
            )
        elif mode == "unpaired_light" and light:
            st.session_state["light_v_input"] = light.get("v", "")
            st.session_state["light_j_input"] = light.get("j", "")
            st.session_state["light_cdr1_length_input"] = (
                light.get("cdr1_length") or ""
            )
            st.session_state["light_cdr2_length_input"] = (
                light.get("cdr2_length") or ""
            )
            st.session_state["light_cdr3_length_input"] = (
                light.get("cdr3_length") or ""
            )
            st.session_state["light_cdr1_motif_input"] = (
                light.get("cdr1_motif") or ""
            )
            st.session_state["light_cdr2_motif_input"] = (
                light.get("cdr2_motif") or ""
            )
            st.session_state["light_cdr3_motif_input"] = (
                light.get("cdr3_motif") or ""
            )
            st.session_state["heavy_main"] = False
            st.session_state["light_main"] = True
            st.session_state["paired_main"] = False
            for subdir in db_struct.get("Heavy", {}).keys():
                st.session_state[f"heavy_{subdir}"] = False
            for subdir in db_struct.get("Light", {}).keys():
                st.session_state[f"light_{subdir}"] = True
            st.session_state["paired_real_bundle"] = False
            st.session_state["search_prefill_message"] = (
                "Search criteria pre-filled from IgBLAST (unpaired light). Select databases and run your search."
            )
        elif mode == "paired" and (heavy or light):
            st.session_state["heavy_v_input"] = heavy.get("v", "")
            st.session_state["heavy_d_input"] = heavy.get("d", "")
            st.session_state["heavy_j_input"] = heavy.get("j", "")
            st.session_state["heavy_cdr1_length_input"] = (
                heavy.get("cdr1_length") or ""
            )
            st.session_state["heavy_cdr2_length_input"] = (
                heavy.get("cdr2_length") or ""
            )
            st.session_state["heavy_cdr3_length_input"] = (
                heavy.get("cdr3_length") or ""
            )
            st.session_state["heavy_cdr1_motif_input"] = (
                heavy.get("cdr1_motif") or ""
            )
            st.session_state["heavy_cdr2_motif_input"] = (
                heavy.get("cdr2_motif") or ""
            )
            st.session_state["heavy_cdr3_motif_input"] = (
                heavy.get("cdr3_motif") or ""
            )
            st.session_state["light_v_input"] = light.get("v", "")
            st.session_state["light_j_input"] = light.get("j", "")
            st.session_state["light_cdr1_length_input"] = (
                light.get("cdr1_length") or ""
            )
            st.session_state["light_cdr2_length_input"] = (
                light.get("cdr2_length") or ""
            )
            st.session_state["light_cdr3_length_input"] = (
                light.get("cdr3_length") or ""
            )
            st.session_state["light_cdr1_motif_input"] = (
                light.get("cdr1_motif") or ""
            )
            st.session_state["light_cdr2_motif_input"] = (
                light.get("cdr2_motif") or ""
            )
            st.session_state["light_cdr3_motif_input"] = (
                light.get("cdr3_motif") or ""
            )
            st.session_state["heavy_main"] = False
            st.session_state["light_main"] = False
            st.session_state["paired_main"] = True
            for subdir in db_struct.get("Heavy", {}).keys():
                st.session_state[f"heavy_{subdir}"] = False
            for subdir in db_struct.get("Light", {}).keys():
                st.session_state[f"light_{subdir}"] = False
            st.session_state["paired_real_bundle"] = True
            st.session_state["search_prefill_message"] = (
                "Search criteria pre-filled from IgBLAST (paired). Select databases and run your search."
            )
        elif mode == "dual_unpaired" and (heavy or light):
            st.session_state["dual_heavy_v_input"] = heavy.get("v", "")
            st.session_state["dual_heavy_d_input"] = heavy.get("d", "")
            st.session_state["dual_heavy_j_input"] = heavy.get("j", "")
            st.session_state["dual_heavy_cdr1_length_input"] = (
                heavy.get("cdr1_length") or ""
            )
            st.session_state["dual_heavy_cdr2_length_input"] = (
                heavy.get("cdr2_length") or ""
            )
            st.session_state["dual_heavy_cdr3_length_input"] = (
                heavy.get("cdr3_length") or ""
            )
            st.session_state["dual_heavy_cdr1_motif_input"] = (
                heavy.get("cdr1_motif") or ""
            )
            st.session_state["dual_heavy_cdr2_motif_input"] = (
                heavy.get("cdr2_motif") or ""
            )
            st.session_state["dual_heavy_cdr3_motif_input"] = (
                heavy.get("cdr3_motif") or ""
            )
            st.session_state["dual_light_v_input"] = light.get("v", "")
            st.session_state["dual_light_j_input"] = light.get("j", "")
            st.session_state["dual_light_cdr1_length_input"] = (
                light.get("cdr1_length") or ""
            )
            st.session_state["dual_light_cdr2_length_input"] = (
                light.get("cdr2_length") or ""
            )
            st.session_state["dual_light_cdr3_length_input"] = (
                light.get("cdr3_length") or ""
            )
            st.session_state["dual_light_cdr1_motif_input"] = (
                light.get("cdr1_motif") or ""
            )
            st.session_state["dual_light_cdr2_motif_input"] = (
                light.get("cdr2_motif") or ""
            )
            st.session_state["dual_light_cdr3_motif_input"] = (
                light.get("cdr3_motif") or ""
            )
            st.session_state["heavy_main"] = True
            st.session_state["light_main"] = True
            st.session_state["paired_main"] = False
            for subdir in db_struct.get("Heavy", {}).keys():
                st.session_state[f"heavy_{subdir}"] = True
            for subdir in db_struct.get("Light", {}).keys():
                st.session_state[f"light_{subdir}"] = True
            st.session_state["paired_real_bundle"] = False
            st.session_state["search_prefill_message"] = (
                "Search criteria pre-filled from IgBLAST (dual unpaired). Select databases and run your search."
            )
        else:
            st.session_state["search_prefill_message"] = None

    is_plotting_locked = st.session_state.get("plotting_controls_locked", False)
    disable_db_selection = (
        st.session_state.search_status == "running"
    ) or is_plotting_locked
    selected_databases, selected_db, is_ready = render_database_selection(
        db_structure, disabled=disable_db_selection
    )
    if selected_databases is None:
        selected_databases = []

    loadable_databases = (
        st.session_state.get("loadable_databases_active", [])
        or selected_databases
    )
    overlay_databases = st.session_state.get("overlay_databases_active", [])

    # Determine database types in a single pass
    has_paired = False
    has_light = False
    has_heavy = False
    for db_path in loadable_databases:
        db_path_str = str(db_path)
        if "/Paired/" in db_path_str:
            has_paired = True
        elif "/Light/" in db_path_str:
            has_light = True
        elif "/Heavy/" in db_path_str:
            has_heavy = True

    def _serialize_selected_databases(db_paths: List[Any]) -> List[str]:
        """Normalize database identifiers for reuse after the user edits the mask."""
        try:
            return sorted([str(path) for path in db_paths])
        except Exception:
            return sorted([f"{path}" for path in db_paths])

    def render_cached_results_for_mode(
        cached_results: Dict[str, Any], current_mode: Optional[str] = None
    ) -> bool:
        engine_obj = st.session_state.get("search_engine")
        if engine_obj is None or not cached_results:
            return False

        mode = cached_results.get("mode")
        cached_selected_databases = cached_results.get("selected_databases")
        if mode == "dual_unpaired":
            if current_mode and current_mode != "dual_unpaired":
                return False
            heavy_result = cached_results.get("heavy")
            light_result = cached_results.get("light")
            if not heavy_result or not light_result:
                return False
            render_dual_search_criteria_display(
                heavy_result.get("statistics", {}),
                light_result.get("statistics", {}),
                selected_databases=cached_selected_databases,
            )
            render_dual_unpaired_results(
                heavy_result,
                light_result,
                engine_obj,
            )
            return True

        if current_mode == "dual_unpaired":
            return False

        is_cached_paired = cached_results.get("is_paired", mode == "paired")
        if current_mode == "paired" and not is_cached_paired:
            return False
        if (
            current_mode in ("unpaired_heavy", "unpaired_light")
            and is_cached_paired
        ):
            return False

        sequences_sample_df = cached_results.get("sequences_sample_df")
        statistics = cached_results.get("statistics")
        stats_df = cached_results.get("stats_df")
        search_params = cached_results.get("search_params", {})

        # Handle old cached results that might not have stats_df
        # Create empty stats_df if missing (from old API format)
        if stats_df is None:
            import pandas as pd  # Import only when needed

            stats_df = pd.DataFrame()

        if sequences_sample_df is None or statistics is None:
            return False

        render_search_criteria_display(
            search_params,
            is_cached_paired,
            selected_databases=cached_selected_databases,
        )
        render_search_results(
            sequences_sample_df,
            stats_df,
            statistics,
            is_cached_paired,
            search_params,
            engine_obj,
        )
        return True

    st.session_state["inferred_overlay_active"] = bool(overlay_databases)

    if has_paired:
        search_mode = "paired"
    elif has_heavy and has_light:
        search_mode = "dual_unpaired"
    elif has_heavy:
        search_mode = "unpaired_heavy"
    elif has_light:
        search_mode = "unpaired_light"
    else:
        search_mode = "unpaired_heavy"

    if not loadable_databases and not overlay_databases:
        if "last_search_results" in st.session_state:
            cached_results = st.session_state["last_search_results"]
            if render_cached_results_for_mode(cached_results):
                st.info(
                    "💡 **Tip:** Select databases above to perform a new search. Your previous results are shown below."
                )
        return

    if not is_ready:
        if "last_search_results" in st.session_state:
            cached_results = st.session_state["last_search_results"]
            render_cached_results_for_mode(
                cached_results, current_mode=search_mode
            )
        return

    if not selected_db:
        st.warning("⚠️ Please select at least one database to search")
        return

    # Show IgBLAST prefill message once, then clear
    prefill_msg = st.session_state.pop("search_prefill_message", None)
    if prefill_msg:
        st.info(f"💡 **{prefill_msg}**")

    engine = st.session_state["search_engine"]
    is_paired = search_mode == "paired"

    st.markdown("## :material/search: Search Criteria")
    st.divider()

    # Determine if form should be disabled
    search_status = st.session_state.search_status
    is_search_running = search_status == "running"
    disable_form_controls = is_search_running or is_plotting_locked

    if is_plotting_locked:
        st.info(
            ":material/hourglass: Result plots are loading. Search controls will unlock shortly."
        )

    # Disable form fields when search is running or plots are loading
    if search_mode == "paired":
        form_data = create_paired_search_form(disabled=disable_form_controls)
        search_params = form_data
        dual_form_data = None
    elif search_mode == "dual_unpaired":
        form_data = create_dual_unpaired_search_form(
            disabled=disable_form_controls
        )
        search_params = None
        dual_form_data = form_data
    else:
        form_data = create_unpaired_search_form(
            loadable_databases, disabled=disable_form_controls
        )
        search_params = form_data
        dual_form_data = None

    # Check if search parameters have changed (to reset completed status)
    if search_status == "completed":
        # Get current search parameters for comparison
        if search_mode == "dual_unpaired":
            current_params = {
                "mode": "dual_unpaired",
                "heavy": dual_form_data["heavy"]["search_params"]
                if dual_form_data
                else {},
                "light": dual_form_data["light"]["search_params"]
                if dual_form_data
                else {},
                "databases": sorted([str(db) for db in loadable_databases]),
            }
        else:
            current_params = {
                "mode": search_mode,
                "params": search_params,
                "databases": sorted([str(db) for db in loadable_databases]),
            }

        # Compare with last search parameters
        last_search_params = st.session_state.get(
            "last_search_params_for_comparison"
        )
        if last_search_params is None or last_search_params != current_params:
            # Parameters have changed, reset status to allow new search
            st.session_state.search_status = "idle"
            st.session_state.pop("search_completed_toast_shown", None)
            search_status = "idle"  # Update local variable

    sample_limit = 100

    if search_mode == "dual_unpaired":
        has_validation_errors = not dual_form_data.get("valid", True)
        validation_errors = dual_form_data.get("validation_errors", [])
    else:
        has_validation_errors = not search_params.get("valid", True)
        validation_errors = search_params.get("validation_errors", [])

    # Estimate phase based on elapsed time
    def estimate_search_phase(elapsed: float) -> str:
        if elapsed < 3:
            return "Initializing..."
        elif elapsed < 10:
            return "Searching database..."
        elif elapsed < 30:
            return "Processing results..."
        elif elapsed < 60:
            return "Calculating statistics..."
        else:
            return "Finalizing..."

    # Show custom button outside form when running (to avoid form constraints)
    if search_status == "running":
        elapsed = (
            time.time() - st.session_state.search_start_time
            if st.session_state.search_start_time
            else 0
        )
        phase = estimate_search_phase(elapsed)

        # Custom button with CSS spinner and cancel button side by side
        col_spinner, col_cancel = st.columns([3, 1])

        with col_spinner:
            st.markdown(
                f"""
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
            """,
                unsafe_allow_html=True,
            )

        with col_cancel:
            if st.button("Cancel Search", width="content"):
                if st.session_state.search_future is not None:
                    st.session_state.search_future.cancel()
                    st.session_state.search_future = None
                    st.session_state.search_start_time = None
                    st.session_state.search_status = "idle"
                    st.session_state.search_result = None
                    st.warning("Search cancellation requested")
                    st.rerun()

    with st.form("search_form"):
        if validation_errors:
            st.error(
                f"**Please fix the following serach filters before searching:** {', '.join(validation_errors)}",
                icon=":material/error:",
            )

        # Always show a submit button (required by Streamlit forms)
        if search_status == "idle":
            search_submitted = st.form_submit_button(
                ":material/database_search: Search Database",
                type="primary",
                disabled=(has_validation_errors or disable_form_controls),
                width="content",
            )
        elif search_status == "running":
            # Show hidden disabled submit button (required by Streamlit, but we show custom button above)
            # This button is hidden by global CSS (see top of file)
            search_submitted = st.form_submit_button(
                ":material/database_search: Search Database",
                disabled=True,
                width="content",
            )
        else:
            # For completed/failed, show disabled submit button with status
            result = st.session_state.search_result
            if (
                search_status == "completed"
                and result
                and result.get("success")
            ):
                total_time = (
                    time.time() - st.session_state.search_start_time
                    if st.session_state.search_start_time
                    else 0
                )
                time_label = f" in {total_time:.1f}s" if total_time else ""
                button_label = (
                    f":material/search_check_2: Search Complete{time_label}"
                )
            else:
                button_label = "❌ Search Failed"
                #! TODO Should never happen, when do we get here?

            # This button is hidden by global CSS (see top of file)
            search_submitted = st.form_submit_button(
                button_label, disabled=True, width="content"
            )

    # Show validation error (e.g. OAS-disallowed gene) right below the form, not after results
    search_validation_error = st.session_state.pop(
        "search_validation_error", None
    )
    if search_validation_error:
        st.error(f"**{search_validation_error}**", icon=":material/error:")

    # Add a small spacer to separate form from results
    st.markdown("<br>", unsafe_allow_html=True)

    results_container = st.empty()

    # Handle completed async search results (only process once, don't rerun immediately)
    if st.session_state.search_status == "completed":
        result = st.session_state.search_result

        # Handle case where result might not be a dict or might be missing 'success' key
        if not result:
            st.error(
                "❌ **Search failed:** No result returned from background process"
            )
            import sys

            print("[ERROR] Search failed: No result returned", file=sys.stderr)
            st.session_state.search_status = "idle"
        elif not isinstance(result, dict):
            st.error(
                f"❌ **Search failed:** Invalid result type: {type(result)}"
            )
            import sys

            print(
                f"[ERROR] Search failed: Invalid result type: {type(result)}",
                file=sys.stderr,
            )
            st.session_state.search_status = "idle"
        elif result.get("success"):
            # Debug logging: Track successful query execution details
            try:
                # Calculate total runtime
                total_runtime = 0.0
                if st.session_state.search_start_time:
                    total_runtime = (
                        time.time() - st.session_state.search_start_time
                    )

                # Calculate total data size
                def calculate_data_size(result_data):
                    """Calculate total memory size of DataFrames in result data."""
                    total_size = 0
                    import pandas as pd

                    if isinstance(result_data, dict):
                        for key, value in result_data.items():
                            if isinstance(value, pd.DataFrame):
                                total_size += value.memory_usage(
                                    deep=True
                                ).sum()
                            elif isinstance(value, dict):
                                total_size += calculate_data_size(value)
                    elif isinstance(result_data, pd.DataFrame):
                        total_size += result_data.memory_usage(deep=True).sum()

                    return total_size

                total_data_size_bytes = calculate_data_size(result)

                # Format sizes for readability
                def format_size(size_bytes):
                    for unit in ["B", "KB", "MB", "GB"]:
                        if size_bytes < 1024.0:
                            return f"{size_bytes:.2f} {unit}"
                        size_bytes /= 1024.0
                    return f"{size_bytes:.2f} TB"

                # Extract search details for logging
                if search_mode == "dual_unpaired":
                    heavy_hits = (
                        result.get("heavy", {})
                        .get("statistics", {})
                        .get("total_hits", 0)
                    )
                    light_hits = (
                        result.get("light", {})
                        .get("statistics", {})
                        .get("total_hits", 0)
                    )
                    logger.debug(
                        f"Query executed successfully - Mode: dual_unpaired, "
                        f"Total runtime: {total_runtime:.3f}s, "
                        f"Heavy hits: {heavy_hits:,}, Light hits: {light_hits:,}, "
                        f"Total data size: {format_size(total_data_size_bytes)}"
                    )
                else:
                    total_hits = (
                        result.get("statistics", {}).get("total_hits", 0)
                        if "statistics" in result
                        else 0
                    )
                    is_paired_str = "paired" if is_paired else search_mode
                    logger.debug(
                        f"Query executed successfully - Mode: {is_paired_str}, "
                        f"Total runtime: {total_runtime:.3f}s, "
                        f"Total hits: {total_hits:,}, "
                        f"Total data size: {format_size(total_data_size_bytes)}"
                    )
            except Exception as e:
                logger.debug(
                    f"Error calculating query execution details for logging: {e}"
                )

            # Show toast notification (only once)
            if "search_completed_toast_shown" not in st.session_state:
                total_hits = (
                    result.get("statistics", {}).get("total_hits", 0)
                    if "statistics" in result
                    else 0
                )
                if search_mode == "dual_unpaired":
                    heavy_hits = (
                        result.get("heavy", {})
                        .get("statistics", {})
                        .get("total_hits", 0)
                    )
                    light_hits = (
                        result.get("light", {})
                        .get("statistics", {})
                        .get("total_hits", 0)
                    )
                    st.toast(
                        f"Search completed! Found {heavy_hits:,} heavy and {light_hits:,} light sequences",
                        icon=":material/search_check_2:",
                    )
                else:
                    st.toast(
                        f"Search completed! Found {total_hits:,} sequences",
                        icon=":material/search_check_2:",
                    )
                st.session_state["search_completed_toast_shown"] = True

            # Note: Search parameters are stored when search is submitted, not here

            if search_mode == "dual_unpaired":
                # Dual unpaired results
                heavy_result = result.get("heavy")
                light_result = result.get("light")
                if heavy_result and light_result:
                    st.session_state["last_search_results"] = {
                        "mode": "dual_unpaired",
                        "heavy": heavy_result,
                        "light": light_result,
                        "selected_databases": _serialize_selected_databases(
                            loadable_databases
                        ),
                    }
                    with results_container.container():
                        render_dual_unpaired_results(
                            heavy_result, light_result, engine
                        )
            else:
                # Single search results (paired or unpaired)
                sequences_sample_df = result.get("sequences_sample_df")
                stats_df = result.get("stats_df")
                statistics = result.get("statistics")
                search_params_result = result.get("search_params")

                # Handle 0 hits case - sequences_sample_df might be empty but should still be a DataFrame
                # Check if statistics exists (which should always be present even with 0 hits)
                if statistics is not None:
                    # Ensure sequences_sample_df is a DataFrame (even if empty)
                    import pandas as pd

                    if sequences_sample_df is None:
                        sequences_sample_df = pd.DataFrame()
                    if stats_df is None:
                        stats_df = pd.DataFrame()

                    st.session_state["last_search_results"] = {
                        "mode": "paired" if is_paired else search_mode,
                        "sequences_sample_df": sequences_sample_df,
                        "statistics": statistics,
                        "stats_df": stats_df,
                        "is_paired": is_paired,
                        "search_params": search_params_result,
                        "selected_databases": _serialize_selected_databases(
                            loadable_databases
                        ),
                    }
                    try:
                        # Ensure engine is valid before rendering
                        if engine is None:
                            raise ValueError(
                                "Search engine is not available. Please reload the page."
                            )

                        with results_container.container():
                            render_search_results(
                                sequences_sample_df,
                                stats_df,
                                statistics,
                                is_paired,
                                search_params_result,
                                engine,
                            )
                    except Exception as render_error:
                        # If rendering fails, show error but don't mark search as failed
                        # This allows user to try again without reloading
                        st.error(
                            f"❌ **Error displaying results:** {str(render_error)}"
                        )
                        st.exception(render_error)
                        # Reset status so user can try again
                        st.session_state.search_status = "idle"
                        # Clear the problematic result to prevent retry issues
                        st.session_state.search_result = None
                else:
                    # Statistics is None but success is True - this shouldn't happen
                    st.error(
                        "❌ **Search completed but no statistics returned.** Please try again."
                    )
                    # Reset status so user can try again
                    st.session_state.search_status = "idle"
            # Don't reset status immediately - keep it as "completed" until parameters change or new search starts
        else:
            # Search failed - show error with full details
            if result:
                error_msg = result.get("error", "Unknown error")
                error_type = result.get("error_type", "Unknown")
                traceback_str = result.get("traceback", "")

                # Show error message
                st.error(f"❌ **Search failed:** {error_msg}")

                # Show error type if available
                if error_type != "Unknown":
                    st.caption(f"Error type: {error_type}")

                # Show full traceback in expander for debugging
                if traceback_str:
                    with st.expander("Show full error details"):
                        st.code(traceback_str, language="python")

                # Also print to stderr for terminal logging
                import sys

                print(
                    f"[ERROR] Search failed: {error_type}: {error_msg}",
                    file=sys.stderr,
                )
                if traceback_str:
                    print(
                        f"[ERROR] Traceback:\n{traceback_str}", file=sys.stderr
                    )
            else:
                st.error(
                    "❌ **Search failed:** No result returned from background process"
                )
                import sys

                print(
                    "[ERROR] Search failed: No result returned", file=sys.stderr
                )

            # Reset status after showing error so user can retry
            st.session_state.search_status = "idle"

    # Show cached results if we have previous results (but not if we just completed a search)
    if (
        st.session_state.search_status == "idle"
        and "last_search_results" in st.session_state
    ):
        cached_results = st.session_state["last_search_results"]
        with results_container.container():
            render_cached_results_for_mode(
                cached_results, current_mode=search_mode
            )

    if not search_submitted or is_search_running:
        return

    # Reset status when starting a new search (clear the completed/failed state)
    if st.session_state.search_status in ("completed", "failed"):
        st.session_state.search_status = "idle"
        st.session_state.pop(
            "search_completed_toast_shown", None
        )  # Clear toast flag
        # Clear any previous search result to avoid stale data
        st.session_state.search_result = None
        st.session_state.search_future = None

    if search_mode == "dual_unpaired":
        heavy_info = dual_form_data["heavy"]
        light_info = dual_form_data["light"]

        heavy_valid, heavy_error = validate_search_criteria(
            heavy_info["search_params"], False
        )
        light_valid, light_error = validate_search_criteria(
            light_info["search_params"], False
        )
        if not heavy_valid or not light_valid:
            parts = []
            if not heavy_valid and heavy_error:
                parts.append(f"Heavy Chain: {heavy_error}")
            if not light_valid and light_error:
                parts.append(f"Light Chain: {light_error}")
            st.session_state["search_validation_error"] = " ".join(parts)
            st.rerun()
            return

        # Store search parameters for comparison (to detect changes later)
        st.session_state["last_search_params_for_comparison"] = {
            "mode": "dual_unpaired",
            "heavy": heavy_info["search_params"],
            "light": light_info["search_params"],
            "databases": sorted([str(db) for db in loadable_databases]),
        }

        # Submit async dual search task
        future = executor.submit(
            perform_dual_unpaired_search_background,
            loadable_databases,
            heavy_info["search_params"],
            light_info["search_params"],
            sample_limit,
        )
        st.session_state.search_future = future
        st.session_state.search_start_time = time.time()
        st.session_state.search_result = None
        st.session_state.search_status = "running"
        st.rerun()
        return

    is_valid, error_message = validate_search_criteria(search_params, is_paired)
    if not is_valid:
        if error_message:
            st.session_state["search_validation_error"] = error_message
        st.rerun()
        return

    # Store search parameters for comparison (to detect changes later)
    st.session_state["last_search_params_for_comparison"] = {
        "mode": search_mode,
        "params": search_params,
        "databases": sorted([str(db) for db in loadable_databases]),
    }

    # Submit async search task
    future = executor.submit(
        # why is this in @test_utils.py ?
        perform_database_search_background,
        loadable_databases,
        search_params,
        is_paired,
        sample_limit,
    )
    st.session_state.search_future = future
    st.session_state.search_start_time = time.time()
    st.session_state.search_result = None
    st.session_state.search_status = "running"
    st.rerun()


search_page_content()
