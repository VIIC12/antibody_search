"""
Tests for search statistics calculations and inferred pairing logic.
"""

import pytest
import pandas as pd
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from search_engine import AntibodySearchEngine

def _write_chain_data(data_dir: Path, chain: str, filename: str, mock_data: pd.DataFrame) -> None:
    """Write mock sequence data plus a matching metadata.parquet.

    Two production requirements this mirrors (src/search_engine.py
    AntibodySearchEngine._register_data / scripts/convert_to_parquet.py),
    both silent-empty-result traps if skipped:

    1. Every registered directory needs a metadata.parquet (a
       FileNotFoundError otherwise); self.total_sequences is the SUM of its
       total_sequences column, independent of the sequence data itself.
    2. The sequence file must live under a `Heavy/`, `Light/`, or `Paired/`
       directory, and metadata's file_path must equal "<Chain>/<filename>":
       the antibodies/metadata join extracts that segment from the parquet
       file's own path via regexp_replace, and _search_unpaired filters on
       `chain = '<chain_type>'` whenever a 'chain' column is present -- a
       missing subdirectory or mismatched chain value makes that join (and
       so every 'chain' value) NULL, which zeroes out every search result
       without raising.
    """
    chain_dir = data_dir / chain
    chain_dir.mkdir(parents=True, exist_ok=True)
    mock_data.to_parquet(chain_dir / filename, index=False)

    metadata = pd.DataFrame({
        'filename': [filename],
        'file_path': [f"{chain}/{filename}"],
        'subject': [mock_data['subject'].iloc[0]],
        'isotype': [mock_data['isotype'].iloc[0]],
        'chain': [chain],
        'rows': [len(mock_data)],
        'total_sequences': [len(mock_data)],
    })
    metadata.to_parquet(data_dir / "metadata.parquet", index=False)

def make_subject_data(subject: str, total: int, hits: int) -> pd.DataFrame:
    rows = []
    for i in range(total):
        is_hit = i < hits
        rows.append({
            'subject': subject,
            'isotype': 'IgG',
            'v_call': 'IGHV3-23*01' if is_hit else 'IGHV1-69*01',
            'd_call': 'IGHD3-10*01',
            'j_call': 'IGHJ4*01',
            'cdr1_aa': 'ARSSS',
            'cdr2_aa': 'ISSGG',
            'cdr3_aa': 'CARGGY',
            'cdr1_length': 5,
            'cdr2_length': 5,
            'cdr3_length': 6,
            'sequence_id': f'{subject}_seq{i}'
        })
    return pd.DataFrame(rows)


class TestStatisticsAndInferredPairing:
    
    @pytest.fixture
    def temp_dir(self):
        d = tempfile.mkdtemp()
        yield Path(d)
        shutil.rmtree(d)

    def test_search_statistics_formulas(self, temp_dir):
        # Arrange
        # SubjA: 8 sequences, 3 hits
        # SubjB: 4 sequences, 0 hits
        # SubjC: 6 sequences, 1 hits
        # Overall: 18 sequences, 4 hits
        data_dirs = []
        configs = [
            ("SubjA", 8, 3),
            ("SubjB", 4, 0),
            ("SubjC", 6, 1)
        ]
        
        for subj, total, hits in configs:
            dd = temp_dir / subj
            dd.mkdir()
            df = make_subject_data(subj, total, hits)
            _write_chain_data(dd, "Heavy", f"{subj}.parquet", df)
            data_dirs.append(str(dd))
            
        engine = AntibodySearchEngine(data_dirs=data_dirs)
        
        # Act
        results_df, stats_df, stats = engine.search(
            chain_mode="heavy", 
            heavy_v="IGHV3-23", 
            full_results=True
        )
        
        # Assert
        # 1. Per-subject stats_df percentage column equals hits/total_sequences*100 rounded to 2 decimals
        # SubjA: hits=3, total=8, so 3/8*100=37.5, round(2) is 37.5
        # SubjC: hits=1, total=6, so 1/6*100=16.666..., round(2) is 16.67
        subj_a = stats_df[stats_df['subject'] == 'SubjA'].iloc[0]
        assert subj_a['percentage'] == 37.5
        
        subj_c = stats_df[stats_df['subject'] == 'SubjC'].iloc[0]
        assert subj_c['percentage'] == 16.67
        
        # 2. Per-subject stats_df per_million column equals hits/total_sequences*1000000 rounded to 0 decimals
        # SubjA: 3/8*1000000 = 375000.0, round(0) is 375000.0
        # SubjC: 1/6*1000000 = 166666.666..., round(0) is 166667.0
        assert subj_a['per_million'] == 375000.0
        assert subj_c['per_million'] == 166667.0
        
        # 3. Overall stats percentage key equals total_hits/total_sequences*100 rounded to 2 decimals
        # Total hits = 4, Total seqs = 18, so 4/18*100 = 22.222..., round(2) is 22.22
        assert stats['percentage'] == 22.22
        
        # 5. A subject with zero hits: percentage and per_million must be 0.0, not NaN
        subj_b = stats_df[stats_df['subject'] == 'SubjB'].iloc[0]
        assert subj_b['percentage'] == 0.0
        assert subj_b['per_million'] == 0.0
        assert isinstance(subj_b['percentage'], float)
        assert isinstance(subj_b['per_million'], float)

    def test_precision_mismatch_documented_behavior(self, temp_dir):
        # 4. Overall stats per_million key equals total_hits/total_sequences*1000000 rounded to 1 decimal
        
        # Arrange
        # We need a hit rate where rounding to 0 decimals vs 1 decimal yields different values.
        # Total=3, hits=1 -> hit rate = 1/3
        # per_million = 333333.333...
        # round(0) -> 333333.0
        # round(1) -> 333333.3
        dd = temp_dir / "Subj1"
        dd.mkdir()
        df = make_subject_data("Subj1", 3, 1)
        _write_chain_data(dd, "Heavy", "Subj1.parquet", df)
        engine = AntibodySearchEngine(data_dirs=[str(dd)])
        
        # Act
        results_df, stats_df, stats = engine.search(
            chain_mode="heavy", 
            heavy_v="IGHV3-23"
        )
        
        # Assert
        subj_stats = stats_df.iloc[0]
        # This flags a real, surprising inconsistency in current production code:
        # Per-subject per_million is rounded to 0 decimals (yielding ...0 float),
        # but overall per_million is rounded to 1 decimal (yielding ...X float).
        # This test pins down that documented behavior.
        assert subj_stats['per_million'] == 333333.0
        assert stats['per_million'] == 333333.3

    def test_zero_sequences_across_dataset(self, temp_dir):
        # 6. A search matching zero sequences across the ENTIRE dataset
        
        # Arrange
        dd = temp_dir / "SubjZ"
        dd.mkdir()
        df = make_subject_data("SubjZ", 5, 0)
        _write_chain_data(dd, "Heavy", "SubjZ.parquet", df)
        engine = AntibodySearchEngine(data_dirs=[str(dd)])
        
        # Act
        results_df, stats_df, stats = engine.search(
            chain_mode="heavy", 
            heavy_v="IGHV3-23"
        )
        
        # Assert
        assert stats['total_hits'] == 0
        # Python's conditional fallback (`round(...) if total_sequences > 0 else 0`) 
        # takes the `if` branch here because total_sequences = 5 > 0.
        # It evaluates `round(0.0, 2)` and `round(0.0, 1)`, returning float 0.0.
        assert stats['percentage'] == 0.0
        assert isinstance(stats['percentage'], float)
        assert stats['per_million'] == 0.0
        assert isinstance(stats['per_million'], float)

    def test_full_results_flag_equivalence(self, temp_dir):
        # 7. full_results=False (default) vs full_results=True on the identical search
        
        # Arrange
        data_dirs = []
        configs = [
            ("SubjA", 8, 3),
            ("SubjB", 4, 0),
            ("SubjC", 6, 1)
        ]
        for subj, total, hits in configs:
            dd = temp_dir / subj
            dd.mkdir()
            df = make_subject_data(subj, total, hits)
            _write_chain_data(dd, "Heavy", f"{subj}.parquet", df)
            data_dirs.append(str(dd))
            
        engine = AntibodySearchEngine(data_dirs=data_dirs)
        
        # Act
        res_false, stats_df_false, stats_false = engine.search(
            chain_mode="heavy", 
            heavy_v="IGHV3-23", 
            full_results=False
        )
        
        res_true, stats_df_true, stats_true = engine.search(
            chain_mode="heavy", 
            heavy_v="IGHV3-23", 
            full_results=True
        )
        
        # Assert
        assert stats_false['total_hits'] == stats_true['total_hits'] == 4
        assert stats_false['percentage'] == stats_true['percentage'] == 22.22
        
        # len(results_df) differs between the two calls.
        # full_results=False returns the stats_df as results_df (which is grouped by subject).
        # In our dataset with 3 subjects, only 2 subjects have hits, so len(results_df) = 2.
        # If we use full_results=True, it returns all hit sequences (4 sequences), 
        # so len(results_df) = 4. They differ!
        assert len(res_false) == 2  
        assert len(res_true) == 4   


    @pytest.mark.parametrize("chain, gene, expected", [
        ("Heavy", "IGHV3-30*01", [('IGKV1', 50.0), ('IGLV2', 30.0), ('IGLV1', 20.0)]),
        ("Light", "IGKV1", [('IGHV1', 60.0), ('IGHV3', 10.0)]),
        ("Heavy", "IGHV9", []), # Family with no lookup entry
        ("Heavy", "IGHV3", [])  # Unknown gene_type case (tested separately)
    ], ids=["heavy_sort", "light_sort", "missing_family", "unknown_type_placeholder"])
    @patch('search_engine.AntibodySearchEngine._register_data')
    def test_inferred_pairing_logic(self, mock_register, chain, gene, expected):
        # 1, 2, 4, 5. Sorting, Zero-filtering, Direction matters, Family extraction
        # Arrange
        engine = AntibodySearchEngine(data_dirs=[])
        
        df = pd.DataFrame([
            {'heavy_v_family': 'IGHV3', 'light_v_family': 'IGKV1', 'h_to_l': 50.0, 'l_to_h': 10.0},
            {'heavy_v_family': 'IGHV3', 'light_v_family': 'IGLV2', 'h_to_l': 30.0, 'l_to_h': 20.0},
            # IGKV3 should be excluded when queried via Heavy because h_to_l is 0.0
            {'heavy_v_family': 'IGHV3', 'light_v_family': 'IGKV3', 'h_to_l': 0.0,  'l_to_h': 5.0}, 
            {'heavy_v_family': 'IGHV3', 'light_v_family': 'IGLV1', 'h_to_l': 20.0, 'l_to_h': 30.0},
            {'heavy_v_family': 'IGHV1', 'light_v_family': 'IGKV1', 'h_to_l': 100.0, 'l_to_h': 60.0},
        ])
        
        engine.inferred_v_pairs_df = df
        engine._rebuild_inferred_lookup()
        
        # Act & Assert
        if gene == "IGHV3" and expected == []:
            # 6. Unknown gene_type
            assert engine._get_inferred_partners('Heavy', 'IGHV3', gene_type='X') == []
        else:
            partners = engine._get_inferred_partners(chain, gene, gene_type='V', top_n=None)
            assert partners == expected

    @patch('search_engine.AntibodySearchEngine._register_data')
    def test_inferred_pairing_top_n_and_wrapper(self, mock_register):
        # 3 & 7. top_n truncation and get_inferred_distribution wrapper
        # Arrange
        engine = AntibodySearchEngine(data_dirs=[])
        
        df = pd.DataFrame([
            {'heavy_v_family': 'IGHV3', 'light_v_family': 'IGKV1', 'h_to_l': 50.0, 'l_to_h': 10.0},
            {'heavy_v_family': 'IGHV3', 'light_v_family': 'IGLV2', 'h_to_l': 30.0, 'l_to_h': 20.0},
            {'heavy_v_family': 'IGHV3', 'light_v_family': 'IGLV1', 'h_to_l': 20.0, 'l_to_h': 30.0},
        ])
        
        engine.inferred_v_pairs_df = df
        engine._rebuild_inferred_lookup()
        
        # Act
        partners_top2 = engine._get_inferred_partners('Heavy', 'IGHV3-30*01', gene_type='V', top_n=2)
        dist = engine.get_inferred_distribution('Heavy', 'IGHV3-30*01', gene_type='V', top_n=2)
        
        # Assert
        assert partners_top2 == [('IGKV1', 50.0), ('IGLV2', 30.0)]
        assert dist == partners_top2

    @patch('search_engine.AntibodySearchEngine._register_data')
    def test_load_inferred_pairs_fallback_and_aggregation(self, mock_register, temp_dir):
        # 8 & 9. End-to-end test going through real load_inferred_pairs
        
        # Arrange
        engine = AntibodySearchEngine(data_dirs=[])
        
        df = pd.DataFrame([
            # Duplicate rows for IGHV1 -> IGKV1 to test aggregation (Requirement 9)
            # h_to_l values: 10.0 and 20.0 -> average should be 15.0
            {'vh_family': 'IGHV1', 'vl_family': 'IGKV1', 'h_to_l': 10.0},
            {'vh_family': 'IGHV1', 'vl_family': 'IGKV1', 'h_to_l': 20.0},
            
            # Second heavy family for IGKV1
            {'vh_family': 'IGHV2', 'vl_family': 'IGKV1', 'h_to_l': 45.0},
        ])
        
        # Arithmetic for IGKV1's l_to_h (Requirement 8):
        # After groupby.agg(mean):
        # IGHV1 -> IGKV1 : h_to_l = 15.0
        # IGHV2 -> IGKV1 : h_to_l = 45.0
        # Sum of h_to_l for IGKV1 = 15.0 + 45.0 = 60.0
        # l_to_h for IGHV1 = 15.0 / 60.0 * 100 = 25.0
        # l_to_h for IGHV2 = 45.0 / 60.0 * 100 = 75.0
        
        overlay_dir = temp_dir / "overlay"
        overlay_dir.mkdir()
        df.to_parquet(overlay_dir / "adj_vh_vl_freq_table_for_search_wo_epsilon.parquet", index=False)
        
        # Act
        engine.load_inferred_pairs([str(overlay_dir)])
        
        # Assert
        partners = engine._get_inferred_partners('Light', 'IGKV1', gene_type='V', top_n=None)
        assert partners == [('IGHV2', 75.0), ('IGHV1', 25.0)]
