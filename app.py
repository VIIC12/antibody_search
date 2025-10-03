#!/usr/bin/env python
"""
ABDB V3.0 - Streamlit Web Interface

High-performance antibody database search using DuckDB.
"""

import sys
from pathlib import Path
import os
import streamlit as st
import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from search_engine import AntibodySearchEngine
import logging

logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="ABDB V3.0 - Antibody Database Search",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .stat-box {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    /* Style for invalid input fields */
    .invalid-input input {
        border: 2px solid #ff4b4b !important;
        background-color: #fff5f5 !important;
    }
</style>
""", unsafe_allow_html=True)


def init_search_engine(data_dir: str, progress_callback=None, db_path: str = ":memory:"):
    """Initialize the search engine for a specific database."""
    try:
        engine = AntibodySearchEngine(data_dir=data_dir, progress_callback=progress_callback, db_path=db_path)
        return engine
    except Exception as e:
        st.error(f"Failed to initialize search engine for {data_dir}: {e}")
        st.info("Please ensure the database directory exists and contains Parquet files.")
        st.stop()

def check_metadata_freshness(data_dir: str) -> bool:
    """Check if metadata.parquet is up-to-date with Parquet files."""
    try:
        from pathlib import Path
        import pyarrow.parquet as pq
        
        metadata_path = Path(data_dir) / 'metadata.parquet'
        if not metadata_path.exists():
            return False
        
        # Get metadata modification time
        metadata_mtime = metadata_path.stat().st_mtime
        
        # Get newest Parquet file modification time
        parquet_files = [f for f in Path(data_dir).glob('*.parquet') if f.name != 'metadata.parquet']
        if not parquet_files:
            return True  # No data files, metadata is "fresh"
        
        newest_parquet_mtime = max(f.stat().st_mtime for f in parquet_files)
        
        return metadata_mtime >= newest_parquet_mtime
    except Exception:
        return False


def validate_gene_input(gene_str: str, field_name: str = "") -> bool:
    """
    Validate gene input - only allow numbers, dashes, commas, pipes, and asterisks.
    
    Returns True if valid, False otherwise.
    """
    import re
    if not gene_str:
        return True
    
    # Only allow: digits, dash, comma, pipe, asterisk, whitespace
    pattern = re.compile(r'^[0-9\-,|\*\s]+$')
    
    return pattern.match(gene_str) is not None


def validate_motif_input(motif_str: str) -> bool:
    """
    Validate CDR3 motif input - only allow valid amino acids, dots, and asterisks.
    
    Returns True if valid, False otherwise.
    """
    import re
    if not motif_str:
        return True
    
    # Only allow: 20 standard amino acids, dot (.), asterisk (*)
    # Valid amino acids: A C D E F G H I K L M N P Q R S T V W Y
    pattern = re.compile(r'^[ACDEFGHIKLMNPQRSTVWY\.\*\s]+$', re.IGNORECASE)
    
    return pattern.match(motif_str) is not None


def main():
    # Header - ALWAYS visible
    st.markdown('<div class="main-header">🔬 ABDB V3.0</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">High-Performance Antibody Database Search</div>', unsafe_allow_html=True)
    
    available_databases = []
    # read ABHUNTER_DB_PATH from environment variable
    abhunter_db_path = os.getenv("ABHUNTER_DB_PATH")
    if abhunter_db_path:
        logger.debug(f"Adding ABHUNTER_DB_PATH: {abhunter_db_path} databases")
        for db in os.listdir(abhunter_db_path):
            available_databases.append(os.path.join(abhunter_db_path, db))
    
    
    # Filter to only show existing databases
    existing_databases = []
    for db in available_databases:
        if Path(db).exists() and any(Path(db).rglob("*.parquet")):
            existing_databases.append(db)
    
    if not existing_databases:
        st.error("No databases found! Please run the data conversion script first.")
        st.stop()
    
    # Database selector with info and reindex button - ALWAYS visible
    col1, col2, col3 = st.columns([2, 2, 1])
    database_labels = [Path(db).name for db in existing_databases]
    with col1:
        selected_label = st.selectbox(
            "🗄️ Database",
            database_labels,
            index=0,
            help="Choose which database to search"
        )
        # Map the selected label back to the actual database path
        selected_db = existing_databases[database_labels.index(selected_label)]
    with col2:
        # Show database info if loaded
        if 'search_engine' in st.session_state and st.session_state.get('current_db') == selected_db:
            engine = st.session_state['search_engine']
            st.metric("Total Sequences", f"{engine.total_sequences:,}")
    
    with col3:
        # Reindex button - always visible
        if 'search_engine' not in st.session_state or st.session_state.get('current_db') != selected_db:
            # Database not loaded - show load button
            parquet_files = list(Path(selected_db).glob('*.parquet'))
            if parquet_files:
                if check_metadata_freshness(selected_db):
                    # Auto-load if metadata is fresh
                    pass  # Will be handled in sidebar
                else:
                    # Show reindex button
                    if st.button("🚀 Reindex Database", type="primary", use_container_width=True):
                        st.session_state['reindex_requested'] = True
                        st.session_state['reindex_db'] = selected_db
                        st.rerun()
            else:
                st.button("No Data", disabled=True, use_container_width=True)
        else:
            # Database loaded - show reload button
            if not check_metadata_freshness(selected_db):
                # Metadata needs updating
                if st.button("🔄 Reindex Database", type="primary", use_container_width=True):
                    st.session_state['reindex_requested'] = True
                    st.session_state['reindex_db'] = selected_db
                    st.rerun()
            else:
                # Metadata is fresh
                if st.button("🔄 Reindex Database", help="Click after adding/removing files", use_container_width=True):
                    st.session_state['reindex_requested'] = True
                    st.session_state['reindex_db'] = selected_db
                    st.rerun()
    
    # Check if metadata needs updating
    metadata_fresh = check_metadata_freshness(selected_db)
    
    # Sidebar - simplified since reindex button is now in main area
    with st.sidebar:
        # Auto-load database if metadata is fresh and not loaded
        if 'search_engine' not in st.session_state or st.session_state.get('current_db') != selected_db:
            parquet_files = list(Path(selected_db).glob('*.parquet'))
            if parquet_files and metadata_fresh:
                with st.spinner("Loading database..."):
                    engine = init_search_engine(selected_db)
                    st.session_state['search_engine'] = engine
                    st.session_state['current_db'] = selected_db
                    # Clear cached search results when database changes
                    if 'last_search_results' in st.session_state:
                        del st.session_state['last_search_results']
                    if 'last_search_params' in st.session_state:
                        del st.session_state['last_search_params']
                st.rerun()
        
        # Show status messages
        if 'search_engine' not in st.session_state or st.session_state.get('current_db') != selected_db:
            parquet_files = list(Path(selected_db).glob('*.parquet'))
            if not parquet_files:
                st.error("No Parquet files found in this database.")
        elif not metadata_fresh:
            st.warning("🔄 Database files have been updated!")
        
        # Fixed About section - always in same position
        st.markdown("### ℹ️ About")
        st.markdown("""
        Search the [Observed Antibody Space (OAS)](https://opig.stats.ox.ac.uk/webapps/oas/) 
        database for specific antibody sequences.
        """)
        
        st.markdown("### 🔗 Resources")
        st.markdown("""
        - [OAS Database](https://opig.stats.ox.ac.uk/webapps/oas/)
        - [GitHub Repository](https://github.com/vicci/antibody_search)
        - [Documentation](#)
        """)
    
    # Handle reindex request with progress bar
    if st.session_state.get('reindex_requested', False):
        reindex_db = st.session_state.get('reindex_db', selected_db)
        
        # Create progress bar in main area
        st.markdown("### 🔄 Reindexing Database")
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def update_progress(progress, status):
            progress_bar.progress(progress)
            status_text.text(status)
        
        try:
            engine = init_search_engine(reindex_db, progress_callback=update_progress)
            st.session_state['search_engine'] = engine
            st.session_state['current_db'] = reindex_db
            # Clear cached search results when database is reindexed
            if 'last_search_results' in st.session_state:
                del st.session_state['last_search_results']
            if 'last_search_params' in st.session_state:
                del st.session_state['last_search_params']
            st.cache_resource.clear()
            st.success("✅ Database reindexed successfully!")
        except Exception as e:
            st.error(f"❌ Reindex failed: {e}")
        finally:
            # Clear progress indicators and reset state
            progress_bar.empty()
            status_text.empty()
            st.session_state['reindex_requested'] = False
            st.session_state['reindex_db'] = None
            # Refresh the page to re-evaluate metadata freshness
            st.rerun()
    
    # Only show search form if database is loaded and not reindexing
    if st.session_state.get('reindex_requested', False):
        # Show reindexing message instead of search form
        st.info("🔄 Database is being reindexed. Please wait...")
        return
    elif 'search_engine' not in st.session_state or st.session_state.get('current_db') != selected_db:
        st.error("Please reindex the database first using the 'Reindex Database' button.")
        return
    
    engine = st.session_state['search_engine']
    
    # Show warning if metadata needs updating
    if not metadata_fresh:
        st.warning("🔄 **Database files have been updated!** Please click 'Reindex Database' to refresh the metadata and see the latest data.")
    
    # Search form
    st.markdown("## 🔍 Search Criteria")
    
    with st.form("search_form"):
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            ighv_valid = True
            ighv = st.text_input(
                "IGHV Gene",
                placeholder="e.g., 3,4 or 3-23",
                help="Single: 3 or 3-23 | Multiple: 3,4 or 3-20,3-22",
                key="ighv_input"
            )
            if ighv and not validate_gene_input(ighv):
                st.markdown(":red[❌ Only: numbers, **-** , **|** **\\***]")
                ighv_valid = False
    
        with col2:
            ighd_valid = True
            ighd = st.text_input(
                "IGHD Gene",
                placeholder="e.g., 2,3 or 2-21",
                help="Single: 2 or 2-21 | Multiple: 2,3 or 2-15,2-18",
                key="ighd_input"
            )
            if ighd and not validate_gene_input(ighd):
                st.markdown(":red[❌ Only: numbers, **-** , **|** **\\***]")
                ighd_valid = False
        
        with col3:
            ighj_valid = True
            ighj = st.text_input(
                "IGHJ Gene",
                placeholder="e.g., 4,5 or J4",
                help="Single: 4 or J4 | Multiple: 4,5 or 4,5",
                key="ighj_input"
            )
            if ighj and not validate_gene_input(ighj):
                st.markdown(":red[❌ Only: numbers, **-** , **|** **\\***]")
                ighj_valid = False
    
        # CDR section - all CDR-related fields grouped together
        st.markdown("#### CDR Region Filters")
        
        # CDR Length fields
        st.markdown("##### CDR Lengths (amino acids)")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            cdr1_length = st.number_input(
                "CDRH1 Length",
                min_value=0,
                max_value=100,
                value=None,
                step=1,
                help="Length of CDRH1 region (amino acids)",
                placeholder="Optional",
                key="cdr1_length_input"
            )
        
        with col2:
            cdr2_length = st.number_input(
                "CDRH2 Length",
                min_value=0,
                max_value=100,
                value=None,
                step=1,
                help="Length of CDRH2 region (amino acids)",
                placeholder="Optional",
                key="cdr2_length_input"
            )
        
        with col3:
            cdr3_length = st.number_input(
                "CDRH3 Length",
                min_value=0,
                max_value=100,
                value=None,
                step=1,
                help="Length of CDRH3 region (amino acids)",
                placeholder="Optional",
                key="cdr3_length_input"
            )
    
        # CDR Motif fields
        st.markdown("##### CDR Sequence Motifs")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            cdr1_motif_valid = True
            cdr1_motif = st.text_input(
                "CDRH1 Sequence Motif",
                placeholder="e.g., *TT or YY.D.*G",
                help='"." for one character, "*" for 0-many characters. Valid amino acids: ACDEFGHIKLMNPQRSTVWY',
                key="cdr1_motif_input"
            )
            if cdr1_motif and not validate_motif_input(cdr1_motif):
                st.markdown(":red[❌ Only: amino acids (ACDEFGHIKLMNPQRSTVWY), **.** and **\\***]")
                cdr1_motif_valid = False
        
        with col2:
            cdr2_motif_valid = True
            cdr2_motif = st.text_input(
                "CDRH2 Sequence Motif",
                placeholder="e.g., *TT or YY.D.*G",
                help='"." for one character, "*" for 0-many characters. Valid amino acids: ACDEFGHIKLMNPQRSTVWY',
                key="cdr2_motif_input"
            )
            if cdr2_motif and not validate_motif_input(cdr2_motif):
                st.markdown(":red[❌ Only: amino acids (ACDEFGHIKLMNPQRSTVWY), **.** and **\\***]")
                cdr2_motif_valid = False
        
        with col3:
            cdr3_motif_valid = True
            cdr3_motif = st.text_input(
                "CDRH3 Sequence Motif",
                placeholder="e.g., *TT or YY.D.*G",
                help='"." for one character, "*" for 0-many characters. Valid amino acids: ACDEFGHIKLMNPQRSTVWY',
                key="cdr3_motif_input"
            )
            if cdr3_motif and not validate_motif_input(cdr3_motif):
                st.markdown(":red[❌ Only: amino acids (ACDEFGHIKLMNPQRSTVWY), **.** and **\\***]")
                cdr3_motif_valid = False
    
        # Fixed sample limit for display
        sample_limit = 100
        
        # Form submit button
        search_submitted = st.form_submit_button(
            "🔍 Search Database", 
            type="primary",
            use_container_width=False
        )
    
    # Track current search parameters (outside form)
    current_params = {
        'ighv': ighv,
        'ighd': ighd, 
        'ighj': ighj,
        'cdr1_length': cdr1_length,
        'cdr2_length': cdr2_length,
        'cdr3_length': cdr3_length,
        'cdr1_motif': cdr1_motif,
        'cdr2_motif': cdr2_motif,
        'cdr3_motif': cdr3_motif
    }
    
    # Check if parameters have changed since last search
    last_params = st.session_state.get('last_search_params', {})
    params_changed = current_params != last_params
    
    # Show message if no changes detected (but still allow form submission)
    if not params_changed and 'last_search_results' in st.session_state:
        st.info("💡 No changes detected since last search. You can still search to refresh results.")
    
    # Display cached results if form not submitted
    if not search_submitted and 'last_search_results' in st.session_state:
        cached_results = st.session_state['last_search_results']
        sequences_sample_df = cached_results['sequences_sample_df']
        statistics = cached_results['statistics']
        stats_df = cached_results['stats_df']
        
        # Display cached results
        st.markdown("---")
        st.markdown("## 📊 Search Results (Cached)")
        
        # Statistics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Hits", f"{statistics['total_hits']:,}")
        
        with col2:
            st.metric("Database Size", f"{statistics['total_sequences']:,}")
        
        with col3:
            st.metric("Hit Percentage", f"{statistics['percentage']}%")
        
        with col4:
            st.metric("Search Time", f"{statistics['search_time']}s")
        
        # Section 1: Statistics by Subject
        st.markdown("### 📊 Statistics by Subject")
        
        if not stats_df.empty:
            # Display statistics table
            st.dataframe(
                stats_df,
                use_container_width=True,
                height=300
            )
            
            # Download statistics
            col1, col2 = st.columns(2)
            with col1:
                csv_stats = stats_df.to_csv(index=False)
                st.download_button(
                    label="📊 Download Statistics (CSV)",
                    data=csv_stats,
                    file_name=f"abdb_stats_{ighv}_{ighd}_{ighj}.csv",
                    mime="text/csv",
                    width='stretch'
                )
        
        # Section 2: Sample Sequences
        st.markdown(f"### 🔬 Sample Sequences (showing {len(sequences_sample_df)} of {statistics['total_hits']:,} total hits)")
        
        if not sequences_sample_df.empty:
            # Display only sequence data fields, exclude metadata/statistics columns
            exclude_cols = {
                'file_source', 'filename', 'rows', 'unique_sequences', 
                'total_sequences', 'source_file', 'filepath', 'file_size_mb'
            }
            display_cols = [col for col in sequences_sample_df.columns if col not in exclude_cols]
            sequences_display = sequences_sample_df[display_cols].copy()
            
            column_rename = {
                'v_call': 'v_gen',
                'd_call': 'd_gen', 
                'j_call': 'j_gen'
            }
            sequences_display = sequences_display.rename(columns=column_rename)
            
            st.dataframe(
                sequences_display,
                use_container_width=True,
                height=400
            )
            
            # Download section
            st.markdown("### 📥 Download Results")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Download sample sequences (CSV)
                csv_sample = sequences_display.to_csv(index=False)
                st.download_button(
                    label=f"📋 Download Sample Sequences (CSV, {len(sequences_display)} rows)",
                    data=csv_sample,
                    file_name=f"abdb_sample_{ighv}_{ighd}_{ighj}.csv",
                    mime="text/csv",
                    width='stretch'
                )
            
            with col2:
                # Download ALL matching sequences (complete dataset)
                if not sequences_sample_df.empty:
                    # Check if user wants to download full dataset
                    if st.button(f"🔬 Download ALL Sequences (Parquet + ZIP, {statistics['total_hits']:,} rows)", 
                               type="primary", width='stretch'):
                        with st.spinner(f"Loading {statistics['total_hits']:,} sequences for download..."):
                            try:
                                # Load full dataset on demand
                                sequences_full_df, _ = engine.search(
                                    ighv=ighv,
                                    ighd=ighd,
                                    ighj=ighj if ighj else "",
                                    cdr1_length=cdr1_length if cdr1_length and cdr1_length > 0 else None,
                                    cdr2_length=cdr2_length if cdr2_length and cdr2_length > 0 else None,
                                    cdr3_length=cdr3_length if cdr3_length and cdr3_length > 0 else None,
                                    cdr1_motif=cdr1_motif,
                                    cdr2_motif=cdr2_motif,
                                    cdr3_motif=cdr3_motif,
                                    full_results=True,
                                    limit=None  # No limit - get everything
                                )
                                
                                # Prepare download data with renamed columns, exclude metadata/statistics
                                exclude_cols = {
                                    'file_source', 'filename', 'rows', 'unique_sequences', 
                                    'total_sequences', 'source_file', 'filepath', 'file_size_mb'
                                }
                                download_cols = [col for col in sequences_full_df.columns if col not in exclude_cols]
                                download_data = sequences_full_df[download_cols].copy()
                                column_rename = {
                                    'v_call': 'v_gen',
                                    'd_call': 'd_gen', 
                                    'j_call': 'j_gen'
                                }
                                download_data = download_data.rename(columns=column_rename)
                                
                                # Save as Parquet
                                import io
                                import zipfile
                                import pyarrow as pa
                                import pyarrow.parquet as pq
                                
                                # Create Parquet file in memory
                                parquet_buffer = io.BytesIO()
                                table = pa.Table.from_pandas(download_data)
                                pq.write_table(table, parquet_buffer)
                                parquet_data = parquet_buffer.getvalue()
                                
                                # Create ZIP file with Parquet inside
                                zip_buffer = io.BytesIO()
                                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                                    zip_file.writestr(f"abdb_sequences_{ighv}_{ighd}_{ighj}.parquet", parquet_data)
                                
                                zip_data = zip_buffer.getvalue()
                                
                                # Download button
                                st.download_button(
                                    label=f"📦 Download ZIP File ({len(zip_data) / 1024 / 1024:.1f} MB)",
                                    data=zip_data,
                                    file_name=f"abdb_sequences_{ighv}_{ighd}_{ighj}.zip",
                                    mime="application/zip",
                                    width='stretch'
                                )
                                
                            except Exception as e:
                                st.error(f"Failed to prepare download: {e}")
                    else:
                        st.info(f"Click above to download all {statistics['total_hits']:,} sequences as Parquet + ZIP")
                else:
                    st.button("No sequences to download", disabled=True, width='stretch')
        else:
            st.info("No sequences found matching the search criteria.")
    
    if search_submitted:
        # Check if any validation failed
        if not all([ighv_valid, ighd_valid, ighj_valid, cdr1_motif_valid, cdr2_motif_valid, cdr3_motif_valid]):
            st.error("❌ Please fix the invalid inputs (marked in red) before searching")
            return
        
        # Validate at least one criterion provided
        if not any([ighv, ighd, ighj, cdr1_length, cdr2_length, cdr3_length, cdr1_motif, cdr2_motif, cdr3_motif]):
            st.warning("⚠️ Please enter at least one search criterion")
            return
        
        # Perform search
        with st.spinner("Searching database..."):
            try:
                # Single search to get both statistics and sample sequences
                sequences_sample_df, statistics = engine.search(
                    ighv=ighv,
                    ighd=ighd,
                    ighj=ighj if ighj else "",
                    cdr1_length=cdr1_length if cdr1_length and cdr1_length > 0 else None,
                    cdr2_length=cdr2_length if cdr2_length and cdr2_length > 0 else None,
                    cdr3_length=cdr3_length if cdr3_length and cdr3_length > 0 else None,
                    cdr1_motif=cdr1_motif,
                    cdr2_motif=cdr2_motif,
                    cdr3_motif=cdr3_motif,
                    full_results=True,
                    limit=sample_limit
                )
                
                # Get statistics separately (fast)
                stats_df, _ = engine.search(
                    ighv=ighv,
                    ighd=ighd,
                    ighj=ighj if ighj else "",
                    cdr1_length=cdr1_length if cdr1_length and cdr1_length > 0 else None,
                    cdr2_length=cdr2_length if cdr2_length and cdr2_length > 0 else None,
                    cdr3_length=cdr3_length if cdr3_length and cdr3_length > 0 else None,
                    cdr1_motif=cdr1_motif,
                    cdr2_motif=cdr2_motif,
                    cdr3_motif=cdr3_motif,
                    full_results=False
                )
                
                # For download, we'll load full data only when needed
                sequences_full_df = None  # Will be loaded on demand
                
                # Store search parameters and results in session state
                st.session_state['last_search_params'] = current_params
                st.session_state['last_search_results'] = {
                    'sequences_sample_df': sequences_sample_df,
                    'statistics': statistics,
                    'stats_df': stats_df
                }
                
                # Display results
                st.markdown("---")
                st.markdown("## 📊 Search Results")
                
                
                # Statistics
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Total Hits", f"{statistics['total_hits']:,}")
                
                with col2:
                    st.metric("Database Size", f"{statistics['total_sequences']:,}")
                
                with col3:
                    st.metric("Hit Percentage", f"{statistics['percentage']}%")
                
                with col4:
                    st.metric("Search Time", f"{statistics['search_time']}s")
                
                # Section 1: Statistics by Subject
                st.markdown("### 📊 Statistics by Subject")
                
                if not stats_df.empty:
                    st.dataframe(
                        stats_df,
                        use_container_width=True,
                        height=300
                    )
                else:
                    st.info("No results found matching your criteria.")
                    return
                
                # Section 2: Sample Sequences
                st.markdown(f"### 🔬 Sample Sequences (showing {len(sequences_sample_df)} of {statistics['total_hits']:,} total hits)")
                
                if not sequences_sample_df.empty:
                    # Display only sequence data fields, exclude metadata/statistics columns
                    exclude_cols = {
                        'file_source', 'filename', 'rows', 'unique_sequences', 
                        'total_sequences', 'source_file', 'filepath', 'file_size_mb'
                    }
                    display_cols = [col for col in sequences_sample_df.columns if col not in exclude_cols]
                    sequences_display = sequences_sample_df[display_cols].copy()
                    
                    # Rename gene columns for display
                    column_rename = {
                        'v_call': 'v_gen',
                        'd_call': 'd_gen', 
                        'j_call': 'j_gen'
                    }
                    sequences_display = sequences_display.rename(columns=column_rename)
                    
                    st.dataframe(
                        sequences_display,
                        use_container_width=True,
                        height=400
                    )
                else:
                    st.info("No sequence data available.")
                
                # Download buttons
                st.markdown("### 📥 Download Results")
                
                # Warning for very large result sets
                if statistics['total_hits'] > 100000:
                    st.warning(f"⚠️ Large result set ({statistics['total_hits']:,} hits). CSV download may take time and be very large.")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    # Download statistics
                    stats_csv = stats_df.to_csv(index=False)
                    st.download_button(
                        label="📊 Download Statistics (CSV)",
                        data=stats_csv,
                        file_name=f"abdb_stats_{ighv}_{ighd}_{ighj}.csv",
                        mime="text/csv",
                        width='stretch'
                    )
                
                with col2:
                    # Download ALL matching sequences (complete dataset)
                    if not sequences_sample_df.empty:
                        # Check if user wants to download full dataset
                        if st.button(f"🔬 Download ALL Sequences (Parquet + ZIP, {statistics['total_hits']:,} rows)", 
                                   type="primary", width='stretch'):
                            with st.spinner(f"Loading {statistics['total_hits']:,} sequences for download..."):
                                try:
                                    # Load full dataset on demand
                                    sequences_full_df, _ = engine.search(
                                        ighv=ighv,
                                        ighd=ighd,
                                        ighj=ighj if ighj else "",
                                        cdr1_length=cdr1_length if cdr1_length and cdr1_length > 0 else None,
                                        cdr2_length=cdr2_length if cdr2_length and cdr2_length > 0 else None,
                                        cdr3_length=cdr3_length if cdr3_length and cdr3_length > 0 else None,
                                        cdr1_motif=cdr1_motif,
                                        cdr2_motif=cdr2_motif,
                                        cdr3_motif=cdr3_motif,
                                        full_results=True,
                                        limit=None  # No limit - get everything
                                    )
                                    
                                    # Prepare download data with renamed columns, exclude metadata/statistics
                                    exclude_cols = {
                                        'file_source', 'filename', 'rows', 'unique_sequences', 
                                        'total_sequences', 'source_file', 'filepath', 'file_size_mb'
                                    }
                                    download_cols = [col for col in sequences_full_df.columns if col not in exclude_cols]
                                    download_data = sequences_full_df[download_cols].copy()
                                    column_rename = {
                                        'v_call': 'v_gen',
                                        'd_call': 'd_gen', 
                                        'j_call': 'j_gen'
                                    }
                                    download_data = download_data.rename(columns=column_rename)
                                    
                                    # Save as Parquet
                                    import io
                                    import zipfile
                                    import pyarrow as pa
                                    import pyarrow.parquet as pq
                                    
                                    # Create Parquet file in memory
                                    parquet_buffer = io.BytesIO()
                                    table = pa.Table.from_pandas(download_data)
                                    pq.write_table(table, parquet_buffer)
                                    parquet_data = parquet_buffer.getvalue()
                                    
                                    # Create ZIP file with Parquet inside
                                    zip_buffer = io.BytesIO()
                                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                                        zip_file.writestr(f"abdb_sequences_{ighv}_{ighd}_{ighj}.parquet", parquet_data)
                                    
                                    zip_data = zip_buffer.getvalue()
                                    
                                    # Download button
                                    st.download_button(
                                        label=f"📦 Download ZIP File ({len(zip_data) / 1024 / 1024:.1f} MB)",
                                        data=zip_data,
                                        file_name=f"abdb_sequences_{ighv}_{ighd}_{ighj}.zip",
                                        mime="application/zip",
                                        width='stretch'
                                    )
                                    
                                except Exception as e:
                                    st.error(f"Failed to prepare download: {e}")
                        else:
                            st.info(f"Click above to download all {statistics['total_hits']:,} sequences as Parquet + ZIP")
                    else:
                        st.button("No sequences to download", disabled=True, width='stretch')
                
                # Search parameters
                with st.expander("🔍 Search Parameters"):
                    st.json(statistics['query_params'])
                
            except Exception as e:
                st.error(f"Search failed: {e}")
                st.exception(e)
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #666; padding: 2rem;'>
        <p>ABDB V3.0 - Antibody Database Search Tool</p>
        <p>© 2024 Tom U. Schlegel | GNU GPLv3 License</p>
        <p>Data from <a href='https://opig.stats.ox.ac.uk/webapps/oas/'>Observed Antibody Space (OAS)</a></p>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()

