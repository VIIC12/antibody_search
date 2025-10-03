#!/usr/bin/env python
"""
ABDB V3.0 - Streamlit Web Interface

High-performance antibody database search using DuckDB.
"""

import os
import sys
from pathlib import Path
import os
from typing import Dict, Any
import streamlit as st

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from search_engine import AntibodySearchEngine
import logging

logger = logging.getLogger(__name__)

# Environment detection
def is_production():
    """Check if running in production environment."""
    return os.getenv('STREAMLIT_ENV') == 'production'

# Page configuration
st.set_page_config(
    page_title="ABDB V3.0 - Antibody Database Search",
    page_icon=':dna:',
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://github.com/VIIC12/antibody_search',
        'Report a bug': 'https://github.com/VIIC12/antibody_search/issues',
        'About': "ABHunter - High-performance OAS antibody database search"
    }
)


def init_search_engine(data_dir: str, progress_callback=None, db_path: str = ":memory:"):
    try:
        engine = AntibodySearchEngine(data_dir=data_dir, progress_callback=progress_callback, db_path=db_path)
        return engine
    except Exception as e:
        st.error(f"Failed to initialize search engine for {data_dir}: {e}")
        st.info("Please ensure the database directory exists and contains Parquet files.")
        st.stop()

@st.cache_data(ttl="5m")  # Cache for 5 minutes using string format
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
    
@st.cache_data(ttl="10m")  # Cache database discovery for 10 minutes
def get_available_databases():
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
    
    return existing_databases

def get_database_schema(data_dir: str) -> Dict[str, Any]:
    """Get database schema information."""
    try:
        # Initialize search engine to get schema (without progress callback for speed)
        engine = AntibodySearchEngine(data_dir=data_dir)
        return engine.schema
    except Exception as e:
        return {'search_type': 'unknown', 'error': str(e)}

def create_unpaired_search_form() -> Dict[str, Any]:
    """Create search form for unpaired data (current implementation)."""
    st.markdown("#### 🧬 Antibody Gene Search")
    
    # Gene fields
    col1, col2, col3 = st.columns(3)
    
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
            placeholder="e.g., 2-21 or 2",
            help="Single: 2 or 2-21 | Multiple: 2,3 or 2-15,2-21",
            key="ighd_input"
        )
        if ighd and not validate_gene_input(ighd):
            st.markdown(":red[❌ Only: numbers, **-** , **|** **\\***]")
            ighd_valid = False
    
    with col3:
        ighj_valid = True
        ighj = st.text_input(
            "IGHJ Gene",
            placeholder="e.g., 4 or J4",
            help="Single: 4 or J4 | Multiple: 4,5 or J4,J5",
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
            min_value=0, max_value=100, value=None, step=1,
            help="Length of CDRH1 region (amino acids)",
            placeholder="Optional", key="cdr1_length_input"
        )
    
    with col2:
        cdr2_length = st.number_input(
            "CDRH2 Length",
            min_value=0, max_value=100, value=None, step=1,
            help="Length of CDRH2 region (amino acids)",
            placeholder="Optional", key="cdr2_length_input"
        )
    
    with col3:
        cdr3_length = st.number_input(
            "CDRH3 Length",
            min_value=0, max_value=100, value=None, step=1,
            help="Length of CDRH3 region (amino acids)",
            placeholder="Optional", key="cdr3_length_input"
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
    
    return {
        'ighv': ighv, 'ighd': ighd, 'ighj': ighj,
        'cdr1_length': cdr1_length, 'cdr2_length': cdr2_length, 'cdr3_length': cdr3_length,
        'cdr1_motif': cdr1_motif, 'cdr2_motif': cdr2_motif, 'cdr3_motif': cdr3_motif,
        'valid': all([ighv_valid, ighd_valid, ighj_valid, cdr1_motif_valid, cdr2_motif_valid, cdr3_motif_valid])
    }

def create_paired_search_form() -> Dict[str, Any]:
    """Create search form for paired data with separate heavy and light chain fields."""
    # Heavy Chain Section
    st.markdown("#### 🧬 Heavy Chain")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        heavy_v_valid = True
        heavy_v = st.text_input(
            "IGHV Gene",
            placeholder="e.g., 3,4 or 3-23",
            help="Single: 3 or 3-23 | Multiple: 3,4 or 3-20,3-22",
            key="heavy_v_input"
        )
        if heavy_v and not validate_gene_input(heavy_v):
            st.markdown(":red[❌ Only: numbers, **-** , **|** **\\***]")
            heavy_v_valid = False
    
    with col2:
        heavy_d_valid = True
        heavy_d = st.text_input(
            "IGHD Gene",
            placeholder="e.g., 2-21 or 2",
            help="Single: 2 or 2-21 | Multiple: 2,3 or 2-15,2-21",
            key="heavy_d_input"
        )
        if heavy_d and not validate_gene_input(heavy_d):
            st.markdown(":red[❌ Only: numbers, **-** , **|** **\\***]")
            heavy_d_valid = False
    
    with col3:
        heavy_j_valid = True
        heavy_j = st.text_input(
            "IGHJ Gene",
            placeholder="e.g., 4 or J4",
            help="Single: 4 or J4 | Multiple: 4,5 or J4,J5",
            key="heavy_j_input"
        )
        if heavy_j and not validate_gene_input(heavy_j):
            st.markdown(":red[❌ Only: numbers, **-** , **|** **\\***]")
            heavy_j_valid = False
    
    # Heavy Chain CDR Lengths
    st.markdown("##### Heavy Chain CDR Lengths (amino acids)")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        heavy_cdr1_length = st.number_input(
            "CDRH1 Length",
            min_value=0, max_value=100, value=None, step=1,
            help="Length of CDRH1 region (amino acids)",
            placeholder="Optional", key="heavy_cdr1_length_input"
        )
    
    with col2:
        heavy_cdr2_length = st.number_input(
            "CDRH2 Length",
            min_value=0, max_value=100, value=None, step=1,
            help="Length of CDRH2 region (amino acids)",
            placeholder="Optional", key="heavy_cdr2_length_input"
        )
    
    with col3:
        heavy_cdr3_length = st.number_input(
            "CDRH3 Length",
            min_value=0, max_value=100, value=None, step=1,
            help="Length of CDRH3 region (amino acids)",
            placeholder="Optional", key="heavy_cdr3_length_input"
        )
    
    # Heavy Chain CDR Motifs
    st.markdown("##### Heavy Chain CDR Sequence Motifs")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        heavy_cdr1_motif_valid = True
        heavy_cdr1_motif = st.text_input(
            "CDRH1 Sequence Motif",
            placeholder="e.g., *TT or YY.D.*G",
            help='"." for one character, "*" for 0-many characters. Valid amino acids: ACDEFGHIKLMNPQRSTVWY',
            key="heavy_cdr1_motif_input"
        )
        if heavy_cdr1_motif and not validate_motif_input(heavy_cdr1_motif):
            st.markdown(":red[❌ Only: amino acids (ACDEFGHIKLMNPQRSTVWY), **.** and **\\***]")
            heavy_cdr1_motif_valid = False
    
    with col2:
        heavy_cdr2_motif_valid = True
        heavy_cdr2_motif = st.text_input(
            "CDRH2 Sequence Motif",
            placeholder="e.g., *TT or YY.D.*G",
            help='"." for one character, "*" for 0-many characters. Valid amino acids: ACDEFGHIKLMNPQRSTVWY',
            key="heavy_cdr2_motif_input"
        )
        if heavy_cdr2_motif and not validate_motif_input(heavy_cdr2_motif):
            st.markdown(":red[❌ Only: amino acids (ACDEFGHIKLMNPQRSTVWY), **.** and **\\***]")
            heavy_cdr2_motif_valid = False
    
    with col3:
        heavy_cdr3_motif_valid = True
        heavy_cdr3_motif = st.text_input(
            "CDRH3 Sequence Motif",
            placeholder="e.g., *TT or YY.D.*G",
            help='"." for one character, "*" for 0-many characters. Valid amino acids: ACDEFGHIKLMNPQRSTVWY',
            key="heavy_cdr3_motif_input"
        )
        if heavy_cdr3_motif and not validate_motif_input(heavy_cdr3_motif):
            st.markdown(":red[❌ Only: amino acids (ACDEFGHIKLMNPQRSTVWY), **.** and **\\***]")
            heavy_cdr3_motif_valid = False
    
    # Light Chain Section
    st.markdown("#### 🔬 Light Chain")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        light_v_valid = True
        light_v = st.text_input(
            "IGLV Gene",
            placeholder="e.g., 1-2 or 1",
            help="Single: 1 or 1-2 | Multiple: 1,2 or 1-2,1-3",
            key="light_v_input"
        )
        if light_v and not validate_gene_input(light_v):
            st.markdown(":red[❌ Only: numbers, **-** , **|** **\\***]")
            light_v_valid = False
    
    with col2:
        light_d_valid = True
        light_d = st.text_input(
            "IGLD Gene",
            placeholder="e.g., 1 or 1-1",
            help="Single: 1 or 1-1 | Multiple: 1,2 or 1-1,1-2",
            key="light_d_input"
        )
        if light_d and not validate_gene_input(light_d):
            st.markdown(":red[❌ Only: numbers, **-** , **|** **\\***]")
            light_d_valid = False
    
    with col3:
        light_j_valid = True
        light_j = st.text_input(
            "IGLJ Gene",
            placeholder="e.g., 2 or J2",
            help="Single: 2 or J2 | Multiple: 2,3 or J2,J3",
            key="light_j_input"
        )
        if light_j and not validate_gene_input(light_j):
            st.markdown(":red[❌ Only: numbers, **-** , **|** **\\***]")
            light_j_valid = False
    
    # Light Chain CDR Lengths
    st.markdown("##### Light Chain CDR Lengths (amino acids)")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        light_cdr1_length = st.number_input(
            "CDRL1 Length",
            min_value=0, max_value=100, value=None, step=1,
            help="Length of CDRL1 region (amino acids)",
            placeholder="Optional", key="light_cdr1_length_input"
        )
    
    with col2:
        light_cdr2_length = st.number_input(
            "CDRL2 Length",
            min_value=0, max_value=100, value=None, step=1,
            help="Length of CDRL2 region (amino acids)",
            placeholder="Optional", key="light_cdr2_length_input"
        )
    
    with col3:
        light_cdr3_length = st.number_input(
            "CDRL3 Length",
            min_value=0, max_value=100, value=None, step=1,
            help="Length of CDRL3 region (amino acids)",
            placeholder="Optional", key="light_cdr3_length_input"
        )
    
    # Light Chain CDR Motifs
    st.markdown("##### Light Chain CDR Sequence Motifs")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        light_cdr1_motif_valid = True
        light_cdr1_motif = st.text_input(
            "CDRL1 Sequence Motif",
            placeholder="e.g., *TT or YY.D.*G",
            help='"." for one character, "*" for 0-many characters. Valid amino acids: ACDEFGHIKLMNPQRSTVWY',
            key="light_cdr1_motif_input"
        )
        if light_cdr1_motif and not validate_motif_input(light_cdr1_motif):
            st.markdown(":red[❌ Only: amino acids (ACDEFGHIKLMNPQRSTVWY), **.** and **\\***]")
            light_cdr1_motif_valid = False
    
    with col2:
        light_cdr2_motif_valid = True
        light_cdr2_motif = st.text_input(
            "CDRL2 Sequence Motif",
            placeholder="e.g., *TT or YY.D.*G",
            help='"." for one character, "*" for 0-many characters. Valid amino acids: ACDEFGHIKLMNPQRSTVWY',
            key="light_cdr2_motif_input"
        )
        if light_cdr2_motif and not validate_motif_input(light_cdr2_motif):
            st.markdown(":red[❌ Only: amino acids (ACDEFGHIKLMNPQRSTVWY), **.** and **\\***]")
            light_cdr2_motif_valid = False
    
    with col3:
        light_cdr3_motif_valid = True
        light_cdr3_motif = st.text_input(
            "CDRL3 Sequence Motif",
            placeholder="e.g., *TT or YY.D.*G",
            help='"." for one character, "*" for 0-many characters. Valid amino acids: ACDEFGHIKLMNPQRSTVWY',
            key="light_cdr3_motif_input"
        )
        if light_cdr3_motif and not validate_motif_input(light_cdr3_motif):
            st.markdown(":red[❌ Only: amino acids (ACDEFGHIKLMNPQRSTVWY), **.** and **\\***]")
            light_cdr3_motif_valid = False
    
    return {
        # Heavy chain parameters
        'heavy_v': heavy_v, 'heavy_d': heavy_d, 'heavy_j': heavy_j,
        'heavy_cdr1_length': heavy_cdr1_length, 'heavy_cdr2_length': heavy_cdr2_length, 'heavy_cdr3_length': heavy_cdr3_length,
        'heavy_cdr1_motif': heavy_cdr1_motif, 'heavy_cdr2_motif': heavy_cdr2_motif, 'heavy_cdr3_motif': heavy_cdr3_motif,
        # Light chain parameters
        'light_v': light_v, 'light_d': light_d, 'light_j': light_j,
        'light_cdr1_length': light_cdr1_length, 'light_cdr2_length': light_cdr2_length, 'light_cdr3_length': light_cdr3_length,
        'light_cdr1_motif': light_cdr1_motif, 'light_cdr2_motif': light_cdr2_motif, 'light_cdr3_motif': light_cdr3_motif,
        # Validation
        'valid': all([heavy_v_valid, heavy_d_valid, heavy_j_valid, heavy_cdr1_motif_valid, heavy_cdr2_motif_valid, heavy_cdr3_motif_valid,
                     light_v_valid, light_d_valid, light_j_valid, light_cdr1_motif_valid, light_cdr2_motif_valid, light_cdr3_motif_valid])
    }

def display_search_results(sequences_sample_df, statistics, stats_df, sequences_full_df=None):
    """Display search results in a reusable function."""
    if sequences_sample_df.empty:
        st.info("No sequences found matching your criteria.")
        return
    
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
            height=300,
            column_config={
                "subject": st.column_config.TextColumn("Subject", width="medium"),
                "hits": st.column_config.NumberColumn("Hits", width="small"),
                "total_sequences": st.column_config.NumberColumn("Total Sequences", width="medium"),
                "hit_percentage": st.column_config.NumberColumn("Hit %", width="small", format="%.2f%%"),
                "hits_per_million": st.column_config.NumberColumn("Hits/Million", width="medium", format="%.1f")
            }
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
            height=400,
            column_config={
                "v_gen": st.column_config.TextColumn("V Gene", width="medium"),
                "d_gen": st.column_config.TextColumn("D Gene", width="medium"),
                "j_gen": st.column_config.TextColumn("J Gene", width="medium"),
                "cdr1_aa": st.column_config.TextColumn("CDRH1", width="large"),
                "cdr2_aa": st.column_config.TextColumn("CDRH2", width="large"),
                "cdr3_aa": st.column_config.TextColumn("CDRH3", width="large"),
                "cdr1_length": st.column_config.NumberColumn("CDRH1 Len", width="small"),
                "cdr2_length": st.column_config.NumberColumn("CDRH2 Len", width="small"),
                "cdr3_length": st.column_config.NumberColumn("CDRH3 Len", width="small"),
                "subject": st.column_config.TextColumn("Subject", width="medium")
            }
        )
    else:
        st.info("No sequence data available.")
    
    # Download buttons
    st.markdown("### 📥 Download Results")
    col1, col2 = st.columns(2)
    
    with col1:
        # Download sample sequences as CSV
        if not sequences_sample_df.empty:
            csv_data = sequences_sample_df.to_csv(index=False)
            st.download_button(
                label=f"📄 Download Sample Sequences (CSV, {len(sequences_sample_df)} rows)",
                data=csv_data,
                file_name=f"abdb_sample_sequences_{statistics['total_hits']}.csv",
                mime="text/csv",
                width='stretch'
            )
        else:
            st.button("No sequences to download", disabled=True, width='stretch')
    
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

def main():
    st.markdown("# :blue[🔬 AntibodyHunter]")
    st.markdown("#### :grey[High-Performance Antibody Database Search]")

    # Get available databases with caching
    existing_databases = get_available_databases()
    
    if not existing_databases:
        st.error("No databases found! Please run the data conversion script first.")
        st.stop()
    
    # Database selector with info and reindex button - ALWAYS visible
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
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
    
    with col4:
        # Reindex button - only visible in development
        if not is_production():
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
        else:
            # Production mode - show status only
            if 'search_engine' in st.session_state and st.session_state.get('current_db') == selected_db:
                st.success("✅ Database Ready")
            else:
                st.info("🔄 Loading...")
    
    # Check if metadata needs updating
    metadata_fresh = check_metadata_freshness(selected_db)
    
    # Sidebar
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
        

        # Show environment indicator
        st.markdown("""### Environment""")
        if is_production():
            st.success("🚀 **Production Mode**")
            st.caption("Database is read-only.")
        else:
            st.info("🛠️ **Development Mode**")
            st.caption("Full database control available.")

        # About section
        st.markdown("""
        ### About
        Search the [Observed Antibody Space (OAS)](https://opig.stats.ox.ac.uk/webapps/oas/) 
        database for specific antibody sequences.

        ### How to Use
        Select the the desired database from the dropdown menu, enter the search criteria, and click the "🔍 Search Database" button. The results will be displayed in the main area and can be downloaded as zipped parquet files.

        ### Resources
        - [GitHub Repository](#)
        - [Documentation API](#)
        """)
        
        
        st.markdown("""
        ---
        ### 📄 License & Credits
        **If you use this software, please cite:** Schlegel, de Riz, Riccabona et al. (2025). *XYZ*. [Link](#)
        
        **Data Source Citations:**
        - [OAS Database](https://opig.stats.ox.ac.uk/webapps/oas/)
            - Olsen, T.H., Boyles, F., and Deane C.M. (2021). *Protein Science*. [Link](#)
            - Kovaltsuk, A., Leem, J. et al (2018). *J. Immunol*. [Link](#)

        **ABHunter** - High-performance OAS antibody database search - GNU GPLv3 License
        """)
    
    # Handle reindex request with progress bar (only in development)
    if st.session_state.get('reindex_requested', False) and not is_production():
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
    elif st.session_state.get('reindex_requested', False) and is_production():
        # Clear reindex request in production (should not happen)
        st.session_state['reindex_requested'] = False
        st.session_state['reindex_db'] = None
        st.error("❌ Database reindexing is not available in production mode.")
    
    # Only show search form if database is loaded and not reindexing
    if st.session_state.get('reindex_requested', False):
        # Show reindexing message instead of search form
        st.info("🔄 Database is being reindexed. Please wait...")
        return
    elif 'search_engine' not in st.session_state or st.session_state.get('current_db') != selected_db:
        st.error("Please reindex the database first using the 'Reindex Database' button.")
        return
    
    engine = st.session_state['search_engine']
    
    # Show warning if metadata needs updating (only in development)
    if not metadata_fresh and not is_production():
        st.warning("🔄 **Database files have been updated!** Please click 'Reindex Database' to refresh the metadata and see the latest data.")
    elif not metadata_fresh and is_production():
        st.error("⚠️ **Database metadata is outdated!** Please contact the administrator to update the database.")
    
    # Get database schema to determine search form type
    schema = get_database_schema(selected_db)
    
    # Search form
    st.markdown("## 🔍 Search Criteria")
    st.divider()
    
    # Show database type indicator
    if schema['search_type'] == 'paired':
        st.info("🔗 **Paired Database**: Search heavy and light chains separately")
    elif schema['search_type'] == 'unpaired':
        st.info("🧬 **Unpaired Database**: Single chain search")
    else:
        st.warning(f"⚠️ **Unknown Database Type**: {schema.get('error', 'Could not detect schema')}")
    
    with st.form("search_form"):
        # Create appropriate search form based on schema
        if schema['search_type'] == 'paired':
            search_params = create_paired_search_form()
        else:
            search_params = create_unpaired_search_form()
        
        # Fixed sample limit for display
        sample_limit = 100
        
        # Form submit button
        search_submitted = st.form_submit_button(
            "🔍 Search Database", 
            type="primary",
            use_container_width=False
        )
    
    # Create empty containers for dynamic content
    results_container = st.empty()
    status_container = st.empty()
    
    # Display cached results if form not submitted
    if not search_submitted and 'last_search_results' in st.session_state:
        cached_results = st.session_state['last_search_results']
        sequences_sample_df = cached_results['sequences_sample_df']
        statistics = cached_results['statistics']
        stats_df = cached_results['stats_df']
        
        # Display cached results using the reusable function
        with results_container.container():
            display_search_results(sequences_sample_df, statistics, stats_df)
        
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
        # Validate inputs based on search form type
        if not search_params.get('valid', True):
            st.error("❌ Please fix the invalid inputs (marked in red) before searching")
            return
        
        # Check if at least one criterion is provided
        if schema['search_type'] == 'paired':
            # Check paired parameters
            has_criteria = any([
                search_params.get('heavy_v'), search_params.get('heavy_d'), search_params.get('heavy_j'),
                search_params.get('heavy_cdr1_length'), search_params.get('heavy_cdr2_length'), search_params.get('heavy_cdr3_length'),
                search_params.get('heavy_cdr1_motif'), search_params.get('heavy_cdr2_motif'), search_params.get('heavy_cdr3_motif'),
                search_params.get('light_v'), search_params.get('light_d'), search_params.get('light_j'),
                search_params.get('light_cdr1_length'), search_params.get('light_cdr2_length'), search_params.get('light_cdr3_length'),
                search_params.get('light_cdr1_motif'), search_params.get('light_cdr2_motif'), search_params.get('light_cdr3_motif')
            ])
        else:
            # Check unpaired parameters
            has_criteria = any([
                search_params.get('ighv'), search_params.get('ighd'), search_params.get('ighj'),
                search_params.get('cdr1_length'), search_params.get('cdr2_length'), search_params.get('cdr3_length'),
                search_params.get('cdr1_motif'), search_params.get('cdr2_motif'), search_params.get('cdr3_motif')
            ])
        
        if not has_criteria:
            st.warning("⚠️ Please enter at least one search criterion")
            return
        
        # Perform search
        with st.spinner("Searching database..."):
            try:
                # Call search engine with appropriate parameters
                if schema['search_type'] == 'paired':
                    # Paired search
                    sequences_sample_df, statistics = engine.search(
                        # Heavy chain parameters
                        heavy_v=search_params.get('heavy_v', ''),
                        heavy_d=search_params.get('heavy_d', ''),
                        heavy_j=search_params.get('heavy_j', ''),
                        heavy_cdr1_length=search_params.get('heavy_cdr1_length') if search_params.get('heavy_cdr1_length') and search_params.get('heavy_cdr1_length') > 0 else None,
                        heavy_cdr2_length=search_params.get('heavy_cdr2_length') if search_params.get('heavy_cdr2_length') and search_params.get('heavy_cdr2_length') > 0 else None,
                        heavy_cdr3_length=search_params.get('heavy_cdr3_length') if search_params.get('heavy_cdr3_length') and search_params.get('heavy_cdr3_length') > 0 else None,
                        heavy_cdr1_motif=search_params.get('heavy_cdr1_motif', ''),
                        heavy_cdr2_motif=search_params.get('heavy_cdr2_motif', ''),
                        heavy_cdr3_motif=search_params.get('heavy_cdr3_motif', ''),
                        # Light chain parameters
                        light_v=search_params.get('light_v', ''),
                        light_d=search_params.get('light_d', ''),
                        light_j=search_params.get('light_j', ''),
                        light_cdr1_length=search_params.get('light_cdr1_length') if search_params.get('light_cdr1_length') and search_params.get('light_cdr1_length') > 0 else None,
                        light_cdr2_length=search_params.get('light_cdr2_length') if search_params.get('light_cdr2_length') and search_params.get('light_cdr2_length') > 0 else None,
                        light_cdr3_length=search_params.get('light_cdr3_length') if search_params.get('light_cdr3_length') and search_params.get('light_cdr3_length') > 0 else None,
                        light_cdr1_motif=search_params.get('light_cdr1_motif', ''),
                        light_cdr2_motif=search_params.get('light_cdr2_motif', ''),
                        light_cdr3_motif=search_params.get('light_cdr3_motif', ''),
                        full_results=True,
                        limit=sample_limit
                    )
                    
                    # Get statistics separately (fast)
                    stats_df, _ = engine.search(
                        # Heavy chain parameters
                        heavy_v=search_params.get('heavy_v', ''),
                        heavy_d=search_params.get('heavy_d', ''),
                        heavy_j=search_params.get('heavy_j', ''),
                        heavy_cdr1_length=search_params.get('heavy_cdr1_length') if search_params.get('heavy_cdr1_length') and search_params.get('heavy_cdr1_length') > 0 else None,
                        heavy_cdr2_length=search_params.get('heavy_cdr2_length') if search_params.get('heavy_cdr2_length') and search_params.get('heavy_cdr2_length') > 0 else None,
                        heavy_cdr3_length=search_params.get('heavy_cdr3_length') if search_params.get('heavy_cdr3_length') and search_params.get('heavy_cdr3_length') > 0 else None,
                        heavy_cdr1_motif=search_params.get('heavy_cdr1_motif', ''),
                        heavy_cdr2_motif=search_params.get('heavy_cdr2_motif', ''),
                        heavy_cdr3_motif=search_params.get('heavy_cdr3_motif', ''),
                        # Light chain parameters
                        light_v=search_params.get('light_v', ''),
                        light_d=search_params.get('light_d', ''),
                        light_j=search_params.get('light_j', ''),
                        light_cdr1_length=search_params.get('light_cdr1_length') if search_params.get('light_cdr1_length') and search_params.get('light_cdr1_length') > 0 else None,
                        light_cdr2_length=search_params.get('light_cdr2_length') if search_params.get('light_cdr2_length') and search_params.get('light_cdr2_length') > 0 else None,
                        light_cdr3_length=search_params.get('light_cdr3_length') if search_params.get('light_cdr3_length') and search_params.get('light_cdr3_length') > 0 else None,
                        light_cdr1_motif=search_params.get('light_cdr1_motif', ''),
                        light_cdr2_motif=search_params.get('light_cdr2_motif', ''),
                        light_cdr3_motif=search_params.get('light_cdr3_motif', ''),
                        full_results=False
                    )
                else:
                    # Unpaired search (backward compatibility)
                    sequences_sample_df, statistics = engine.search(
                        ighv=search_params.get('ighv', ''),
                        ighd=search_params.get('ighd', ''),
                        ighj=search_params.get('ighj', ''),
                        cdr1_length=search_params.get('cdr1_length') if search_params.get('cdr1_length') and search_params.get('cdr1_length') > 0 else None,
                        cdr2_length=search_params.get('cdr2_length') if search_params.get('cdr2_length') and search_params.get('cdr2_length') > 0 else None,
                        cdr3_length=search_params.get('cdr3_length') if search_params.get('cdr3_length') and search_params.get('cdr3_length') > 0 else None,
                        cdr1_motif=search_params.get('cdr1_motif', ''),
                        cdr2_motif=search_params.get('cdr2_motif', ''),
                        cdr3_motif=search_params.get('cdr3_motif', ''),
                        full_results=True,
                        limit=sample_limit
                    )
                    
                    # Get statistics separately (fast)
                    stats_df, _ = engine.search(
                        ighv=search_params.get('ighv', ''),
                        ighd=search_params.get('ighd', ''),
                        ighj=search_params.get('ighj', ''),
                        cdr1_length=search_params.get('cdr1_length') if search_params.get('cdr1_length') and search_params.get('cdr1_length') > 0 else None,
                        cdr2_length=search_params.get('cdr2_length') if search_params.get('cdr2_length') and search_params.get('cdr2_length') > 0 else None,
                        cdr3_length=search_params.get('cdr3_length') if search_params.get('cdr3_length') and search_params.get('cdr3_length') > 0 else None,
                        cdr1_motif=search_params.get('cdr1_motif', ''),
                        cdr2_motif=search_params.get('cdr2_motif', ''),
                        cdr3_motif=search_params.get('cdr3_motif', ''),
                        full_results=False
                    )
                
                # For download, we'll load full data only when needed
                sequences_full_df = None  # Will be loaded on demand
                
                # Store results in session state for caching
                st.session_state['last_search_results'] = {
                    'sequences_sample_df': sequences_sample_df,
                    'statistics': statistics,
                    'stats_df': stats_df
                }
                
                # Show success toast
                st.toast(f"✅ Search completed! Found {statistics['total_hits']:,} sequences", icon="🎉")
                
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
                        height=300,
                        column_config={
                            "subject": st.column_config.TextColumn("Subject", width="medium"),
                            "hits": st.column_config.NumberColumn("Hits", width="small"),
                            "total_sequences": st.column_config.NumberColumn("Total Sequences", width="medium"),
                            "hit_percentage": st.column_config.NumberColumn("Hit %", width="small", format="%.2f%%"),
                            "hits_per_million": st.column_config.NumberColumn("Hits/Million", width="medium", format="%.1f")
                        }
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
                    
                    # Rename gene columns for display based on schema type
                    if schema['search_type'] == 'paired':
                        column_rename = {
                            'v_call_heavy': 'v_gen_heavy',
                            'd_call_heavy': 'd_gen_heavy', 
                            'j_call_heavy': 'j_gen_heavy',
                            'v_call_light': 'v_gen_light',
                            'd_call_light': 'd_gen_light', 
                            'j_call_light': 'j_gen_light'
                        }
                        column_config = {
                            "v_gen_heavy": st.column_config.TextColumn("Heavy V Gene", width="medium"),
                            "d_gen_heavy": st.column_config.TextColumn("Heavy D Gene", width="medium"),
                            "j_gen_heavy": st.column_config.TextColumn("Heavy J Gene", width="medium"),
                            "v_gen_light": st.column_config.TextColumn("Light V Gene", width="medium"),
                            "d_gen_light": st.column_config.TextColumn("Light D Gene", width="medium"),
                            "j_gen_light": st.column_config.TextColumn("Light J Gene", width="medium"),
                            "cdr1_aa_heavy": st.column_config.TextColumn("Heavy CDRH1", width="large"),
                            "cdr2_aa_heavy": st.column_config.TextColumn("Heavy CDRH2", width="large"),
                            "cdr3_aa_heavy": st.column_config.TextColumn("Heavy CDRH3", width="large"),
                            "cdr1_aa_light": st.column_config.TextColumn("Light CDRL1", width="large"),
                            "cdr2_aa_light": st.column_config.TextColumn("Light CDRL2", width="large"),
                            "cdr3_aa_light": st.column_config.TextColumn("Light CDRL3", width="large"),
                            "subject": st.column_config.TextColumn("Subject", width="medium")
                        }
                    else:
                        column_rename = {
                            'v_call': 'v_gen',
                            'd_call': 'd_gen', 
                            'j_call': 'j_gen'
                        }
                        column_config = {
                            "v_gen": st.column_config.TextColumn("V Gene", width="medium"),
                            "d_gen": st.column_config.TextColumn("D Gene", width="medium"),
                            "j_gen": st.column_config.TextColumn("J Gene", width="medium"),
                            "cdr1_aa": st.column_config.TextColumn("CDRH1", width="large"),
                            "cdr2_aa": st.column_config.TextColumn("CDRH2", width="large"),
                            "cdr3_aa": st.column_config.TextColumn("CDRH3", width="large"),
                            "cdr1_length": st.column_config.NumberColumn("CDRH1 Len", width="small"),
                            "cdr2_length": st.column_config.NumberColumn("CDRH2 Len", width="small"),
                            "cdr3_length": st.column_config.NumberColumn("CDRH3 Len", width="small"),
                            "subject": st.column_config.TextColumn("Subject", width="medium")
                        }
                    
                    sequences_display = sequences_display.rename(columns=column_rename)
                    
                    st.dataframe(
                        sequences_display,
                        use_container_width=True,
                        height=400,
                        column_config=column_config
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
                    # Generate filename based on search parameters
                    if schema['search_type'] == 'paired':
                        filename = f"abdb_stats_paired.csv"
                    else:
                        filename = f"abdb_stats_unpaired.csv"
                    st.download_button(
                        label="📊 Download Statistics (CSV)",
                        data=stats_csv,
                        file_name=filename,
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
                                    # Load full dataset on demand based on schema type
                                    if schema['search_type'] == 'paired':
                                        sequences_full_df, _ = engine.search(
                                            # Heavy chain parameters
                                            heavy_v=search_params.get('heavy_v', ''),
                                            heavy_d=search_params.get('heavy_d', ''),
                                            heavy_j=search_params.get('heavy_j', ''),
                                            heavy_cdr1_length=search_params.get('heavy_cdr1_length') if search_params.get('heavy_cdr1_length') and search_params.get('heavy_cdr1_length') > 0 else None,
                                            heavy_cdr2_length=search_params.get('heavy_cdr2_length') if search_params.get('heavy_cdr2_length') and search_params.get('heavy_cdr2_length') > 0 else None,
                                            heavy_cdr3_length=search_params.get('heavy_cdr3_length') if search_params.get('heavy_cdr3_length') and search_params.get('heavy_cdr3_length') > 0 else None,
                                            heavy_cdr1_motif=search_params.get('heavy_cdr1_motif', ''),
                                            heavy_cdr2_motif=search_params.get('heavy_cdr2_motif', ''),
                                            heavy_cdr3_motif=search_params.get('heavy_cdr3_motif', ''),
                                            # Light chain parameters
                                            light_v=search_params.get('light_v', ''),
                                            light_d=search_params.get('light_d', ''),
                                            light_j=search_params.get('light_j', ''),
                                            light_cdr1_length=search_params.get('light_cdr1_length') if search_params.get('light_cdr1_length') and search_params.get('light_cdr1_length') > 0 else None,
                                            light_cdr2_length=search_params.get('light_cdr2_length') if search_params.get('light_cdr2_length') and search_params.get('light_cdr2_length') > 0 else None,
                                            light_cdr3_length=search_params.get('light_cdr3_length') if search_params.get('light_cdr3_length') and search_params.get('light_cdr3_length') > 0 else None,
                                            light_cdr1_motif=search_params.get('light_cdr1_motif', ''),
                                            light_cdr2_motif=search_params.get('light_cdr2_motif', ''),
                                            light_cdr3_motif=search_params.get('light_cdr3_motif', ''),
                                            full_results=True,
                                            limit=None  # No limit - get everything
                                        )
                                    else:
                                        sequences_full_df, _ = engine.search(
                                            ighv=search_params.get('ighv', ''),
                                            ighd=search_params.get('ighd', ''),
                                            ighj=search_params.get('ighj', ''),
                                            cdr1_length=search_params.get('cdr1_length') if search_params.get('cdr1_length') and search_params.get('cdr1_length') > 0 else None,
                                            cdr2_length=search_params.get('cdr2_length') if search_params.get('cdr2_length') and search_params.get('cdr2_length') > 0 else None,
                                            cdr3_length=search_params.get('cdr3_length') if search_params.get('cdr3_length') and search_params.get('cdr3_length') > 0 else None,
                                            cdr1_motif=search_params.get('cdr1_motif', ''),
                                            cdr2_motif=search_params.get('cdr2_motif', ''),
                                            cdr3_motif=search_params.get('cdr3_motif', ''),
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
                                    
                                    # Column renaming based on schema type
                                    if schema['search_type'] == 'paired':
                                        column_rename = {
                                            'v_call_heavy': 'v_gen_heavy',
                                            'd_call_heavy': 'd_gen_heavy', 
                                            'j_call_heavy': 'j_gen_heavy',
                                            'v_call_light': 'v_gen_light',
                                            'd_call_light': 'd_gen_light', 
                                            'j_call_light': 'j_gen_light'
                                        }
                                        filename_base = "abdb_sequences_paired"
                                    else:
                                        column_rename = {
                                            'v_call': 'v_gen',
                                            'd_call': 'd_gen', 
                                            'j_call': 'j_gen'
                                        }
                                        filename_base = "abdb_sequences_unpaired"
                                    
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
                                        zip_file.writestr(f"{filename_base}.parquet", parquet_data)
                                    
                                    zip_data = zip_buffer.getvalue()
                                    
                                    # Download button
                                    st.download_button(
                                        label=f"📦 Download ZIP File ({len(zip_data) / 1024 / 1024:.1f} MB)",
                                        data=zip_data,
                                        file_name=f"{filename_base}.zip",
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
    


if __name__ == "__main__":
    main()

