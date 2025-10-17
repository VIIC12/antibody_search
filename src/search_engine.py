"""
DuckDB-based search engine for antibody sequences.

This module provides high-performance searching using DuckDB's
analytical query engine on Parquet files.
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re

import duckdb
import pandas as pd

class AntibodySearchEngine:
    """High-performance antibody sequence search using DuckDB.
    Supports both paired and unpaired antibody data.
    """
    
    def __init__(self, data_dir: str = "data/parquet", progress_callback=None, db_path: str = ":memory:"):
        """
        Initialize search engine.
        
        Args:
            data_dir: Directory containing Parquet files (relative to V3.0/)
            progress_callback: Optional callback function(progress, status) for progress updates
            db_path: DuckDB database path (default: ":memory:" for in-memory database)
        """
        # Handle relative paths from V3.0 directory
        if not Path(data_dir).is_absolute():
            # Get the directory where this script is located
            script_dir = Path(__file__).parent.parent
            self.data_dir = script_dir / data_dir
        else:
            self.data_dir = Path(data_dir)
        
        # Connect to DuckDB with the specified database path
        self.conn = duckdb.connect(database=db_path)
        self.db_path = db_path
        
        # Detect database schema (paired vs unpaired)
        self.schema = self._detect_schema()
        
        # Register Parquet files as views
        self._register_data(progress_callback)
    
    def _detect_schema(self) -> Dict[str, Any]:
        """
        Detect database schema by examining column names.
        
        Returns:
            Dictionary with schema information:
            {
                'search_type': 'paired' | 'unpaired',
                'heavy_chain': bool,
                'light_chain': bool,
                'available_columns': List[str],
                'chain_columns': {
                    'v_call': ['v_call'] | ['v_call_heavy', 'v_call_light'],
                    'cdr3_aa': ['cdr3_aa'] | ['cdr3_aa_heavy', 'cdr3_aa_light'],
                    # ... etc
                }
            }
        """
        try:
            # Get a sample Parquet file to examine columns
            parquet_files = [f for f in self.data_dir.rglob("*.parquet") if f.name != 'metadata.parquet']
            if not parquet_files:
                return {'search_type': 'unknown', 'error': 'No parquet files found'}
            
            # Read column names from first file (very fast operation)
            # Use pyarrow to read just the schema without loading data
            import pyarrow.parquet as pq
            parquet_file = pq.ParquetFile(parquet_files[0])
            columns = parquet_file.schema.names
            
            # Detect schema type
            has_heavy_suffix = any('_heavy' in col for col in columns)
            has_light_suffix = any('_light' in col for col in columns)
            
            if has_heavy_suffix or has_light_suffix:
                search_type = 'paired'
            else:
                search_type = 'unpaired'
            
            # Map available columns
            chain_columns = {}
            base_columns = ['v_call', 'd_call', 'j_call', 'cdr1_aa', 'cdr2_aa', 'cdr3_aa']
            
            for base_col in base_columns:
                if search_type == 'paired':
                    heavy_col = f"{base_col}_heavy"
                    light_col = f"{base_col}_light"
                    chain_columns[base_col] = []
                    if heavy_col in columns:
                        chain_columns[base_col].append(heavy_col)
                    if light_col in columns:
                        chain_columns[base_col].append(light_col)
                else:
                    if base_col in columns:
                        chain_columns[base_col] = [base_col]
            
            # Add length columns
            length_columns = {}
            for base_col in ['cdr1_length', 'cdr2_length', 'cdr3_length']:
                if search_type == 'paired':
                    heavy_col = f"{base_col}_heavy"
                    light_col = f"{base_col}_light"
                    length_columns[base_col] = []
                    if heavy_col in columns:
                        length_columns[base_col].append(heavy_col)
                    if light_col in columns:
                        length_columns[base_col].append(light_col)
                else:
                    if base_col in columns:
                        length_columns[base_col] = [base_col]
            
            return {
                'search_type': search_type,
                'heavy_chain': has_heavy_suffix,
                'light_chain': has_light_suffix,
                'available_columns': columns,
                'chain_columns': chain_columns,
                'length_columns': length_columns
            }
            
        except Exception as e:
            return {'search_type': 'unknown', 'error': str(e)}
    
    def _register_data(self, progress_callback=None):
        """Register Parquet files as DuckDB views and rebuild metadata if needed."""
        if progress_callback:
            progress_callback(0.0, "Initializing search engine...")
        
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")
        
        if progress_callback:
            progress_callback(0.1, "Scanning for Parquet files...")
        
        # Register all parquet files from all isotype subdirectories
        parquet_files = [f for f in self.data_dir.rglob("*.parquet") if f.name != 'metadata.parquet']
        
        if not parquet_files:
            raise FileNotFoundError(f"No Parquet files found in {self.data_dir}")
        
        if progress_callback:
            progress_callback(0.2, f"Found {len(parquet_files)} Parquet files")
        
        # Create a view that reads all parquet files (excluding metadata.parquet)
        # Build a list of specific files to avoid schema conflicts
        if progress_callback:
            progress_callback(0.3, "Creating database view...")
        
        parquet_file_paths = [str(f) for f in parquet_files]
        parquet_files_str = "', '".join(parquet_file_paths)
        
        self.conn.execute(f"""
            CREATE OR REPLACE VIEW antibodies AS 
            SELECT *, filename as source_file FROM read_parquet(['{parquet_files_str}'], 
                                        union_by_name=true,
                                        filename=true)
        """)
        
        if progress_callback:
            progress_callback(0.4, "Checking metadata...")
        
        # Only rebuild metadata if needed
        self._ensure_metadata_up_to_date(parquet_files, progress_callback)
        
        if progress_callback:
            progress_callback(0.8, "Counting total sequences...")
        
        # Get row count
        result = self.conn.execute("SELECT COUNT(*) FROM antibodies").fetchone()
        self.total_sequences = result[0] if result else 0
        
        if progress_callback:
            progress_callback(1.0, "Search engine ready!")
        
        print(f"✓ Registered {len(parquet_files)} Parquet files")
        print(f"✓ Total sequences: {self.total_sequences:,}")
    
    def generate_similarity_pattern(self, motif: str, max_mismatches: int = 2) -> str:
        """
        Generate a regex pattern for similarity-based motif matching.
        
        Args:
            motif: The motif pattern (e.g., "YY.D.*G")
            max_mismatches: Maximum number of amino acid mismatches allowed (default: 2)
        
        Returns:
            A regex pattern that matches sequences with up to max_mismatches differences
        """
        if not motif:
            return ""
        
        # Define amino acid similarity groups (based on chemical properties)
        amino_acid_groups = {
            'A': '[AILV]',  # Aliphatic
            'C': '[C]',     # Cysteine (unique)
            'D': '[DE]',    # Acidic
            'E': '[DE]',    # Acidic
            'F': '[FWY]',   # Aromatic
            'G': '[G]',     # Glycine (unique)
            'H': '[H]',     # Histidine (unique)
            'I': '[AILV]',  # Aliphatic
            'K': '[KR]',    # Basic
            'L': '[AILV]',  # Aliphatic
            'M': '[M]',     # Methionine (unique)
            'N': '[NQ]',    # Amide
            'P': '[P]',     # Proline (unique)
            'Q': '[NQ]',    # Amide
            'R': '[KR]',    # Basic
            'S': '[ST]',    # Hydroxyl
            'T': '[ST]',    # Hydroxyl
            'V': '[AILV]',  # Aliphatic
            'W': '[FWY]',   # Aromatic
            'Y': '[FWY]',   # Aromatic
        }
        
        # Convert motif to regex pattern
        regex_pattern = ""
        i = 0
        while i < len(motif):
            char = motif[i].upper()
            
            if char == '*':
                # Wildcard - match any characters
                regex_pattern += '.*'
            elif char == '.':
                # Single character wildcard
                regex_pattern += '.'
            elif char in amino_acid_groups:
                # Amino acid - create similarity group
                if max_mismatches > 0:
                    # Allow the original amino acid or similar ones
                    original = f'[{char}]'
                    similar = amino_acid_groups[char]
                    # Create a pattern that matches either the original or similar amino acids
                    regex_pattern += f'({original}|{similar})'
                else:
                    # Exact match only
                    regex_pattern += f'[{char}]'
            else:
                # Other characters (shouldn't happen with validation)
                regex_pattern += re.escape(char)
            
            i += 1
        
        return regex_pattern
    
    def _ensure_metadata_up_to_date(self, parquet_files: list, progress_callback=None):
        """
        Ensure metadata.parquet exists and is up-to-date.
        Only rebuilds if necessary for efficiency.
        """
        # Look for metadata.parquet in the same directory as Parquet files
        # Check if Parquet files are directly in data_dir or in subdirectories
        parquet_files_in_root = list(self.data_dir.glob('*.parquet'))
        
        if parquet_files_in_root:
            # Case 1: Parquet files are directly in data_dir - look for metadata there
            metadata_path = self.data_dir / 'metadata.parquet'
        else:
            # Case 2: Parquet files are in subdirectories - look for metadata in first subdirectory
            subdirs = [d for d in self.data_dir.iterdir() if d.is_dir()]
            if subdirs:
                metadata_path = subdirs[0] / 'metadata.parquet'
            else:
                metadata_path = self.data_dir / 'metadata.parquet'
        
        # Check if metadata exists and is recent
        if metadata_path.exists():
            try:
                # Check if metadata is newer than all Parquet files
                metadata_mtime = metadata_path.stat().st_mtime
                newest_parquet_mtime = max(f.stat().st_mtime for f in parquet_files)
                
                if metadata_mtime >= newest_parquet_mtime:
                    print("✓ Using existing metadata.parquet")
                    return
                else:
                    print("🔄 Parquet files newer than metadata - rebuilding...")
            except Exception as e:
                print(f"⚠️  Error checking metadata age: {e} - rebuilding...")
        else:
            print("📝 No metadata.parquet found - creating...")
        
        # Rebuild metadata
        self._rebuild_metadata(parquet_files, progress_callback)
    
    def _rebuild_metadata(self, parquet_files: list, progress_callback=None):
        """
        Rebuild metadata.parquet with current database state.
        
        This is called automatically when initializing the search engine,
        ensuring metadata is always in sync with actual files.
        
        Args:
            parquet_files: List of Parquet files to process
            progress_callback: Optional callback function(progress, status) for progress updates
        """
        import pyarrow.parquet as pq
        
        metadata_records = []
        total_files = len(parquet_files)
        
        for i, pfile in enumerate(parquet_files):
            if progress_callback:
                progress_callback(i / total_files, f"Processing files... ({i+1}/{total_files})")
            try:
                # Read only file metadata (very fast - no data loading)
                parquet_file = pq.ParquetFile(pfile)
                num_rows = parquet_file.metadata.num_rows
                
                # Read only the first row to get subject and isotype (much faster)
                first_batch = parquet_file.read_row_group(0, columns=['subject', 'isotype'])
                subject = first_batch.column('subject').to_pylist()[0] if 'subject' in first_batch.column_names else 'Unknown'
                isotype = first_batch.column('isotype').to_pylist()[0] if 'isotype' in first_batch.column_names else pfile.parent.name
                
                metadata_records.append({
                    'filename': pfile.name,
                    'subject': subject,
                    'isotype': isotype,
                    'rows': num_rows,
                    'total_sequences': num_rows,  # Same as rows for our purposes
                })
            except Exception as e:
                print(f"Warning: Could not read metadata from {pfile.name}: {e}")
                continue
        
        if metadata_records:
            if progress_callback:
                progress_callback(0.9, "Creating metadata files...")
            
            import pandas as pd
            metadata_df = pd.DataFrame(metadata_records)
            
            # Create single metadata file in the same directory as Parquet files
            metadata_path = self.data_dir / 'metadata.parquet'
            metadata_df.to_parquet(metadata_path, index=False)
            print(f"✓ Updated metadata ({len(metadata_df)} files)")
            
            if progress_callback:
                progress_callback(1.0, "Complete!")
    
    def force_rebuild_metadata(self, progress_callback=None):
        """
        Force rebuild metadata.parquet regardless of file timestamps.
        Useful for manual refresh or when metadata might be corrupted.
        
        Args:
            progress_callback: Optional callback function(progress, status) for progress updates
        """
        parquet_files = list(self.data_dir.rglob('*.parquet'))
        # Filter out metadata.parquet itself
        parquet_files = [f for f in parquet_files if f.name != 'metadata.parquet']
        
        if parquet_files:
            print("🔄 Force rebuilding metadata.parquet...")
            self._rebuild_metadata(parquet_files, progress_callback)
        else:
            print("⚠️  No Parquet files found to build metadata from")
    
    def _build_gene_pattern(self, column: str, gene: str) -> str:
        """
        Build SQL pattern for gene matching.
        
        Handles:
        - "3" → matches IGHV3-* (not IGHV4-34 or IGHV33-*)
        - "3-" → matches IGHV3-* 
        - "3-23" → matches IGHV3-23*
        - "3-23*01" → matches exact allele
        
        Args:
            column: Column name (v_call, d_call, j_call)
            gene: Gene pattern to match
            
        Returns:
            SQL WHERE condition
        """
        gene = gene.strip()
        
        # If just a number (e.g., "3"), auto-add dash to match family
        if gene.isdigit():
            gene = gene + '-'
        
        # Determine if this is a light chain column
        is_light_chain = '_light' in column
        
        # Build pattern that matches gene correctly
        # For v_call: Match IGHV3- but not IGHV4-34 or IGHV33-
        # Strategy: Match pattern immediately after IGHV/IGHD/IGHJ prefix
        
        # Escape special regex characters except * (wildcard)
        gene_escaped = gene.replace('*', '.*')
        
        # Match: IGHV3-23 or IGHD3-10 etc., but not 4-34 or 33-
        # Use precise pattern: gene must be followed by * (allele) or end of string
        if gene.endswith('-'):
            # Family search (e.g., "3-"): match IGHV3-* but not IGHV33-*
            if is_light_chain:
                pattern = f"IGKV{gene}%"
                d_pattern = f"IGKD{gene}%"  # Light chains don't have D genes typically
                j_pattern = f"IGKJ{gene}%"
            else:
                pattern = f"IGHV{gene}%"
                d_pattern = f"IGHD{gene}%"
                j_pattern = f"IGHJ{gene}%"
        elif '-' in gene and not gene.endswith('*'):
            # Gene search (e.g., "3-3"): match IGHV3-3* but not IGHV3-33*
            # Add * to ensure it matches allele or end of string
            if is_light_chain:
                pattern = f"IGKV{gene}*%"
                d_pattern = f"IGKD{gene}*%"  # Light chains don't have D genes typically
                j_pattern = f"IGKJ{gene}*%"
            else:
                pattern = f"IGHV{gene}*%"
                d_pattern = f"IGHD{gene}*%"
                j_pattern = f"IGHJ{gene}*%"
        else:
            # Exact match or already has wildcard
            if is_light_chain:
                pattern = f"IGKV{gene}%"
                d_pattern = f"IGKD{gene}%"  # Light chains don't have D genes typically
                j_pattern = f"IGKJ{gene}%"
            else:
                pattern = f"IGHV{gene}%"
                d_pattern = f"IGHD{gene}%"
                j_pattern = f"IGHJ{gene}%"
        
        return f"({column} LIKE '{pattern}' OR {column} LIKE '{d_pattern}' OR {column} LIKE '{j_pattern}')"
    
    def search(
        self,
        # Unpaired parameters (backward compatibility)
        ighv: str = "",
        ighd: str = "",
        ighj: str = "",
        cdr1_length: Optional[int] = None,
        cdr2_length: Optional[int] = None,
        cdr3_length: Optional[int] = None,
        cdr1_motif: str = "",
        cdr2_motif: str = "",
        cdr3_motif: str = "",
        cdr1_similarity: bool = False,
        cdr2_similarity: bool = False,
        cdr3_similarity: bool = False,
        cdr1_mismatches: int = 2,
        cdr2_mismatches: int = 2,
        cdr3_mismatches: int = 2,
        # Paired parameters
        heavy_v: str = "",
        heavy_d: str = "",
        heavy_j: str = "",
        heavy_cdr1_length: Optional[int] = None,
        heavy_cdr2_length: Optional[int] = None,
        heavy_cdr3_length: Optional[int] = None,
        heavy_cdr1_motif: str = "",
        heavy_cdr2_motif: str = "",
        heavy_cdr3_motif: str = "",
        heavy_cdr1_similarity: bool = False,
        heavy_cdr2_similarity: bool = False,
        heavy_cdr3_similarity: bool = False,
        light_v: str = "",
        light_d: str = "",
        light_j: str = "",
        light_cdr1_length: Optional[int] = None,
        light_cdr2_length: Optional[int] = None,
        light_cdr3_length: Optional[int] = None,
        light_cdr1_motif: str = "",
        light_cdr2_motif: str = "",
        light_cdr3_motif: str = "",
        light_cdr1_similarity: bool = False,
        light_cdr2_similarity: bool = False,
        light_cdr3_similarity: bool = False,
        # Common parameters
        full_results: bool = False,
        limit: Optional[int] = None
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Search for antibody sequences matching criteria.
        Supports both paired and unpaired data based on database schema.
        
        Args:
            # Unpaired parameters (for backward compatibility)
            ighv, ighd, ighj: V, D, J genes
            cdr1_length, cdr2_length, cdr3_length: CDR lengths
            cdr1_motif, cdr2_motif, cdr3_motif: CDR motifs
            cdr1_similarity, cdr2_similarity, cdr3_similarity: Enable similarity search for CDR motifs
            
            # Paired parameters
            heavy_v, heavy_d, heavy_j: Heavy chain genes
            heavy_cdr1_length, heavy_cdr2_length, heavy_cdr3_length: Heavy chain CDR lengths
            heavy_cdr1_motif, heavy_cdr2_motif, heavy_cdr3_motif: Heavy chain CDR motifs
            heavy_cdr1_similarity, heavy_cdr2_similarity, heavy_cdr3_similarity: Enable similarity search for heavy chain CDR motifs
            light_v, light_d, light_j: Light chain genes
            light_cdr1_length, light_cdr2_length, light_cdr3_length: Light chain CDR lengths
            light_cdr1_motif, light_cdr2_motif, light_cdr3_motif: Light chain CDR motifs
            light_cdr1_similarity, light_cdr2_similarity, light_cdr3_similarity: Enable similarity search for light chain CDR motifs
            
            # Common parameters
            full_results: Return full sequence data (vs statistics only)
            limit: Maximum number of results to return
            
        Returns:
            Tuple of (results_df, statistics_dict)
        """
        start_time = time.time()
        
        # Determine search type based on schema and provided parameters
        if self.schema['search_type'] == 'paired':
            return self._search_paired(
                heavy_v, heavy_d, heavy_j,
                heavy_cdr1_length, heavy_cdr2_length, heavy_cdr3_length,
                heavy_cdr1_motif, heavy_cdr2_motif, heavy_cdr3_motif,
                heavy_cdr1_similarity, heavy_cdr2_similarity, heavy_cdr3_similarity,
                heavy_cdr1_mismatches, heavy_cdr2_mismatches, heavy_cdr3_mismatches,
                light_v, light_d, light_j,
                light_cdr1_length, light_cdr2_length, light_cdr3_length,
                light_cdr1_motif, light_cdr2_motif, light_cdr3_motif,
                light_cdr1_similarity, light_cdr2_similarity, light_cdr3_similarity,
                light_cdr1_mismatches, light_cdr2_mismatches, light_cdr3_mismatches,
                full_results, limit, start_time
            )
        else:
            return self._search_unpaired(
                ighv, ighd, ighj,
                cdr1_length, cdr2_length, cdr3_length,
                cdr1_motif, cdr2_motif, cdr3_motif,
                cdr1_similarity, cdr2_similarity, cdr3_similarity,
                cdr1_mismatches, cdr2_mismatches, cdr3_mismatches,
                full_results, limit, start_time
            )
    
    def _search_unpaired(
        self,
        ighv: str = "",
        ighd: str = "",
        ighj: str = "",
        cdr1_length: Optional[int] = None,
        cdr2_length: Optional[int] = None,
        cdr3_length: Optional[int] = None,
        cdr1_motif: str = "",
        cdr2_motif: str = "",
        cdr3_motif: str = "",
        cdr1_similarity: bool = False,
        cdr2_similarity: bool = False,
        cdr3_similarity: bool = False,
        cdr1_mismatches: int = 2,
        cdr2_mismatches: int = 2,
        cdr3_mismatches: int = 2,
        full_results: bool = False,
        limit: Optional[int] = None,
        start_time: float = None
    ) -> Tuple[pd.DataFrame, Dict]:
        """Search unpaired data (original implementation)."""
        if start_time is None:
            start_time = time.time()
        
        # Build WHERE clause
        conditions = []
        
        if ighv:
            separator = ',' if ',' in ighv else '|'
            if separator in ighv:
                ighv_conditions = [self._build_gene_pattern('v_call', g) for g in ighv.split(separator)]
                conditions.append(f"({' OR '.join(ighv_conditions)})")
            else:
                conditions.append(self._build_gene_pattern('v_call', ighv))
        
        if ighd:
            separator = ',' if ',' in ighd else '|'
            if separator in ighd:
                ighd_conditions = [self._build_gene_pattern('d_call', g) for g in ighd.split(separator)]
                conditions.append(f"({' OR '.join(ighd_conditions)})")
            else:
                conditions.append(self._build_gene_pattern('d_call', ighd))
        
        if ighj:
            if not ighj.startswith('J'):
                ighj = f"J{ighj}"
            if '|' in ighj:
                ighj_conditions = [f"j_call LIKE '%{g}%'" for g in ighj.split('|')]
                conditions.append(f"({' OR '.join(ighj_conditions)})")
            else:
                conditions.append(f"j_call LIKE '%{ighj}%'")
        
        if cdr1_length is not None:
            conditions.append(f"cdr1_length = {cdr1_length}")
        
        if cdr2_length is not None:
            conditions.append(f"cdr2_length = {cdr2_length}")
        
        if cdr3_length is not None:
            conditions.append(f"cdr3_length = {cdr3_length}")
        
        # Helper function to convert SQL LIKE wildcards to regex patterns
        def convert_motif_to_regex(motif):
            if not motif:
                return ""
            regex_pattern = motif
            regex_pattern = re.sub(r'(?<!\.)\*(?!\*)', '.*', regex_pattern)
            regex_pattern = re.escape(regex_pattern)
            regex_pattern = regex_pattern.replace(r'\.\*', '.*')
            return regex_pattern
        
        if cdr1_motif:
            if cdr1_similarity:
                regex_pattern = self.generate_similarity_pattern(cdr1_motif, cdr1_mismatches)
            else:
                regex_pattern = convert_motif_to_regex(cdr1_motif)
            conditions.append(f"cdr1_aa ~ '{regex_pattern}'")
        
        if cdr2_motif:
            if cdr2_similarity:
                regex_pattern = self.generate_similarity_pattern(cdr2_motif, cdr2_mismatches)
            else:
                regex_pattern = convert_motif_to_regex(cdr2_motif)
            conditions.append(f"cdr2_aa ~ '{regex_pattern}'")
        
        if cdr3_motif:
            if cdr3_similarity:
                regex_pattern = self.generate_similarity_pattern(cdr3_motif, cdr3_mismatches)
            else:
                regex_pattern = convert_motif_to_regex(cdr3_motif)
            conditions.append(f"cdr3_aa ~ '{regex_pattern}'")
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        if full_results:
            # Return full sequence data
            query = f"""
                SELECT *
                FROM antibodies
                WHERE {where_clause}
                {f'LIMIT {limit}' if limit else ''}
            """
            results_df = self.conn.execute(query).df()
            
            # Get subject statistics
            stats_query = f"""
                SELECT 
                    subject,
                    COUNT(*) as hits,
                    COUNT(DISTINCT source_file) as num_files
                FROM antibodies
                WHERE {where_clause}
                GROUP BY subject
            """
            stats_df = self.conn.execute(stats_query).df()
            
        else:
            # Return statistics only (much faster)
            query = f"""
                SELECT 
                    subject,
                    COUNT(*) as hits
                FROM antibodies
                WHERE {where_clause}
                GROUP BY subject
            """
            results_df = self.conn.execute(query).df()
            stats_df = results_df
        
        # Calculate overall statistics
        total_hits = int(stats_df['hits'].sum()) if not stats_df.empty else 0
        
        # Get total sequences per subject from metadata.parquet (fast!)
        # This is pre-computed during initialization, so it's very fast even with 1B sequences
        # Look for metadata file in the same directory as Parquet files
        # Check if Parquet files are directly in data_dir or in subdirectories
        parquet_files_in_root = list(self.data_dir.glob('*.parquet'))
        
        if parquet_files_in_root:
            # Case 1: Parquet files are directly in data_dir - look for metadata there
            metadata_path = self.data_dir / 'metadata.parquet'
        else:
            # Case 2: Parquet files are in subdirectories - look for metadata in first subdirectory
            subdirs = [d for d in self.data_dir.iterdir() if d.is_dir()]
            if subdirs:
                metadata_path = subdirs[0] / 'metadata.parquet'
            else:
                metadata_path = self.data_dir / 'metadata.parquet'
        
        metadata_query = f"""
            SELECT subject, SUM(total_sequences) as total
            FROM read_parquet('{metadata_path}')
            GROUP BY subject
        """
        
        try:
            total_seqs_df = self.conn.execute(metadata_query).df()
            
            # Merge with results
            if not stats_df.empty and not total_seqs_df.empty:
                stats_df = stats_df.merge(
                    total_seqs_df, 
                    on='subject', 
                    how='left'
                ).fillna(0)
                
                # Calculate percentages
                stats_df['percentage'] = (
                    stats_df['hits'] / stats_df['total'] * 100
                ).round(2)
                stats_df['per_million'] = (
                    stats_df['hits'] / stats_df['total'] * 1000000
                ).round(0)
                
                # Rename for display
                stats_df = stats_df.rename(columns={'total': 'total_sequences'})
        except Exception as e:
            # If metadata not available, just use hits (no percentages)
            pass
        
        search_time = time.time() - start_time
        
        statistics = {
            'total_hits': total_hits,
            'total_sequences': self.total_sequences,
            'percentage': round(total_hits / self.total_sequences * 100, 2) if self.total_sequences > 0 else 0,
            'search_time': round(search_time, 2),
            'query_params': {
                'ighv': ighv,
                'ighd': ighd,
                'ighj': ighj,
                'cdr1_length': cdr1_length,
                'cdr2_length': cdr2_length,
                'cdr3_length': cdr3_length,
                'cdr1_motif': cdr1_motif,
                'cdr2_motif': cdr2_motif,
                'cdr3_motif': cdr3_motif,
                'cdr1_similarity': cdr1_similarity,
                'cdr2_similarity': cdr2_similarity,
                'cdr3_similarity': cdr3_similarity,
                'cdr1_mismatches': cdr1_mismatches,
                'cdr2_mismatches': cdr2_mismatches,
                'cdr3_mismatches': cdr3_mismatches
            }
        }
        
        return results_df if full_results else stats_df, statistics
    
    def _search_paired(
        self,
        heavy_v: str = "",
        heavy_d: str = "",
        heavy_j: str = "",
        heavy_cdr1_length: Optional[int] = None,
        heavy_cdr2_length: Optional[int] = None,
        heavy_cdr3_length: Optional[int] = None,
        heavy_cdr1_motif: str = "",
        heavy_cdr2_motif: str = "",
        heavy_cdr3_motif: str = "",
        heavy_cdr1_similarity: bool = False,
        heavy_cdr2_similarity: bool = False,
        heavy_cdr3_similarity: bool = False,
        heavy_cdr1_mismatches: int = 2,
        heavy_cdr2_mismatches: int = 2,
        heavy_cdr3_mismatches: int = 2,
        light_v: str = "",
        light_d: str = "",
        light_j: str = "",
        light_cdr1_length: Optional[int] = None,
        light_cdr2_length: Optional[int] = None,
        light_cdr3_length: Optional[int] = None,
        light_cdr1_motif: str = "",
        light_cdr2_motif: str = "",
        light_cdr3_motif: str = "",
        light_cdr1_similarity: bool = False,
        light_cdr2_similarity: bool = False,
        light_cdr3_similarity: bool = False,
        light_cdr1_mismatches: int = 2,
        light_cdr2_mismatches: int = 2,
        light_cdr3_mismatches: int = 2,
        full_results: bool = False,
        limit: Optional[int] = None,
        start_time: float = None
    ) -> Tuple[pd.DataFrame, Dict]:
        """Search paired data with separate heavy and light chain criteria."""
        if start_time is None:
            start_time = time.time()
        
        conditions = []
        
        # Helper function to convert SQL LIKE wildcards to regex patterns
        def convert_motif_to_regex(motif):
            if not motif:
                return ""
            import re
            regex_pattern = motif
            regex_pattern = re.sub(r'(?<!\.)\*(?!\*)', '.*', regex_pattern)
            regex_pattern = re.escape(regex_pattern)
            regex_pattern = regex_pattern.replace(r'\.\*', '.*')
            return regex_pattern
        
        # Heavy chain conditions
        if heavy_v:
            separator = ',' if ',' in heavy_v else '|'
            if separator in heavy_v:
                heavy_v_conditions = []
                for g in heavy_v.split(separator):
                    for col in self.schema['chain_columns']['v_call']:
                        if '_heavy' in col:
                            heavy_v_conditions.append(self._build_gene_pattern(col, g))
                if heavy_v_conditions:
                    conditions.append(f"({' OR '.join(heavy_v_conditions)})")
            else:
                heavy_v_conditions = []
                for col in self.schema['chain_columns']['v_call']:
                    if '_heavy' in col:
                        heavy_v_conditions.append(self._build_gene_pattern(col, heavy_v))
                if heavy_v_conditions:
                    conditions.append(f"({' OR '.join(heavy_v_conditions)})")
        
        if heavy_d:
            separator = ',' if ',' in heavy_d else '|'
            if separator in heavy_d:
                heavy_d_conditions = []
                for g in heavy_d.split(separator):
                    for col in self.schema['chain_columns']['d_call']:
                        if '_heavy' in col:
                            heavy_d_conditions.append(self._build_gene_pattern(col, g))
                if heavy_d_conditions:
                    conditions.append(f"({' OR '.join(heavy_d_conditions)})")
            else:
                heavy_d_conditions = []
                for col in self.schema['chain_columns']['d_call']:
                    if '_heavy' in col:
                        heavy_d_conditions.append(self._build_gene_pattern(col, heavy_d))
                if heavy_d_conditions:
                    conditions.append(f"({' OR '.join(heavy_d_conditions)})")
        
        if heavy_j:
            if not heavy_j.startswith('J'):
                heavy_j = f"J{heavy_j}"
            heavy_j_conditions = []
            for col in self.schema['chain_columns']['j_call']:
                if '_heavy' in col:
                    heavy_j_conditions.append(f"{col} LIKE '%{heavy_j}%'")
            if heavy_j_conditions:
                conditions.append(f"({' OR '.join(heavy_j_conditions)})")
        
        # Heavy chain CDR lengths
        if heavy_cdr1_length is not None:
            for col in self.schema['length_columns']['cdr1_length']:
                if '_heavy' in col:
                    conditions.append(f"{col} = {heavy_cdr1_length}")
        
        if heavy_cdr2_length is not None:
            for col in self.schema['length_columns']['cdr2_length']:
                if '_heavy' in col:
                    conditions.append(f"{col} = {heavy_cdr2_length}")
        
        if heavy_cdr3_length is not None:
            for col in self.schema['length_columns']['cdr3_length']:
                if '_heavy' in col:
                    conditions.append(f"{col} = {heavy_cdr3_length}")
        
        # Heavy chain CDR motifs
        if heavy_cdr1_motif:
            if heavy_cdr1_similarity:
                regex_pattern = self.generate_similarity_pattern(heavy_cdr1_motif, heavy_cdr1_mismatches)
            else:
                regex_pattern = convert_motif_to_regex(heavy_cdr1_motif)
            for col in self.schema['chain_columns']['cdr1_aa']:
                if '_heavy' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        if heavy_cdr2_motif:
            if heavy_cdr2_similarity:
                regex_pattern = self.generate_similarity_pattern(heavy_cdr2_motif, heavy_cdr2_mismatches)
            else:
                regex_pattern = convert_motif_to_regex(heavy_cdr2_motif)
            for col in self.schema['chain_columns']['cdr2_aa']:
                if '_heavy' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        if heavy_cdr3_motif:
            if heavy_cdr3_similarity:
                regex_pattern = self.generate_similarity_pattern(heavy_cdr3_motif, heavy_cdr3_mismatches)
            else:
                regex_pattern = convert_motif_to_regex(heavy_cdr3_motif)
            for col in self.schema['chain_columns']['cdr3_aa']:
                if '_heavy' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        # Light chain conditions
        if light_v:
            separator = ',' if ',' in light_v else '|'
            if separator in light_v:
                light_v_conditions = []
                for g in light_v.split(separator):
                    for col in self.schema['chain_columns']['v_call']:
                        if '_light' in col:
                            light_v_conditions.append(self._build_gene_pattern(col, g))
                if light_v_conditions:
                    conditions.append(f"({' OR '.join(light_v_conditions)})")
            else:
                light_v_conditions = []
                for col in self.schema['chain_columns']['v_call']:
                    if '_light' in col:
                        light_v_conditions.append(self._build_gene_pattern(col, light_v))
                if light_v_conditions:
                    conditions.append(f"({' OR '.join(light_v_conditions)})")
        
        if light_d:
            separator = ',' if ',' in light_d else '|'
            if separator in light_d:
                light_d_conditions = []
                for g in light_d.split(separator):
                    for col in self.schema['chain_columns']['d_call']:
                        if '_light' in col:
                            light_d_conditions.append(self._build_gene_pattern(col, g))
                if light_d_conditions:
                    conditions.append(f"({' OR '.join(light_d_conditions)})")
            else:
                light_d_conditions = []
                for col in self.schema['chain_columns']['d_call']:
                    if '_light' in col:
                        light_d_conditions.append(self._build_gene_pattern(col, light_d))
                if light_d_conditions:
                    conditions.append(f"({' OR '.join(light_d_conditions)})")
        
        if light_j:
            if not light_j.startswith('J'):
                light_j = f"J{light_j}"
            light_j_conditions = []
            for col in self.schema['chain_columns']['j_call']:
                if '_light' in col:
                    light_j_conditions.append(f"{col} LIKE '%IGKJ{light_j[1:]}%'")
            if light_j_conditions:
                conditions.append(f"({' OR '.join(light_j_conditions)})")
        
        # Light chain CDR lengths
        if light_cdr1_length is not None:
            for col in self.schema['length_columns']['cdr1_length']:
                if '_light' in col:
                    conditions.append(f"{col} = {light_cdr1_length}")
        
        if light_cdr2_length is not None:
            for col in self.schema['length_columns']['cdr2_length']:
                if '_light' in col:
                    conditions.append(f"{col} = {light_cdr2_length}")
        
        if light_cdr3_length is not None:
            for col in self.schema['length_columns']['cdr3_length']:
                if '_light' in col:
                    conditions.append(f"{col} = {light_cdr3_length}")
        
        # Light chain CDR motifs
        if light_cdr1_motif:
            if light_cdr1_similarity:
                regex_pattern = self.generate_similarity_pattern(light_cdr1_motif, light_cdr1_mismatches)
            else:
                regex_pattern = convert_motif_to_regex(light_cdr1_motif)
            for col in self.schema['chain_columns']['cdr1_aa']:
                if '_light' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        if light_cdr2_motif:
            if light_cdr2_similarity:
                regex_pattern = self.generate_similarity_pattern(light_cdr2_motif, light_cdr2_mismatches)
            else:
                regex_pattern = convert_motif_to_regex(light_cdr2_motif)
            for col in self.schema['chain_columns']['cdr2_aa']:
                if '_light' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        if light_cdr3_motif:
            if light_cdr3_similarity:
                regex_pattern = self.generate_similarity_pattern(light_cdr3_motif, light_cdr3_mismatches)
            else:
                regex_pattern = convert_motif_to_regex(light_cdr3_motif)
            for col in self.schema['chain_columns']['cdr3_aa']:
                if '_light' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        if full_results:
            # Return full sequence data
            query = f"""
                SELECT *
                FROM antibodies
                WHERE {where_clause}
                {f'LIMIT {limit}' if limit else ''}
            """
            results_df = self.conn.execute(query).df()
            
            # Get subject statistics
            stats_query = f"""
                SELECT 
                    subject,
                    COUNT(*) as hits,
                    COUNT(DISTINCT source_file) as num_files
                FROM antibodies
                WHERE {where_clause}
                GROUP BY subject
            """
            stats_df = self.conn.execute(stats_query).df()
            
        else:
            # Return statistics only (much faster)
            query = f"""
                SELECT 
                    subject,
                    COUNT(*) as hits
                FROM antibodies
                WHERE {where_clause}
                GROUP BY subject
            """
            results_df = self.conn.execute(query).df()
            stats_df = results_df
        
        # Calculate overall statistics
        total_hits = int(stats_df['hits'].sum()) if not stats_df.empty else 0
        
        # Get total sequences per subject from metadata.parquet (same as unpaired)
        parquet_files_in_root = list(self.data_dir.glob('*.parquet'))
        
        if parquet_files_in_root:
            metadata_path = self.data_dir / 'metadata.parquet'
        else:
            subdirs = [d for d in self.data_dir.iterdir() if d.is_dir()]
            if subdirs:
                metadata_path = subdirs[0] / 'metadata.parquet'
            else:
                metadata_path = self.data_dir / 'metadata.parquet'
        
        metadata_query = f"""
            SELECT subject, SUM(total_sequences) as total
            FROM read_parquet('{metadata_path}')
            GROUP BY subject
        """
        
        try:
            total_seqs_df = self.conn.execute(metadata_query).df()
            
            # Merge with results
            if not stats_df.empty and not total_seqs_df.empty:
                stats_df = stats_df.merge(
                    total_seqs_df, 
                    on='subject', 
                    how='left'
                ).fillna(0)
                
                # Calculate percentages
                stats_df['percentage'] = (
                    stats_df['hits'] / stats_df['total'] * 100
                ).round(2)
                stats_df['per_million'] = (
                    stats_df['hits'] / stats_df['total'] * 1000000
                ).round(0)
                
                # Rename for display
                stats_df = stats_df.rename(columns={'total': 'total_sequences'})
        except Exception as e:
            # If metadata not available, just use hits (no percentages)
            pass
        
        search_time = time.time() - start_time
        
        statistics = {
            'total_hits': total_hits,
            'total_sequences': self.total_sequences,
            'percentage': round(total_hits / self.total_sequences * 100, 2) if self.total_sequences > 0 else 0,
            'search_time': round(search_time, 2),
            'query_params': {
                'heavy_v': heavy_v,
                'heavy_d': heavy_d,
                'heavy_j': heavy_j,
                'heavy_cdr1_length': heavy_cdr1_length,
                'heavy_cdr2_length': heavy_cdr2_length,
                'heavy_cdr3_length': heavy_cdr3_length,
                'heavy_cdr1_motif': heavy_cdr1_motif,
                'heavy_cdr2_motif': heavy_cdr2_motif,
                'heavy_cdr3_motif': heavy_cdr3_motif,
                'heavy_cdr1_similarity': heavy_cdr1_similarity,
                'heavy_cdr2_similarity': heavy_cdr2_similarity,
                'heavy_cdr3_similarity': heavy_cdr3_similarity,
                'heavy_cdr1_mismatches': heavy_cdr1_mismatches,
                'heavy_cdr2_mismatches': heavy_cdr2_mismatches,
                'heavy_cdr3_mismatches': heavy_cdr3_mismatches,
                'light_v': light_v,
                'light_d': light_d,
                'light_j': light_j,
                'light_cdr1_length': light_cdr1_length,
                'light_cdr2_length': light_cdr2_length,
                'light_cdr3_length': light_cdr3_length,
                'light_cdr1_motif': light_cdr1_motif,
                'light_cdr2_motif': light_cdr2_motif,
                'light_cdr3_motif': light_cdr3_motif,
                'light_cdr1_similarity': light_cdr1_similarity,
                'light_cdr2_similarity': light_cdr2_similarity,
                'light_cdr3_similarity': light_cdr3_similarity,
                'light_cdr1_mismatches': light_cdr1_mismatches,
                'light_cdr2_mismatches': light_cdr2_mismatches,
                'light_cdr3_mismatches': light_cdr3_mismatches
            }
        }
        
        return results_df if full_results else stats_df, statistics
    
    def get_available_genes(self) -> Dict[str, List[str]]:
        """Get list of available V, D, J genes in database."""
        genes = {}
        
        # V genes
        v_genes = self.conn.execute("""
            SELECT DISTINCT v_call 
            FROM antibodies 
            WHERE v_call IS NOT NULL
            LIMIT 100
        """).df()
        genes['v_genes'] = sorted(v_genes['v_call'].tolist())
        
        # D genes
        d_genes = self.conn.execute("""
            SELECT DISTINCT d_call 
            FROM antibodies 
            WHERE d_call IS NOT NULL
            LIMIT 100
        """).df()
        genes['d_genes'] = sorted(d_genes['d_call'].tolist())
        
        # J genes
        j_genes = self.conn.execute("""
            SELECT DISTINCT j_call 
            FROM antibodies 
            WHERE j_call IS NOT NULL
            LIMIT 50
        """).df()
        genes['j_genes'] = sorted(j_genes['j_call'].tolist())
        
        return genes
    
    def get_database_info(self) -> dict:
        """Get information about the current database configuration."""
        return {
            'data_dir': str(self.data_dir),
            'db_path': self.db_path,
            'total_sequences': self.total_sequences,
            'is_memory_db': self.db_path == ":memory:"
        }
    
    def close(self):
        """Close database connection."""
        self.conn.close()

