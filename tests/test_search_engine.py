"""
Comprehensive pytest tests for AntibodySearchEngine.

Tests all functionality mentioned in README.md:
1. Database selection functionality
2. Each search field and combinations
3. Downloaded files correctness
4. Edge cases and error handling
"""

import pytest
import pandas as pd
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb
import os
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from search_engine import AntibodySearchEngine


class TestAntibodySearchEngine:
    """Test suite for AntibodySearchEngine class."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test data."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def mock_unpaired_data(self, temp_dir):
        """Create mock unpaired antibody data."""
        data_dir = Path(temp_dir) / "data" / "parquet"
        data_dir.mkdir(parents=True)
        
        # Create mock unpaired data
        mock_data = pd.DataFrame({
            'subject': ['Subject1', 'Subject1', 'Subject2', 'Subject2', 'Subject3'],
            'isotype': ['IgG', 'IgG', 'IgM', 'IgA', 'IgG'],
            'v_call': ['IGHV3-23*01', 'IGHV1-69*01', 'IGHV4-34*01', 'IGHV3-23*02', 'IGHV1-69*02'],
            'd_call': ['IGHD3-10*01', 'IGHD2-2*01', 'IGHD3-22*01', 'IGHD3-10*02', 'IGHD2-2*02'],
            'j_call': ['IGHJ4*01', 'IGHJ6*01', 'IGHJ4*02', 'IGHJ4*01', 'IGHJ6*02'],
            'cdr1_aa': ['ARSSS', 'ARSSS', 'ARSSS', 'ARSSS', 'ARSSS'],
            'cdr2_aa': ['ISSGG', 'ISSGG', 'ISSGG', 'ISSGG', 'ISSGG'],
            'cdr3_aa': ['CARGGY', 'CARGGY', 'CARGGY', 'CARGGY', 'CARGGY'],
            'cdr1_length': [5, 5, 5, 5, 5],
            'cdr2_length': [5, 5, 5, 5, 5],
            'cdr3_length': [6, 6, 6, 6, 6],
            'sequence_id': ['seq1', 'seq2', 'seq3', 'seq4', 'seq5']
        })
        
        # Save as parquet
        parquet_path = data_dir / "test_data.parquet"
        mock_data.to_parquet(parquet_path, index=False)
        
        return str(data_dir), mock_data
    
    @pytest.fixture
    def mock_light_unpaired_data(self, temp_dir):
        """Create mock unpaired light-chain antibody data."""
        data_dir = Path(temp_dir) / "data" / "parquet"
        data_dir.mkdir(parents=True)
        
        mock_data = pd.DataFrame({
            'subject': ['SubjectL1', 'SubjectK1', 'SubjectL2', 'SubjectK2'],
            'isotype': ['IgG', 'IgG', 'IgM', 'IgA'],
            'v_call': ['IGLV2-14*01', 'IGKV2-30*01', 'IGLV3-21*01', 'IGKV1-39*01'],
            'd_call': ['None', 'None', 'None', 'None'],
            'j_call': ['IGLJ2*01', 'IGKJ2*01', 'IGLJ3*01', 'IGKJ1*01'],
            'cdr1_aa': ['QQYNT', 'QQYNT', 'QQYNT', 'QQYNT'],
            'cdr2_aa': ['SASGG', 'SASGG', 'SASGG', 'SASGG'],
            'cdr3_aa': ['QQYWG', 'QQYWG', 'QQYWG', 'QQYWG'],
            'cdr1_length': [5, 5, 5, 5],
            'cdr2_length': [5, 5, 5, 5],
            'cdr3_length': [5, 5, 5, 5],
            'sequence_id': ['seqL1', 'seqK1', 'seqL2', 'seqK2']
        })
        
        parquet_path = data_dir / "test_light_data.parquet"
        mock_data.to_parquet(parquet_path, index=False)
        
        return str(data_dir), mock_data
    
    @pytest.fixture
    def mock_paired_data(self, temp_dir):
        """Create mock paired antibody data."""
        data_dir = Path(temp_dir) / "data" / "parquet"
        data_dir.mkdir(parents=True)
        
        # Create mock paired data
        mock_data = pd.DataFrame({
            'subject': ['Subject1', 'Subject1', 'Subject2', 'Subject2'],
            'isotype': ['IgG', 'IgG', 'IgM', 'IgA'],
            'v_call_heavy': ['IGHV3-23*01', 'IGHV1-69*01', 'IGHV4-34*01', 'IGHV3-23*02'],
            'd_call_heavy': ['IGHD3-10*01', 'IGHD2-2*01', 'IGHD3-22*01', 'IGHD3-10*02'],
            'j_call_heavy': ['IGHJ4*01', 'IGHJ6*01', 'IGHJ4*02', 'IGHJ4*01'],
            'cdr1_aa_heavy': ['ARSSS', 'ARSSS', 'ARSSS', 'ARSSS'],
            'cdr2_aa_heavy': ['ISSGG', 'ISSGG', 'ISSGG', 'ISSGG'],
            'cdr3_aa_heavy': ['CARGGY', 'CARGGY', 'CARGGY', 'CARGGY'],
            'cdr1_length_heavy': [5, 5, 5, 5],
            'cdr2_length_heavy': [5, 5, 5, 5],
            'cdr3_length_heavy': [6, 6, 6, 6],
            'v_call_light': ['IGKV1-39*01', 'IGKV1-39*02', 'IGKV3-20*01', 'IGKV3-20*02'],
            'd_call_light': ['None', 'None', 'None', 'None'],
            'j_call_light': ['IGKJ1*01', 'IGKJ1*02', 'IGKJ2*01', 'IGKJ2*02'],
            'cdr1_aa_light': ['RASQS', 'RASQS', 'RASQS', 'RASQS'],
            'cdr2_aa_light': ['YASQS', 'YASQS', 'YASQS', 'YASQS'],
            'cdr3_aa_light': ['QQYST', 'QQYST', 'QQYST', 'QQYST'],
            'cdr1_length_light': [5, 5, 5, 5],
            'cdr2_length_light': [5, 5, 5, 5],
            'cdr3_length_light': [5, 5, 5, 5],
            'sequence_id': ['seq1', 'seq2', 'seq3', 'seq4']
        })
        
        # Save as parquet
        parquet_path = data_dir / "test_paired_data.parquet"
        mock_data.to_parquet(parquet_path, index=False)
        
        return str(data_dir), mock_data
    
    @pytest.fixture
    def mock_metadata(self, temp_dir):
        """Create mock metadata file."""
        data_dir = Path(temp_dir) / "data" / "parquet"
        data_dir.mkdir(parents=True, exist_ok=True)
        
        metadata = pd.DataFrame({
            'filename': ['test_data.parquet', 'test_paired_data.parquet'],
            'file_path': ['parquet/test_data.parquet', 'parquet/test_paired_data.parquet'],
            'subject': ['Subject1', 'Subject2'],
            'isotype': ['IgG', 'IgM'],
            'rows': [5, 4],
            'total_sequences': [5, 4]
        })
        
        metadata_path = data_dir / "metadata.parquet"
        metadata.to_parquet(metadata_path, index=False)
        
        return str(metadata_path)
    
    def test_database_selection_unpaired(self, mock_unpaired_data):
        """Test 1: Database selection selects correct unpaired database."""
        data_dir, mock_data = mock_unpaired_data
        
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test schema detection
        assert engine.schema['search_type'] == 'unpaired'
        assert engine.schema['heavy_chain'] == False
        assert engine.schema['light_chain'] == False
        assert 'v_call' in engine.schema['chain_columns']
        assert 'cdr1_aa' in engine.schema['chain_columns']
        
        # Test total sequences count
        assert engine.total_sequences == len(mock_data)
        
        engine.close()
    
    def test_database_selection_paired(self, mock_paired_data):
        """Test 1: Database selection selects correct paired database."""
        data_dir, mock_data = mock_paired_data
        
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test schema detection
        assert engine.schema['search_type'] == 'paired'
        assert engine.schema['heavy_chain'] == True
        assert engine.schema['light_chain'] == True
        assert 'v_call_heavy' in engine.schema['chain_columns']['v_call']
        assert 'v_call_light' in engine.schema['chain_columns']['v_call']
        
        # Test total sequences count
        assert engine.total_sequences == len(mock_data)
        
        engine.close()
    
    def test_v_gene_search_unpaired(self, mock_unpaired_data):
        """Test 2: V gene search in unpaired data."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test single V gene
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23")
        assert stats['total_hits'] == 2  # Two sequences with IGHV3-23
        
        # Test multiple V genes with comma separator
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23,1-69")
        assert stats['total_hits'] == 4  # All sequences
        
        # Test multiple V genes with pipe separator
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23|1-69")
        assert stats['total_hits'] == 4  # All sequences
        
        # Test family search (just number)
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3")
        assert stats['total_hits'] == 2  # Two sequences with IGHV3-*
        
        engine.close()
    
    def test_d_gene_search_unpaired(self, mock_unpaired_data):
        """Test 2: D gene search in unpaired data."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test single D gene
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_d="3-10")
        assert stats['total_hits'] == 2  # Two sequences with IGHD3-10
        
        # Test multiple D genes
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_d="3-10,2-2")
        assert stats['total_hits'] == 4  # All sequences
        
        engine.close()
    
    def test_j_gene_search_unpaired(self, mock_unpaired_data):
        """Test 2: J gene search in unpaired data."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test J gene with J prefix
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_j="J4")
        assert stats['total_hits'] == 3  # Three sequences with IGHJ4
        
        # Test J gene without J prefix (should auto-add)
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_j="4")
        assert stats['total_hits'] == 3  # Three sequences with IGHJ4
        
        # Test multiple J genes
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_j="J4|J6")
        assert stats['total_hits'] == 5  # All sequences
        
        engine.close()
    
    def test_light_chain_v_gene_search_unpaired(self, mock_light_unpaired_data):
        """Test 2: Light-chain V gene search in unpaired data."""
        data_dir, mock_data = mock_light_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        results_df, stats_df, stats = engine.search(chain_mode="light", light_v="2")
        assert stats['total_hits'] == 2  # Matches both lambda and kappa family 2 genes
        
        results_df, stats_df, stats = engine.search(chain_mode="light", light_v="L2")
        assert stats['total_hits'] == 1  # Lambda-only prefix
        
        results_df, stats_df, stats = engine.search(chain_mode="light", light_v="K2")
        assert stats['total_hits'] == 1  # Kappa-only prefix
        
        results_df, stats_df, stats = engine.search(chain_mode="light", light_v="IGLV2-14*01")
        assert stats['total_hits'] == 1  # Exact allele match
        
        engine.close()
    
    def test_light_chain_j_gene_search_unpaired(self, mock_light_unpaired_data):
        """Test 2: Light-chain J gene search in unpaired data."""
        data_dir, mock_data = mock_light_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        results_df, stats_df, stats = engine.search(chain_mode="light", light_j="2")
        assert stats['total_hits'] == 2  # Matches both lambda and kappa family 2 J genes
        
        results_df, stats_df, stats = engine.search(chain_mode="light", light_j="L2")
        assert stats['total_hits'] == 1  # Lambda-only prefix
        
        results_df, stats_df, stats = engine.search(chain_mode="light", light_j="K2")
        assert stats['total_hits'] == 1  # Kappa-only prefix
        
        engine.close()
    
    def test_cdr_length_search_unpaired(self, mock_unpaired_data):
        """Test 2: CDR length search in unpaired data."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test CDR1 length
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr1_length=5)
        assert stats['total_hits'] == 5  # All sequences have CDR1 length 5
        
        # Test CDR2 length
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr2_length=5)
        assert stats['total_hits'] == 5  # All sequences have CDR2 length 5
        
        # Test CDR3 length
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr3_length=6)
        assert stats['total_hits'] == 5  # All sequences have CDR3 length 6
        
        # Test non-matching length
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr1_length=10)
        assert stats['total_hits'] == 0  # No sequences have CDR1 length 10
        
        engine.close()
    
    def test_cdr_motif_search_unpaired(self, mock_unpaired_data):
        """Test 2: CDR motif search in unpaired data."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test exact CDR1 motif
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr1_motif="ARSSS")
        assert stats['total_hits'] == 5  # All sequences have this CDR1 motif
        
        # Test partial CDR1 motif
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr1_motif="ARS*")
        assert stats['total_hits'] == 5  # All sequences match this pattern
        
        # Test CDR2 motif
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr2_motif="ISSGG")
        assert stats['total_hits'] == 5  # All sequences have this CDR2 motif
        
        # Test CDR3 motif
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr3_motif="CARGGY")
        assert stats['total_hits'] == 5  # All sequences have this CDR3 motif
        
        # Test non-matching motif
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr1_motif="XXXXX")
        assert stats['total_hits'] == 0  # No sequences match this motif
        
        engine.close()
    
    def test_combined_search_unpaired(self, mock_unpaired_data):
        """Test 2: Combined search fields in unpaired data."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test V gene + CDR length combination
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23", heavy_cdr3_length=6)
        assert stats['total_hits'] == 2  # Two sequences match both criteria
        
        # Test V gene + D gene + J gene combination
        results_df, stats_df, stats = engine.search(
            chain_mode="heavy",
            heavy_v="3-23",
            heavy_d="3-10",
            heavy_j="J4"
        )
        assert stats['total_hits'] == 2  # Two sequences match all three
        
        # Test all criteria combination
        results_df, stats_df, stats = engine.search(
            chain_mode="heavy",
            heavy_v="3-23",
            heavy_d="3-10",
            heavy_j="J4",
            heavy_cdr1_length=5,
            heavy_cdr2_length=5,
            heavy_cdr3_length=6,
            heavy_cdr1_motif="ARSSS",
            heavy_cdr2_motif="ISSGG",
            heavy_cdr3_motif="CARGGY"
        )
        assert stats['total_hits'] == 2  # One sequence matches all criteria
        
        engine.close()
    
    def test_heavy_chain_search_paired(self, mock_paired_data):
        """Test 2: Heavy chain search in paired data."""
        data_dir, mock_data = mock_paired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test heavy V gene
        results_df, stats_df, stats = engine.search(heavy_v="3-23")
        assert stats['total_hits'] == 2  # Two sequences with IGHV3-23
        
        # Test heavy D gene
        results_df, stats_df, stats = engine.search(heavy_d="3-10")
        assert stats['total_hits'] == 2  # Two sequences with IGHD3-10
        
        # Test heavy J gene
        results_df, stats_df, stats = engine.search(heavy_j="J4")
        assert stats['total_hits'] == 3  # Three sequences with IGHJ4
        
        # Test heavy CDR lengths
        results_df, stats_df, stats = engine.search(heavy_cdr1_length=5)
        assert stats['total_hits'] == 4  # All sequences have CDR1 length 5
        
        # Test heavy CDR motifs
        results_df, stats_df, stats = engine.search(heavy_cdr3_motif="CARGGY")
        assert stats['total_hits'] == 4  # All sequences have this CDR3 motif
        
        engine.close()
    
    def test_light_chain_search_paired(self, mock_paired_data):
        """Test 2: Light chain search in paired data."""
        data_dir, mock_data = mock_paired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test light V gene
        results_df, stats_df, stats = engine.search(light_v="1-39")
        assert stats['total_hits'] == 2  # Two sequences with IGKV1-39
        
        # Test light J gene
        results_df, stats_df, stats = engine.search(light_j="J1")
        assert stats['total_hits'] == 2  # Two sequences with IGKJ1
        
        # Test light CDR lengths
        results_df, stats_df, stats = engine.search(light_cdr1_length=5)
        assert stats['total_hits'] == 4  # All sequences have CDR1 length 5
        
        # Test light CDR motifs
        results_df, stats_df, stats = engine.search(light_cdr3_motif="QQYST")
        assert stats['total_hits'] == 4  # All sequences have this CDR3 motif
        
        engine.close()
    
    def test_combined_heavy_light_search_paired(self, mock_paired_data):
        """Test 2: Combined heavy and light chain search in paired data."""
        data_dir, mock_data = mock_paired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test heavy + light V genes
        results_df, stats_df, stats = engine.search(heavy_v="3-23", light_v="1-39")
        assert stats['total_hits'] == 1  # One sequence matches both heavy and light V genes
        
        # Test heavy + light CDR lengths
        results_df, stats_df, stats = engine.search(heavy_cdr3_length=6, light_cdr3_length=5)
        assert stats['total_hits'] == 4  # All sequences match both CDR3 lengths
        
        # Test complex combination
        results_df, stats_df, stats = engine.search(
            heavy_v="3-23",
            heavy_d="3-10",
            heavy_j="J4",
            light_v="1-39",
            light_j="J1",
            heavy_cdr3_length=6,
            light_cdr3_length=5
        )
        assert stats['total_hits'] == 1  # One sequence matches all criteria
        
        engine.close()
    
    def test_full_results_vs_statistics(self, mock_unpaired_data):
        """Test 2: Full results vs statistics-only mode."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test statistics-only mode (default)
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23")
        assert len(results_df.columns) >= 2  # At least subject and hits columns
        assert 'subject' in results_df.columns
        assert 'hits' in results_df.columns
        
        # Test full results mode
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23", full_results=True)
        assert len(results_df.columns) > 2  # All columns returned
        assert 'v_call' in results_df.columns
        assert 'cdr3_aa' in results_df.columns
        
        engine.close()
    
    def test_limit_parameter(self, mock_unpaired_data):
        """Test 2: Limit parameter functionality."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test with limit
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23", full_results=True, limit=1)
        assert len(results_df) <= 1  # Should respect limit
        
        # Test without limit
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23", full_results=True)
        assert len(results_df) == 2  # All matching sequences
        
        engine.close()
    
    def test_download_functionality(self, mock_unpaired_data):
        """Test 3: Downloaded files are correct."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test that search results can be converted to downloadable format
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23", full_results=True)
        
        # Verify results contain expected columns for download
        expected_columns = ['subject', 'v_call', 'd_call', 'j_call', 'cdr1_aa', 'cdr2_aa', 'cdr3_aa']
        for col in expected_columns:
            assert col in results_df.columns
        
        # Test CSV export capability
        csv_content = results_df.to_csv(index=False)
        assert 'Subject1' in csv_content
        assert 'IGHV3-23' in csv_content
        
        # Test that all returned sequences match search criteria
        for _, row in results_df.iterrows():
            assert 'IGHV3-23' in row['v_call']
        
        engine.close()
    
    def test_metadata_functionality(self, mock_unpaired_data, mock_metadata):
        """Test metadata file handling."""
        data_dir, mock_data = mock_unpaired_data
        
        # Test that metadata is created/used correctly
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test metadata query
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23")
        
        # Verify statistics include percentage calculations
        if not results_df.empty:
            assert 'percentage' in results_df.columns or 'per_million' in results_df.columns
        
        engine.close()
    
    def test_edge_cases_and_error_handling(self, temp_dir):
        """Test 4: Edge cases and error handling."""
        
        # Test with non-existent directory
        with pytest.raises(FileNotFoundError):
            AntibodySearchEngine(data_dir="/non/existent/path")
        
        # Test with empty directory
        empty_dir = Path(temp_dir) / "empty"
        empty_dir.mkdir()
        
        with pytest.raises(FileNotFoundError):
            AntibodySearchEngine(data_dir=str(empty_dir))
        
        # Test with invalid parquet files
        invalid_dir = Path(temp_dir) / "invalid"
        invalid_dir.mkdir()
        
        # Create invalid parquet file
        invalid_file = invalid_dir / "invalid.parquet"
        with open(invalid_file, 'w') as f:
            f.write("not a parquet file")
        
        with pytest.raises(Exception):  # Should handle invalid parquet gracefully
            AntibodySearchEngine(data_dir=str(invalid_dir))
    
    def test_gene_pattern_building(self, mock_unpaired_data):
        """Test gene pattern building functionality."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test different gene pattern formats
        test_cases = [
            ("3", "IGHV3-%"),  # Family search
            ("3-", "IGHV3-%"),  # Family search with dash
            ("3-23", "IGHV3-23*%"),  # Gene search
            ("3-23*01", "IGHV3-23*01%"),  # Allele search
        ]
        
        for gene_input, expected_pattern in test_cases:
            pattern = engine._build_gene_pattern('v_call', gene_input)
            assert expected_pattern in pattern
        
        engine.close()
    
    def test_available_genes_functionality(self, mock_unpaired_data):
        """Test get_available_genes functionality."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        genes = engine.get_available_genes()
        
        assert 'v_genes' in genes
        assert 'd_genes' in genes
        assert 'j_genes' in genes
        
        # Verify genes are sorted
        assert genes['v_genes'] == sorted(genes['v_genes'])
        assert genes['d_genes'] == sorted(genes['d_genes'])
        assert genes['j_genes'] == sorted(genes['j_genes'])
        
        engine.close()
    
    def test_database_info_functionality(self, mock_unpaired_data):
        """Test get_database_info functionality."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        info = engine.get_database_info()
        
        assert 'data_dir' in info
        assert 'db_path' in info
        assert 'total_sequences' in info
        assert 'is_memory_db' in info
        
        assert info['total_sequences'] == len(mock_data)
        assert info['is_memory_db'] == True  # Default is memory database
        
        engine.close()
    
    def test_force_rebuild_metadata(self, mock_unpaired_data):
        """Test force_rebuild_metadata functionality."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test force rebuild (should not raise exception)
        engine.force_rebuild_metadata()
        
        # Verify rebuild keeps totals intact
        assert engine.total_sequences == len(mock_data)
        
        engine.close()
    
    def test_progress_callback(self, mock_unpaired_data):
        """Test progress callback functionality."""
        data_dir, mock_data = mock_unpaired_data
        
        # Mock progress callback
        progress_calls = []
        def mock_callback(progress, status):
            progress_calls.append((progress, status))
        
        engine = AntibodySearchEngine(data_dir=data_dir, progress_callback=mock_callback)
        
        # Verify progress was called
        assert len(progress_calls) > 0
        assert progress_calls[0][0] == 0.0  # First call should be 0.0
        assert progress_calls[-1][0] == 1.0  # Last call should be 1.0
        
        engine.close()
    
    def test_memory_vs_file_database(self, mock_unpaired_data, temp_dir):
        """Test memory vs file database functionality."""
        data_dir, mock_data = mock_unpaired_data
        
        # Test memory database (default)
        engine_memory = AntibodySearchEngine(data_dir=data_dir, db_path=":memory:")
        assert engine_memory.get_database_info()['is_memory_db'] == True
        engine_memory.close()
        
        # Test file database
        temp_db = Path(temp_dir) / "test.db"
        engine_file = AntibodySearchEngine(data_dir=data_dir, db_path=str(temp_db))
        assert engine_file.get_database_info()['is_memory_db'] == False
        assert temp_db.exists()
        engine_file.close()
    
    def test_search_performance_timing(self, mock_unpaired_data):
        """Test search performance timing."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test that search timing is recorded
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="3-23")
        
        assert 'search_time' in stats
        assert isinstance(stats['search_time'], (int, float))
        assert stats['search_time'] >= 0
        
        engine.close()
    
    def test_empty_search_results(self, mock_unpaired_data):
        """Test handling of empty search results."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test search with no matches
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_v="999-999")
        
        assert stats['total_hits'] == 0
        assert stats['percentage'] == 0
        assert len(results_df) == 0
        
        engine.close()
    
    def test_special_characters_in_motifs(self, mock_unpaired_data):
        """Test handling of special characters in CDR motifs."""
        data_dir, mock_data = mock_unpaired_data
        engine = AntibodySearchEngine(data_dir=data_dir)
        
        # Test motifs with special regex characters
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr1_motif="AR.S*")
        assert stats['total_hits'] >= 0  # Should not crash
        
        # Test motifs with wildcards
        results_df, stats_df, stats = engine.search(chain_mode="heavy", heavy_cdr1_motif="AR*")
        assert stats['total_hits'] >= 0  # Should not crash
        
        engine.close()


if __name__ == "__main__":
    pytest.main([__file__])
