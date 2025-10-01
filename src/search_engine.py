"""
DuckDB-based search engine for antibody sequences.

This module provides high-performance searching using DuckDB's
analytical query engine on Parquet files.
"""

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import duckdb
import pandas as pd

class AntibodySearchEngine:
    """High-performance antibody sequence search using DuckDB."""
    
    def __init__(self, data_dir: str = "data/parquet", progress_callback=None):
        """
        Initialize search engine.
        
        Args:
            data_dir: Directory containing Parquet files (relative to V3.0/)
            progress_callback: Optional callback function(progress, status) for progress updates
        """
        # Handle relative paths from V3.0 directory
        if not Path(data_dir).is_absolute():
            # Get the directory where this script is located
            script_dir = Path(__file__).parent.parent
            self.data_dir = script_dir / data_dir
        else:
            self.data_dir = Path(data_dir)
        self.conn = duckdb.connect(database=':memory:')
        
        # Register Parquet files as views
        self._register_data(progress_callback)
    
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
        
        # Build pattern that matches gene correctly
        # For v_call: Match IGHV3- but not IGHV4-34 or IGHV33-
        # Strategy: Match pattern immediately after IGHV/IGHD/IGHJ prefix
        
        # Escape special regex characters except * (wildcard)
        gene_escaped = gene.replace('*', '.*')
        
        # Match: IGHV3-23 or IGHD3-10 etc., but not 4-34 or 33-
        # Use precise pattern: gene must be followed by * (allele) or end of string
        if gene.endswith('-'):
            # Family search (e.g., "3-"): match IGHV3-* but not IGHV33-*
            pattern = f"IGHV{gene}%"
            d_pattern = f"IGHD{gene}%"
            j_pattern = f"IGHJ{gene}%"
        elif '-' in gene and not gene.endswith('*'):
            # Gene search (e.g., "3-3"): match IGHV3-3* but not IGHV3-33*
            # Add * to ensure it matches allele or end of string
            pattern = f"IGHV{gene}*%"
            d_pattern = f"IGHD{gene}*%"
            j_pattern = f"IGHJ{gene}*%"
        else:
            # Exact match or already has wildcard
            pattern = f"IGHV{gene}%"
            d_pattern = f"IGHD{gene}%"
            j_pattern = f"IGHJ{gene}%"
        
        return f"({column} LIKE '{pattern}' OR {column} LIKE '{d_pattern}' OR {column} LIKE '{j_pattern}')"
    
    def search(
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
        full_results: bool = False,
        limit: Optional[int] = None
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Search for antibody sequences matching criteria.
        
        Args:
            ighv: V gene (e.g., "3-23" or "3" for all 3-* genes)
            ighd: D gene (e.g., "2-21" or "2")
            ighj: J gene (e.g., "4" or "J4")
            cdr1_length: Exact CDR1 length (amino acids)
            cdr2_length: Exact CDR2 length (amino acids)
            cdr3_length: Exact CDR3 length (amino acids)
            cdr1_motif: Regex pattern for cdr1_aa (e.g., "YY.D.*G")
            cdr2_motif: Regex pattern for cdr2_aa (e.g., "YY.D.*G")
            cdr3_motif: Regex pattern for cdr3_aa (e.g., "YY.D.*G")
            full_results: Return full sequence data (vs statistics only)
            limit: Maximum number of results to return
            
        Returns:
            Tuple of (results_df, statistics_dict)
        """
        start_time = time.time()
        
        # Build WHERE clause
        conditions = []
        
        if ighv:
            # Support multiple genes with , or | separator
            separator = ',' if ',' in ighv else '|'
            if separator in ighv:
                ighv_conditions = [self._build_gene_pattern('v_call', g) for g in ighv.split(separator)]
                conditions.append(f"({' OR '.join(ighv_conditions)})")
            else:
                conditions.append(self._build_gene_pattern('v_call', ighv))
        
        if ighd:
            # Support multiple genes with , or | separator
            separator = ',' if ',' in ighd else '|'
            if separator in ighd:
                ighd_conditions = [self._build_gene_pattern('d_call', g) for g in ighd.split(separator)]
                conditions.append(f"({' OR '.join(ighd_conditions)})")
            else:
                conditions.append(self._build_gene_pattern('d_call', ighd))
        
        if ighj:
            # Add 'J' prefix if not present
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
            import re
            regex_pattern = motif
            # First convert SQL LIKE wildcards to regex, but be careful about existing .*
            # Replace * only when it's not already part of .*
            regex_pattern = re.sub(r'(?<!\.)\*(?!\*)', '.*', regex_pattern)
            # Then escape remaining regex special characters
            regex_pattern = re.escape(regex_pattern)
            # Restore the .* patterns that we want to keep
            regex_pattern = regex_pattern.replace(r'\.\*', '.*')  # \.* -> .*
            return regex_pattern
        
        if cdr1_motif:
            regex_pattern = convert_motif_to_regex(cdr1_motif)
            conditions.append(f"cdr1_aa ~ '{regex_pattern}'")
        
        if cdr2_motif:
            regex_pattern = convert_motif_to_regex(cdr2_motif)
            conditions.append(f"cdr2_aa ~ '{regex_pattern}'")
        
        if cdr3_motif:
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
                    COUNT(DISTINCT file_source) as num_files
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
                'cdr3_motif': cdr3_motif
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
    
    def close(self):
        """Close database connection."""
        self.conn.close()

