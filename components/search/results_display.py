"""
Results display utilities for formatting and displaying search results.

This module provides functions for formatting dataframes, column renaming,
and Streamlit column configuration.
"""

import streamlit as st
from typing import Dict, Any, Set
import pandas as pd


def get_exclude_columns() -> Set[str]:
    """
    Get set of columns to exclude from display/download.
    
    Returns:
        Set of column names to exclude
    """
    return {
        'file_source', 'filename', 'rows', 'unique_sequences',
        'total_sequences', 'source_file', 'filepath', 'file_size_mb'
    }


def get_column_rename_mapping(is_paired: bool) -> Dict[str, str]:
    """
    Get column renaming mapping based on search type.
    
    Args:
        is_paired: Whether this is a paired search
        
    Returns:
        Dictionary mapping old column names to new column names
    """
    if is_paired:
        return {
            'v_call_heavy': 'v_gen_heavy',
            'd_call_heavy': 'd_gen_heavy',
            'j_call_heavy': 'j_gen_heavy',
            'v_call_light': 'v_gen_light',
            'j_call_light': 'j_gen_light'
        }
    else:
        return {
            'v_call': 'v_gen',
            'd_call': 'd_gen',
            'j_call': 'j_gen'
        }


def get_column_config(is_paired: bool) -> Dict[str, Any]:
    """
    Get Streamlit column configuration based on search type.
    
    Args:
        is_paired: Whether this is a paired search
        
    Returns:
        Dictionary of Streamlit column configurations
    """
    if is_paired:
        return {
            "v_gen_heavy": st.column_config.TextColumn("Heavy V Gene", width="medium"),
            "d_gen_heavy": st.column_config.TextColumn("Heavy D Gene", width="medium"),
            "j_gen_heavy": st.column_config.TextColumn("Heavy J Gene", width="medium"),
            "v_gen_light": st.column_config.TextColumn("Light V Gene", width="medium"),
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
        return {
            "v_gen": st.column_config.TextColumn("V Gene", width="medium"),
            "d_gen": st.column_config.TextColumn("D Gene", width="medium"),
            "j_gen": st.column_config.TextColumn("J Gene", width="medium"),
            "cdr1_aa": st.column_config.TextColumn("CDRH1", width="large"),
            "cdr2_aa": st.column_config.TextColumn("CDRH2", width="large"),
            "cdr3_aa": st.column_config.TextColumn("CDRH3", width="large"),
            "cdr1_length": st.column_config.NumberColumn("CDRH1 Len", width="small"),
            "cdr2_length": st.column_config.NumberColumn("CDRH2 Len", width="small"),
            "cdr3_length": st.column_config.NumberColumn("CDRH3 Len", width="small"),
            "subject": st.column_config.TextColumn("Subject", width="medium"),
            # V gene inferred partners
            "inferred_light_v_partners": st.column_config.TextColumn("Inferred Light V Families", width="large"),
            "inferred_light_v_top_family": st.column_config.TextColumn("Top Light V Family", width="medium"),
            "inferred_light_v_top_percent": st.column_config.NumberColumn("Top Light V %", width="small", format="%.1f%%"),
            # J gene inferred partners
            "inferred_light_j_partners": st.column_config.TextColumn("Inferred Light J Families", width="large"),
            "inferred_light_j_top_family": st.column_config.TextColumn("Top Light J Family", width="medium"),
            "inferred_light_j_top_percent": st.column_config.NumberColumn("Top Light J %", width="small", format="%.1f%%"),
            # Heavy chain inferred partners
            "inferred_heavy_v_partners": st.column_config.TextColumn("Inferred Heavy V Families", width="large"),
            "inferred_heavy_v_top_family": st.column_config.TextColumn("Top Heavy V Family", width="medium"),
            "inferred_heavy_v_top_percent": st.column_config.NumberColumn("Top Heavy V %", width="small", format="%.1f%%"),
            # J gene inferred partners for heavy chain
            "inferred_heavy_j_partners": st.column_config.TextColumn("Inferred Heavy J Families", width="large"),
            "inferred_heavy_j_top_family": st.column_config.TextColumn("Top Heavy J Family", width="medium"),
            "inferred_heavy_j_top_percent": st.column_config.NumberColumn("Top Heavy J %", width="small", format="%.1f%%"),
        }


def format_results_dataframe(
    df: pd.DataFrame,
    is_paired: bool,
    exclude_cols: Set[str] = None
) -> pd.DataFrame:
    """
    Format results dataframe by excluding columns and renaming columns.
    
    Args:
        df: Input dataframe
        is_paired: Whether this is a paired search
        exclude_cols: Optional set of columns to exclude (defaults to get_exclude_columns())
        
    Returns:
        Formatted dataframe
    """
    if exclude_cols is None:
        exclude_cols = get_exclude_columns()
    
    # Filter columns
    display_cols = [col for col in df.columns if col not in exclude_cols]
    formatted_df = df[display_cols].copy()
    
    # Rename columns
    column_rename = get_column_rename_mapping(is_paired)
    formatted_df = formatted_df.rename(columns=column_rename)
    
    return formatted_df


def get_stats_column_config() -> Dict[str, Any]:
    """
    Get Streamlit column configuration for statistics dataframe.
    
    Returns:
        Dictionary of Streamlit column configurations for stats
    """
    return {
        "subject": st.column_config.TextColumn("Subject", width="medium"),
        "hits": st.column_config.NumberColumn("Hits", width="small"),
        "total_sequences": st.column_config.NumberColumn("Total Sequences", width="medium"),
        "hit_percentage": st.column_config.NumberColumn("Hit %", width="small", format="%.2f%%"),
        "hits_per_million": st.column_config.NumberColumn("Hits/Million", width="medium", format="%.1f")
    }

