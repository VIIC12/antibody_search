import streamlit as st
import concurrent.futures
import time
from components.test_utils import (
    perform_heavy_chain_search,
    prepare_fasta_download_background,
)
from components.search.database_utils import get_database_structure
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Async Test", layout="wide")

# Inject CSS for spinner animation
st.markdown(
    """
<style>
@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}

.spinner-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
}

.spinner {
    border: 2px solid #f3f3f3;
    border-top: 2px solid #3498db;
    border-radius: 50%;
    width: 16px;
    height: 16px;
    animation: spin 1s linear infinite;
}

.spinner-dark {
    border: 2px solid rgba(255, 255, 255, 0.2);
    border-top: 2px solid #ffffff;
    border-radius: 50%;
    width: 16px;
    height: 16px;
    animation: spin 1s linear infinite;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🔀 Background Database Search Test")
st.markdown("---")

# Initialize session state for background tasks
if "background_future" not in st.session_state:
    st.session_state.background_future = None
if "background_result" not in st.session_state:
    st.session_state.background_result = None
if "background_start_time" not in st.session_state:
    st.session_state.background_start_time = None
if "background_status" not in st.session_state:
    st.session_state.background_status = (
        "idle"  # idle, running, completed, failed
    )

# Initialize session state for FASTA download tasks
if "fasta_future" not in st.session_state:
    st.session_state.fasta_future = None
if "fasta_result" not in st.session_state:
    st.session_state.fasta_result = None
if "fasta_start_time" not in st.session_state:
    st.session_state.fasta_start_time = None
if "fasta_status" not in st.session_state:
    st.session_state.fasta_status = "idle"  # idle, running, completed, failed


# Get or create executor
@st.cache_resource
def get_executor():
    MAX_WORKERS = 4
    return concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS)


executor = get_executor()


# Status checking function (non-blocking)
def check_task_status():
    """Check task status without blocking - updates session state"""
    if st.session_state.background_future is not None:
        if st.session_state.background_future.done():
            try:
                result = st.session_state.background_future.result()
                st.session_state.background_result = result
                st.session_state.background_future = None
                elapsed = time.time() - st.session_state.background_start_time
                st.session_state.background_start_time = None
                st.session_state.background_status = "completed"
                return True, result, elapsed
            except Exception as e:
                st.session_state.background_future = None
                st.session_state.background_start_time = None
                st.session_state.background_status = "failed"
                return False, str(e), None
    return None, None, None


def check_fasta_status():
    """Check FASTA task status without blocking - updates session state."""
    if st.session_state.fasta_future is not None:
        if st.session_state.fasta_future.done():
            try:
                result = st.session_state.fasta_future.result()
                st.session_state.fasta_result = result
                st.session_state.fasta_future = None
                st.session_state.fasta_start_time = None
                st.session_state.fasta_status = (
                    "completed" if result.get("success") else "failed"
                )
                return True, result, None
            except Exception as e:
                st.session_state.fasta_future = None
                st.session_state.fasta_start_time = None
                st.session_state.fasta_status = "failed"
                return False, str(e), None
    return None, None, None


# Check status on every run (non-blocking check)
check_task_status()

# Auto-refresh when background task is running (every 2 seconds)
# This must be called during every script execution when a task is running
if st.session_state.background_status == "running":
    # Auto-refresh every 2 seconds to check task status
    # This will trigger automatic page refreshes while task is running
    st_autorefresh(interval=2000, key="background_task_refresh")

# Display status (this executes instantly - no blocking)
if st.session_state.background_status == "running":
    elapsed_time = (
        time.time() - st.session_state.background_start_time
        if st.session_state.background_start_time
        else 0
    )
    st.info(
        f"⏳ **Database search is running in the background...** (elapsed: {elapsed_time:.1f}s)"
    )
    st.caption(
        "🔄 **Auto-refreshing every 2 seconds** - you'll be notified automatically when it completes!"
    )
elif st.session_state.background_status == "completed":
    result = st.session_state.background_result
    if result and result.get("success"):
        total_hits = result.get("total_hits", 0)
        st.success(
            f"✅ **Search completed!** Found **{total_hits:,}** matching sequences"
        )
    else:
        error_msg = (
            result.get("error", "Unknown error") if result else "Unknown error"
        )
        st.error(f"❌ **Search failed:** {error_msg}")
elif st.session_state.background_status == "failed":
    st.error("❌ **Task failed**")

# Get database structure to find Heavy chain databases
db_structure = get_database_structure()
heavy_databases = []
for subdir, info in db_structure.get("Heavy", {}).items():
    heavy_databases.append(info["path"])

if not heavy_databases:
    st.error(
        "❌ No Heavy chain databases found! Please ensure databases are available."
    )
    st.stop()

# Search parameters form
st.markdown("### 🔍 Search Parameters")
col_param1, col_param2 = st.columns(2)

with col_param1:
    heavy_v = st.text_input(
        "VH Gene",
        value="IGHV1-2",
        help="Enter VH gene(s), e.g., 'IGHV1-2' or 'IGHV1-2,IGHV1-3' for multiple genes",
        disabled=st.session_state.background_status == "running",
    )

with col_param2:
    heavy_cdr3_motif = st.text_input(
        "CDR3 Motif",
        value="AR",
        help="Enter CDR3 motif pattern to search for, e.g., 'AR' or 'AR.*DY'",
        disabled=st.session_state.background_status == "running",
    )

sample_limit = st.number_input(
    "Sample Limit",
    min_value=10,
    max_value=1000,
    value=100,
    step=10,
    help="Maximum number of sample sequences to return",
    disabled=st.session_state.background_status == "running",
)

st.caption(
    f"📊 Searching in **{len(heavy_databases)}** Heavy chain database(s)"
)

# Control section
col1, col2, col3 = st.columns(3)

with col1:
    if st.button(
        "🚀 Start Database Search",
        disabled=st.session_state.background_status == "running",
    ):
        if not heavy_v and not heavy_cdr3_motif:
            st.warning(
                "⚠️ Please enter at least one search criterion (VH Gene or CDR3 Motif)"
            )
        else:
            # Submit new task - this returns immediately, doesn't block!
            future = executor.submit(
                perform_heavy_chain_search,
                heavy_databases,
                heavy_v,
                heavy_cdr3_motif,
                int(sample_limit),
            )
            st.session_state.background_future = future
            st.session_state.background_start_time = time.time()
            st.session_state.background_result = None
            st.session_state.background_status = "running"
            # Trigger immediate rerun to activate auto-refresh
            st.rerun()

with col2:
    if st.button("🔄 Check Status"):
        # Manually check status - this will trigger a rerun only if status changed
        old_status = st.session_state.background_status
        check_task_status()
        if st.session_state.background_status != old_status:
            st.rerun()

with col3:
    if st.button(
        "🛑 Cancel Task",
        disabled=st.session_state.background_status != "running",
    ):
        if st.session_state.background_future is not None:
            st.session_state.background_future.cancel()
            st.session_state.background_future = None
            st.session_state.background_start_time = None
            st.session_state.background_status = "idle"
            st.warning("Task cancellation requested")

# Show search results if available
if st.session_state.background_result is not None:
    result = st.session_state.background_result
    st.markdown("---")
    st.markdown("### 📊 Search Results")

    if result.get("success"):
        total_hits = result.get("total_hits", 0)
        sequences_df = result.get("sequences_sample_df")
        stats_df = result.get("stats_df")
        statistics = result.get("statistics", {})

        st.metric("Total Hits", f"{total_hits:,}")

        if sequences_df is not None and not sequences_df.empty:
            st.markdown("#### Sample Sequences")
            st.dataframe(sequences_df, width="stretch")

        if stats_df is not None and not stats_df.empty:
            st.markdown("#### Statistics by Subject")
            st.dataframe(stats_df, width="stretch")

        if statistics:
            st.markdown("#### Search Statistics")
            st.json(statistics)
    else:
        st.error(f"❌ Search failed: {result.get('error', 'Unknown error')}")
        if result.get("error_type"):
            st.caption(f"Error type: {result.get('error_type')}")

# ============================================================================
# FASTA Download UI/UX Options Comparison
# ============================================================================
st.markdown("---")
st.markdown("## 📥 FASTA Download UI/UX Options Comparison")
st.markdown(
    "**Compare three different UI/UX approaches for background FASTA generation**"
)
st.caption(
    "Each option demonstrates a different way to show progress and completion status. Test all three to decide which works best!"
)

# Initialize FASTA task states for each option
if "fasta_tasks" not in st.session_state:
    st.session_state.fasta_tasks = {
        "option_a": None,
        "option_b": None,
        "option_c": None,
    }

if "fasta_results" not in st.session_state:
    st.session_state.fasta_results = {
        "option_a": None,
        "option_b": None,
        "option_c": None,
    }

# Initialize fasta_status - handle migration from old string format to new dict format
if "fasta_status" not in st.session_state:
    st.session_state.fasta_status = {
        "option_a": "idle",
        "option_b": "idle",
        "option_c": "idle",
    }
elif isinstance(st.session_state.fasta_status, str):
    # Migrate from old string format to new dict format
    old_status = st.session_state.fasta_status
    st.session_state.fasta_status = {
        "option_a": old_status
        if old_status in ["running", "completed", "failed"]
        else "idle",
        "option_b": "idle",
        "option_c": "idle",
    }
elif not isinstance(st.session_state.fasta_status, dict):
    # If it's something else, reset to dict
    st.session_state.fasta_status = {
        "option_a": "idle",
        "option_b": "idle",
        "option_c": "idle",
    }

# Initialize fasta_start_time - handle migration from old format
if "fasta_start_time" not in st.session_state:
    st.session_state.fasta_start_time = {
        "option_a": None,
        "option_b": None,
        "option_c": None,
    }
elif not isinstance(st.session_state.fasta_start_time, dict):
    # If it's not a dict (e.g., was a single timestamp), convert to dict
    st.session_state.fasta_start_time = {
        "option_a": None,
        "option_b": None,
        "option_c": None,
    }

# Store timing history for estimates
if "fasta_timing_history" not in st.session_state:
    st.session_state.fasta_timing_history = []


def estimate_remaining_time(
    elapsed: float, total_sequences: int = None
) -> tuple[str, str]:
    """
    Estimate remaining time and provide feedback based on elapsed time.

    Returns:
        Tuple of (phase_description, time_estimate)
    """
    # Typical timing patterns (in seconds)
    # Based on experience: search usually takes 60-80% of time, FASTA generation 20-40%
    if elapsed < 3:
        return "Initializing search...", "~10-30s remaining"
    elif elapsed < 10:
        return "Searching database...", "~5-20s remaining"
    elif elapsed < 30:
        return "Processing results...", "~3-15s remaining"
    elif elapsed < 60:
        return "Generating FASTA file...", "~2-10s remaining"
    else:
        # For longer operations, estimate based on elapsed time
        # Assume most operations complete within 2-3 minutes
        if elapsed < 120:
            return "Finalizing FASTA file...", "~5-30s remaining"
        else:
            return "Processing large dataset...", "Please wait..."


# Status checking for all options
def check_fasta_task_status(option_key):
    """Check FASTA task status for a specific option"""
    task = st.session_state.fasta_tasks.get(option_key)
    if task is not None:
        if task.done():
            try:
                result = task.result()
                st.session_state.fasta_results[option_key] = result
                st.session_state.fasta_tasks[option_key] = None
                elapsed = (
                    time.time() - st.session_state.fasta_start_time[option_key]
                )

                # Store timing history for future estimates
                if result.get("success"):
                    timing_info = {
                        "elapsed": elapsed,
                        "sequence_count": result.get("sequence_count", 0),
                        "file_size_mb": result.get("file_size_bytes", 0)
                        / 1024
                        / 1024,
                        "timestamp": time.time(),
                    }
                    st.session_state.fasta_timing_history.append(timing_info)
                    # Keep only last 10 timings
                    if len(st.session_state.fasta_timing_history) > 10:
                        st.session_state.fasta_timing_history.pop(0)

                st.session_state.fasta_start_time[option_key] = None
                st.session_state.fasta_status[option_key] = (
                    "completed" if result.get("success") else "failed"
                )
                return True, result, elapsed
            except Exception as e:
                st.session_state.fasta_tasks[option_key] = None
                st.session_state.fasta_start_time[option_key] = None
                st.session_state.fasta_status[option_key] = "failed"
                return False, str(e), None
    return None, None, None


# Check all task statuses
for option in ["option_a", "option_b", "option_c"]:
    check_fasta_task_status(option)

# Auto-refresh if any task is running
if any(
    st.session_state.fasta_status[opt] == "running"
    for opt in ["option_a", "option_b", "option_c"]
):
    st_autorefresh(interval=2000, key="fasta_options_refresh")

# Shared search parameters for all options
st.markdown("### 🔍 Shared Search Parameters")
col_shared1, col_shared2 = st.columns(2)

with col_shared1:
    shared_heavy_v = st.text_input(
        "VH Gene (All Options)",
        value="IGHV1-2",
        help="Enter VH gene(s) for FASTA download",
        key="shared_fasta_vh_gene",
    )

with col_shared2:
    shared_heavy_cdr3_motif = st.text_input(
        "CDR3 Motif (All Options)",
        value="AR",
        help="Enter CDR3 motif pattern for FASTA download",
        key="shared_fasta_cdr3_motif",
    )

col_shared3, col_shared4 = st.columns(2)
with col_shared3:
    shared_include_heavy = st.checkbox(
        "Include Heavy Chain", value=True, key="shared_fasta_include_heavy"
    )
with col_shared4:
    shared_include_light = st.checkbox(
        "Include Light Chain", value=False, key="shared_fasta_include_light"
    )

st.divider()

# ============================================================================
# Option A: Inline Status Indicator
# ============================================================================
st.markdown("### Option A: Inline Status Indicator")
st.caption("Status appears directly below the button. Simple and clear.")

col_a1, col_a2 = st.columns([2, 1])

with col_a1:
    status_a = st.session_state.fasta_status["option_a"]

    if status_a == "idle":
        if st.button(
            "📥 Download FASTA", key="option_a_start", width="stretch"
        ):
            if not shared_heavy_v and not shared_heavy_cdr3_motif:
                st.warning("⚠️ Please enter at least one search criterion")
            elif not shared_include_heavy and not shared_include_light:
                st.warning("⚠️ Please select at least one chain type")
            else:
                # Ensure dictionaries are initialized
                if not isinstance(st.session_state.fasta_start_time, dict):
                    st.session_state.fasta_start_time = {
                        "option_a": None,
                        "option_b": None,
                        "option_c": None,
                    }
                if not isinstance(st.session_state.fasta_status, dict):
                    st.session_state.fasta_status = {
                        "option_a": "idle",
                        "option_b": "idle",
                        "option_c": "idle",
                    }
                if not isinstance(st.session_state.fasta_tasks, dict):
                    st.session_state.fasta_tasks = {
                        "option_a": None,
                        "option_b": None,
                        "option_c": None,
                    }

                future = executor.submit(
                    prepare_fasta_download_background,
                    heavy_databases,
                    shared_heavy_v,
                    shared_heavy_cdr3_motif,
                    shared_include_heavy,
                    shared_include_light,
                )
                st.session_state.fasta_tasks["option_a"] = future
                st.session_state.fasta_start_time["option_a"] = time.time()
                st.session_state.fasta_status["option_a"] = "running"
                st.rerun()

    elif status_a == "running":
        elapsed = (
            time.time() - st.session_state.fasta_start_time["option_a"]
            if st.session_state.fasta_start_time["option_a"]
            else 0
        )
        phase, time_estimate = estimate_remaining_time(elapsed)

        # Custom button with CSS spinner
        st.markdown(
            """
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
                <span>Preparing FASTA...</span>
            </button>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Progress feedback with time estimates
        col_progress1, col_progress2 = st.columns([2, 1])
        with col_progress1:
            st.info(f"⏳ **{phase}** (elapsed: {elapsed:.1f}s)")
        with col_progress2:
            st.caption(f"⏱️ {time_estimate}")
        st.caption("🔄 Auto-refreshing every 2 seconds")

    elif status_a == "completed":
        result_a = st.session_state.fasta_results.get("option_a")
        if result_a and result_a.get("success"):
            file_size_mb = result_a.get("file_size_bytes", 0) / 1024 / 1024
            sequence_count = result_a.get("sequence_count", 0)

            # Calculate total time (stored in timing history)
            total_time = None
            if st.session_state.fasta_timing_history:
                latest = st.session_state.fasta_timing_history[-1]
                total_time = latest.get("elapsed", 0)

            # The original button becomes the download button
            st.download_button(
                label=f"📥 Download FASTA ({sequence_count:,} sequences, {file_size_mb:.2f} MB)",
                data=result_a.get("content", ""),
                file_name=result_a.get("filename", "sequences.fasta"),
                mime="text/plain",
                width="stretch",
                key="download_option_a",
            )

            if total_time:
                st.success(
                    f"✅ **FASTA file ready!** {sequence_count:,} sequences ({file_size_mb:.2f} MB) in {total_time:.1f}s"
                )
            else:
                st.success(
                    f"✅ **FASTA file ready!** {sequence_count:,} sequences ({file_size_mb:.2f} MB)"
                )
            st.caption(f"Filename: `{result_a.get('filename', 'unknown')}`")
        else:
            st.error(
                f"❌ Failed: {result_a.get('error', 'Unknown error') if result_a else 'Unknown error'}"
            )

    elif status_a == "failed":
        st.error("❌ FASTA generation failed")
        if st.button("🔄 Retry", key="option_a_retry"):
            st.session_state.fasta_status["option_a"] = "idle"
            st.session_state.fasta_results["option_a"] = None
            st.rerun()

with col_a2:
    if st.button("🔄 Reset Option A", key="reset_option_a"):
        st.session_state.fasta_tasks["option_a"] = None
        st.session_state.fasta_results["option_a"] = None
        st.session_state.fasta_status["option_a"] = "idle"
        st.session_state.fasta_start_time["option_a"] = None
        st.rerun()

st.divider()

# ============================================================================
# Option B: Toast Notification + Button Update
# ============================================================================
st.markdown("### Option B: Toast Notification + Button Update")
st.caption(
    "Button updates its text, and a toast notification appears when ready."
)

col_b1, col_b2 = st.columns([2, 1])

with col_b1:
    status_b = st.session_state.fasta_status["option_b"]

    # Show toast notification when completed
    if status_b == "completed" and st.session_state.fasta_results.get(
        "option_b"
    ):
        result_b = st.session_state.fasta_results.get("option_b")
        if result_b and result_b.get("success"):
            st.toast("✅ FASTA file is ready for download!", icon="✅")

    if status_b == "idle":
        if st.button(
            "📥 Download FASTA", key="option_b_start", width="stretch"
        ):
            if not shared_heavy_v and not shared_heavy_cdr3_motif:
                st.warning("⚠️ Please enter at least one search criterion")
            elif not shared_include_heavy and not shared_include_light:
                st.warning("⚠️ Please select at least one chain type")
            else:
                # Ensure dictionaries are initialized
                if not isinstance(st.session_state.fasta_start_time, dict):
                    st.session_state.fasta_start_time = {
                        "option_a": None,
                        "option_b": None,
                        "option_c": None,
                    }
                if not isinstance(st.session_state.fasta_status, dict):
                    st.session_state.fasta_status = {
                        "option_a": "idle",
                        "option_b": "idle",
                        "option_c": "idle",
                    }
                if not isinstance(st.session_state.fasta_tasks, dict):
                    st.session_state.fasta_tasks = {
                        "option_a": None,
                        "option_b": None,
                        "option_c": None,
                    }

                future = executor.submit(
                    prepare_fasta_download_background,
                    heavy_databases,
                    shared_heavy_v,
                    shared_heavy_cdr3_motif,
                    shared_include_heavy,
                    shared_include_light,
                )
                st.session_state.fasta_tasks["option_b"] = future
                st.session_state.fasta_start_time["option_b"] = time.time()
                st.session_state.fasta_status["option_b"] = "running"
                st.rerun()

    elif status_b == "running":
        elapsed = (
            time.time() - st.session_state.fasta_start_time["option_b"]
            if st.session_state.fasta_start_time["option_b"]
            else 0
        )
        phase, time_estimate = estimate_remaining_time(elapsed)

        # Custom button with CSS spinner
        st.markdown(
            """
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
                <span>Preparing FASTA...</span>
            </button>
        </div>
        """,
            unsafe_allow_html=True,
        )
        st.caption(f"⏳ {phase} | Elapsed: {elapsed:.1f}s | ⏱️ {time_estimate}")

    elif status_b == "completed":
        result_b = st.session_state.fasta_results.get("option_b")
        if result_b and result_b.get("success"):
            file_size_mb = result_b.get("file_size_bytes", 0) / 1024 / 1024
            sequence_count = result_b.get("sequence_count", 0)

            # Calculate total time
            total_time = None
            if st.session_state.fasta_timing_history:
                latest = st.session_state.fasta_timing_history[-1]
                total_time = latest.get("elapsed", 0)

            # The original button becomes the download button
            st.download_button(
                label=f"📥 Download FASTA ({sequence_count:,} sequences, {file_size_mb:.2f} MB)",
                data=result_b.get("content", ""),
                file_name=result_b.get("filename", "sequences.fasta"),
                mime="text/plain",
                width="stretch",
                type="primary",
                key="download_option_b",
            )
            if total_time:
                st.caption(
                    f"✅ Ready to download | Completed in {total_time:.1f}s | Filename: `{result_b.get('filename', 'unknown')}`"
                )
            else:
                st.caption(
                    f"✅ Ready to download | Filename: `{result_b.get('filename', 'unknown')}`"
                )
        else:
            st.error(
                f"❌ Failed: {result_b.get('error', 'Unknown error') if result_b else 'Unknown error'}"
            )

    elif status_b == "failed":
        st.error("❌ FASTA generation failed")
        if st.button("🔄 Retry", key="option_b_retry"):
            st.session_state.fasta_status["option_b"] = "idle"
            st.session_state.fasta_results["option_b"] = None
            st.rerun()

with col_b2:
    if st.button("🔄 Reset Option B", key="reset_option_b"):
        st.session_state.fasta_tasks["option_b"] = None
        st.session_state.fasta_results["option_b"] = None
        st.session_state.fasta_status["option_b"] = "idle"
        st.session_state.fasta_start_time["option_b"] = None
        st.rerun()

st.divider()

# ============================================================================
# Option C: Status Badge on Button
# ============================================================================
st.markdown("### Option C: Status Badge on Button")
st.caption(
    "The button itself shows the status with different text and styling."
)

col_c1, col_c2 = st.columns([2, 1])

with col_c1:
    status_c = st.session_state.fasta_status["option_c"]

    if status_c == "idle":
        if st.button(
            "📥 Download FASTA", key="option_c_start", width="stretch"
        ):
            if not shared_heavy_v and not shared_heavy_cdr3_motif:
                st.warning("⚠️ Please enter at least one search criterion")
            elif not shared_include_heavy and not shared_include_light:
                st.warning("⚠️ Please select at least one chain type")
            else:
                # Ensure dictionaries are initialized
                if not isinstance(st.session_state.fasta_start_time, dict):
                    st.session_state.fasta_start_time = {
                        "option_a": None,
                        "option_b": None,
                        "option_c": None,
                    }
                if not isinstance(st.session_state.fasta_status, dict):
                    st.session_state.fasta_status = {
                        "option_a": "idle",
                        "option_b": "idle",
                        "option_c": "idle",
                    }
                if not isinstance(st.session_state.fasta_tasks, dict):
                    st.session_state.fasta_tasks = {
                        "option_a": None,
                        "option_b": None,
                        "option_c": None,
                    }

                future = executor.submit(
                    prepare_fasta_download_background,
                    heavy_databases,
                    shared_heavy_v,
                    shared_heavy_cdr3_motif,
                    shared_include_heavy,
                    shared_include_light,
                )
                st.session_state.fasta_tasks["option_c"] = future
                st.session_state.fasta_start_time["option_c"] = time.time()
                st.session_state.fasta_status["option_c"] = "running"
                st.rerun()

    elif status_c == "running":
        elapsed = (
            time.time() - st.session_state.fasta_start_time["option_c"]
            if st.session_state.fasta_start_time["option_c"]
            else 0
        )
        phase, _ = estimate_remaining_time(elapsed)

        # Custom button with CSS spinner and phase info (no elapsed time)
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

    elif status_c == "completed":
        result_c = st.session_state.fasta_results.get("option_c")
        if result_c and result_c.get("success"):
            # Show toast notification when completed
            st.toast("✅ FASTA file is ready for download!", icon="✅")

            file_size_mb = result_c.get("file_size_bytes", 0) / 1024 / 1024
            sequence_count = result_c.get("sequence_count", 0)

            # Calculate total time
            total_time = None
            if st.session_state.fasta_timing_history:
                latest = st.session_state.fasta_timing_history[-1]
                total_time = latest.get("elapsed", 0)

            # The original button becomes the download button (shows status in label)
            time_label = f" in {total_time:.1f}s" if total_time else ""
            st.download_button(
                label=f"✅ Download FASTA ({sequence_count:,} sequences, {file_size_mb:.2f} MB{time_label})",
                data=result_c.get("content", ""),
                file_name=result_c.get("filename", "sequences.fasta"),
                mime="text/plain",
                width="stretch",
                type="primary",
                key="download_option_c",
            )
            st.caption(f"Filename: `{result_c.get('filename', 'unknown')}`")
        else:
            st.button(
                "❌ Generation Failed",
                disabled=True,
                key="option_c_failed",
                width="stretch",
            )
            st.error(
                f"❌ {result_c.get('error', 'Unknown error') if result_c else 'Unknown error'}"
            )

    elif status_c == "failed":
        st.button(
            "❌ Generation Failed - Click to Retry",
            disabled=False,
            key="option_c_retry_button",
            width="stretch",
        )
        if st.button("🔄 Retry", key="option_c_retry"):
            st.session_state.fasta_status["option_c"] = "idle"
            st.session_state.fasta_results["option_c"] = None
            st.rerun()

with col_c2:
    if st.button("🔄 Reset Option C", key="reset_option_c"):
        st.session_state.fasta_tasks["option_c"] = None
        st.session_state.fasta_results["option_c"] = None
        st.session_state.fasta_status["option_c"] = "idle"
        st.session_state.fasta_start_time["option_c"] = None
        st.rerun()

st.divider()
st.markdown("### 💡 Comparison Notes")
st.markdown("""
- **Option A**: Status appears as a separate info box below the button. Clear separation of action and status.
- **Option B**: Button text changes and toast notification appears. Good for non-intrusive notifications.
- **Option C**: Button itself shows all status information. Most compact, all info in one place.
""")

# Display FASTA status
if st.session_state.fasta_status == "running":
    elapsed_time = (
        time.time() - st.session_state.fasta_start_time
        if st.session_state.fasta_start_time
        else 0
    )
    st.info(
        f"⏳ **FASTA generation is running in the background...** (elapsed: {elapsed_time:.1f}s)"
    )
    st.caption(
        "🔄 **Auto-refreshing every 2 seconds** - you'll be notified automatically when it completes!"
    )
elif st.session_state.fasta_status == "completed":
    fasta_result = st.session_state.fasta_result
    if fasta_result and fasta_result.get("success"):
        sequence_count = fasta_result.get("sequence_count", 0)
        file_size = fasta_result.get("file_size_bytes", 0)
        file_size_mb = file_size / 1024 / 1024
        st.success(
            f"✅ **FASTA file ready!** {sequence_count:,} sequences ({file_size_mb:.2f} MB)"
        )
    else:
        error_msg = (
            fasta_result.get("error", "Unknown error")
            if fasta_result
            else "Unknown error"
        )
        st.error(f"❌ **FASTA generation failed:** {error_msg}")
elif st.session_state.fasta_status == "failed":
    st.error("❌ **FASTA generation failed**")

# FASTA search parameters
st.markdown("### 🔍 FASTA Search Parameters")
col_fasta1, col_fasta2 = st.columns(2)

with col_fasta1:
    fasta_heavy_v = st.text_input(
        "VH Gene (FASTA)",
        value="IGHV1-2",
        help="Enter VH gene(s) for FASTA download",
        disabled=st.session_state.fasta_status == "running",
        key="fasta_vh_gene",
    )

with col_fasta2:
    fasta_heavy_cdr3_motif = st.text_input(
        "CDR3 Motif (FASTA)",
        value="AR",
        help="Enter CDR3 motif pattern for FASTA download",
        disabled=st.session_state.fasta_status == "running",
        key="fasta_cdr3_motif",
    )

col_fasta3, col_fasta4 = st.columns(2)
with col_fasta3:
    fasta_include_heavy = st.checkbox(
        "Include Heavy Chain",
        value=True,
        disabled=st.session_state.fasta_status == "running",
        key="fasta_include_heavy",
    )
with col_fasta4:
    fasta_include_light = st.checkbox(
        "Include Light Chain",
        value=False,
        disabled=st.session_state.fasta_status == "running",
        key="fasta_include_light",
    )

# FASTA control buttons
col_fasta_btn1, col_fasta_btn2, col_fasta_btn3 = st.columns(3)

with col_fasta_btn1:
    if st.button(
        "🚀 Generate FASTA File",
        disabled=st.session_state.fasta_status == "running",
    ):
        if not fasta_heavy_v and not fasta_heavy_cdr3_motif:
            st.warning(
                "⚠️ Please enter at least one search criterion (VH Gene or CDR3 Motif)"
            )
        elif not fasta_include_heavy and not fasta_include_light:
            st.warning(
                "⚠️ Please select at least one chain type (Heavy or Light)"
            )
        else:
            # Submit FASTA generation task
            future = executor.submit(
                prepare_fasta_download_background,
                heavy_databases,
                fasta_heavy_v,
                fasta_heavy_cdr3_motif,
                fasta_include_heavy,
                fasta_include_light,
            )
            st.session_state.fasta_future = future
            st.session_state.fasta_start_time = time.time()
            st.session_state.fasta_result = None
            st.session_state.fasta_status = "running"
            # Trigger immediate rerun to activate auto-refresh
            st.rerun()

with col_fasta_btn2:
    if st.button("🔄 Check FASTA Status", key="check_fasta"):
        old_status = st.session_state.fasta_status
        check_fasta_status()
        if st.session_state.fasta_status != old_status:
            st.rerun()

with col_fasta_btn3:
    if st.button(
        "🛑 Cancel FASTA",
        disabled=st.session_state.fasta_status != "running",
        key="cancel_fasta",
    ):
        if st.session_state.fasta_future is not None:
            st.session_state.fasta_future.cancel()
            st.session_state.fasta_future = None
            st.session_state.fasta_start_time = None
            st.session_state.fasta_status = "idle"
            st.warning("FASTA generation cancellation requested")

# Show FASTA download button when ready
if st.session_state.fasta_result is not None:
    fasta_result = st.session_state.fasta_result
    if fasta_result.get("success"):
        st.markdown("---")
        st.markdown("### 📥 Download FASTA File")

        col_info, col_download = st.columns([2, 1])
        with col_info:
            st.metric("Sequences", f"{fasta_result.get('sequence_count', 0):,}")
            file_size_mb = fasta_result.get("file_size_bytes", 0) / 1024 / 1024
            st.caption(f"File size: {file_size_mb:.2f} MB")
            st.caption(
                f"Filename: `{fasta_result.get('filename', 'unknown.fasta')}`"
            )

        with col_download:
            st.download_button(
                label="📥 Download FASTA",
                data=fasta_result.get("content", ""),
                file_name=fasta_result.get("filename", "sequences.fasta"),
                mime="text/plain",
                width="stretch",
                key="download_fasta_file",
            )

# Demo: Show that the UI is still interactive
# NOTE: Any interaction with these widgets will trigger a script rerun,
# which will quickly check the background task status (non-blocking)
st.markdown("---")
st.markdown("### 🎯 Interactive Demo")
st.markdown(
    "**Try interacting with these controls - each interaction will check the background task status!**"
)

user_input = st.text_input("Type something here:", key="demo_input")
if user_input:
    st.write(f"You typed: **{user_input}**")

slider_value = st.slider("Move this slider:", 0, 100, 50, key="demo_slider")
# Status check happens automatically on rerun (line 50)
st.write(f"Slider value: **{slider_value}**")

checkbox_state = st.checkbox("Check this box", key="demo_checkbox")
if checkbox_state:
    st.write("✅ Checkbox is checked!")
else:
    st.write("☐ Checkbox is unchecked")
