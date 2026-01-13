"""
DuckDB-based search engine for antibody sequences.

This module provides high-performance searching using DuckDB's
analytical query engine on Parquet files.
"""

import time
import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import re
import json
import time
from datetime import datetime

def _log_debug_event(location, message, data=None):
    try:
        log_entry = {
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": "duckdb_spill"
        }
        with open("/app/.cursor/debug.log", "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception:
        pass

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# Configuration: Number of threads for DuckDB queries
# Set to None to use all available cores, or specify a number (e.g., 4)
DUCKDB_THREADS = None  # Change this to set a specific thread count

# Configuration: Verbose output control via environment variable
# Set ABHUNTER_VERBOSE=true to enable verbose output (default: false)
def _get_verbose_default() -> bool:
    """Get verbose setting from environment variable, defaulting to False.
    
    Only accepts 'true' or 'false' (case-insensitive). Any other value defaults to False.
    
    Returns:
        True if ABHUNTER_VERBOSE is set to 'true', False otherwise
    """
    verbose_env = os.getenv('ABHUNTER_VERBOSE', '').lower().strip()
    return verbose_env == 'true'

class AntibodySearchEngine:
    """High-performance antibody sequence search using DuckDB.
    Supports both paired and unpaired antibody data.
    """
    
    def __init__(self, data_dir: str = "data/parquet", progress_callback=None, db_path: str = ":memory:", verbose: Optional[bool] = None, data_dirs: Optional[List[str]] = None):
        """
        Initialize search engine.
        
        Args:
            data_dir: Directory containing Parquet files (relative to V3.0/)
                     Used if data_dirs is None
            progress_callback: Optional callback function(progress, status) for progress updates
            db_path: DuckDB database path (default: ":memory:" for in-memory database)
            verbose: Whether to print initialization messages. If None, uses ABHUNTER_VERBOSE
                    environment variable (defaults to False if not set). Only accepts True/False.
            data_dirs: Optional list of directories to search (takes precedence over data_dir)
        """
        # Use environment variable default if verbose not explicitly provided
        if verbose is None:
            verbose = _get_verbose_default()
        # Handle multiple directories if provided
        if data_dirs:
            # Handle relative paths from V3.0 directory
            script_dir = Path(__file__).parent.parent
            self.data_dirs = [
                script_dir / d if not Path(d).is_absolute() else Path(d)
                for d in data_dirs
            ]
            # Use first directory as primary data_dir for backward compatibility
            self.data_dir = self.data_dirs[0]
        else:
            # Handle relative paths from V3.0 directory
            if not Path(data_dir).is_absolute():
                # Get the directory where this script is locateds
                script_dir = Path(__file__).parent.parent
                self.data_dir = script_dir / data_dir
            else:
                self.data_dir = Path(data_dir)
            self.data_dirs = [self.data_dir]
        
        # Precompute directory prefixes grouped by antibody chain for efficient filtering later
        self.chain_dir_prefixes = {'Heavy': set(), 'Light': set(), 'Paired': set()}
        for data_dir in self.data_dirs:
            path_obj = Path(data_dir)
            parts_lower = [part.lower() for part in path_obj.parts]
            if 'heavy' in parts_lower:
                chain_key = 'Heavy'
            elif 'light' in parts_lower:
                chain_key = 'Light'
            elif 'paired' in parts_lower:
                chain_key = 'Paired'
            else:
                chain_key = None
            if chain_key:
                prefix = path_obj.as_posix()
                if not prefix.endswith('/'):
                    prefix += '/'
                self.chain_dir_prefixes[chain_key].add(prefix)

        # Mapping of chain types to dedicated DuckDB views (populated during registration)
        self.chain_views: Dict[str, str] = {}

        # Inferred pairing lookup (populated when overlays are provided)
        # Structure: {'V': {'Heavy': {}, 'Light': {}}, 'J': {'Heavy': {}, 'Light': {}}}
        self.inferred_v_pairs_df: Optional[pd.DataFrame] = None
        self.inferred_j_pairs_df: Optional[pd.DataFrame] = None
        self._inferred_lookup: Dict[str, Dict[str, Dict[str, List[Tuple[str, float]]]]] = {
            'V': {'Heavy': {}, 'Light': {}},
            'J': {'Heavy': {}, 'Light': {}}
        }

        # Connect to DuckDB with the specified database path
        self.conn = duckdb.connect(database=db_path)
        self.db_path = db_path

        # Set temp directory to /tmp to avoid bind mount I/O overhead and Streamlit file watcher loops
        try:
            # Create a dedicated temp directory for DuckDB
            duckdb_tmp = Path("/tmp/duckdb_tmp")
            duckdb_tmp.mkdir(parents=True, exist_ok=True)
            self.conn.execute(f"SET temp_directory='{str(duckdb_tmp)}'")
            
            # #region agent log
            temp_dir = self.conn.execute("SELECT current_setting('temp_directory')").fetchone()
            _log_debug_event("AntibodySearchEngine.__init__", "DuckDB initialized (Fixed temp dir)", {
                "db_path": db_path,
                "temp_directory": str(temp_dir[0]) if temp_dir else "unknown",
                "cwd": os.getcwd()
            })
            # #endregion
        except Exception as e:
            # #region agent log
            _log_debug_event("AntibodySearchEngine.__init__", "Error setting temp dir", {"error": str(e)})
            # #endregion
            pass

        # Configure thread count based on global setting
        if DUCKDB_THREADS is not None:
            self.conn.execute(f"SET threads = {DUCKDB_THREADS}")
            if verbose:
                print(f"DuckDB configured to use {DUCKDB_THREADS} threads")
        else:
            # Use all available cores (DuckDB default)
            available_cores = os.cpu_count()
            if verbose:
                print(f"DuckDB using all available cores: {available_cores}")
        
        # Detect database schema (paired vs unpaired)
        self.schema = self._detect_schema()
        
        # Register Parquet files as views
        # #region agent log
        _log_debug_event("AntibodySearchEngine.__init__", "Calling _register_data", {})
        # #endregion
        self._register_data(progress_callback, verbose)
    
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
            parquet_files = []
            for data_dir in self.data_dirs:
                parquet_files.extend([f for f in data_dir.rglob("*.parquet") if f.name != 'metadata.parquet'])
            
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
    
    def _register_data(self, progress_callback=None, verbose: bool = True):
        """Register Parquet files as DuckDB views."""
        # #region agent log
        _log_debug_event("AntibodySearchEngine._register_data", "Start", {})
        # #endregion

        if progress_callback:
            progress_callback(0.0, "Initializing search engine...")
        
        # Check if all data directories exist
        for data_dir in self.data_dirs:
            if not data_dir.exists():
                raise FileNotFoundError(f"Data directory not found: {data_dir}")
        
        if progress_callback:
            progress_callback(0.1, "Scanning for Parquet files...")
        
        # Reset chain-specific view mapping before (re)registration
        self.chain_views = {}
        
        # Register all parquet files from all data directories and bucket them by chain
        parquet_files: List[Path] = []
        chain_file_map: Dict[str, List[str]] = {'Heavy': [], 'Light': [], 'Paired': []}
        for data_dir in self.data_dirs:
            for f in data_dir.rglob("*.parquet"):
                if f.name == 'metadata.parquet':
                    continue
                parquet_files.append(f)
                parts_lower = [part.lower() for part in f.parts]
                if 'heavy' in parts_lower:
                    chain_key = 'Heavy'
                elif 'light' in parts_lower:
                    chain_key = 'Light'
                elif 'paired' in parts_lower:
                    chain_key = 'Paired'
                else:
                    chain_key = None
                if chain_key:
                    chain_file_map.setdefault(chain_key, []).append(str(f))
        
        if not parquet_files:
            raise FileNotFoundError(f"No Parquet files found in {[str(d) for d in self.data_dirs]}")
        
        if progress_callback:
            progress_callback(0.2, f"Found {len(parquet_files)} Parquet files")
        
        # #region agent log
        _log_debug_event("AntibodySearchEngine._register_data", "Parquet files found", {"count": len(parquet_files)})
        # #endregion

        # Create a view that reads all parquet files (excluding metadata.parquet)
        # Build a list of specific files to avoid schema conflicts
        if progress_callback:
            progress_callback(0.3, "Creating database view...")
        
        parquet_file_paths = [str(f) for f in parquet_files]
        parquet_files_str = "', '".join(parquet_file_paths)
        
        # #region agent log
        _log_debug_event("AntibodySearchEngine._register_data", "Creating antibodies_base view", {"files_count": len(parquet_file_paths)})
        start_view = time.time()
        # #endregion

        # Register files as view with source_file
        self.conn.execute(f"""
            CREATE OR REPLACE VIEW antibodies_base AS 
            SELECT *, filename as source_file FROM read_parquet(['{parquet_files_str}'], 
                                        union_by_name=true,
                                        filename=true)
        """)
        
        # #region agent log
        _log_debug_event("AntibodySearchEngine._register_data", "antibodies_base view created", {"duration": time.time() - start_view})
        # #endregion

        # Register metadata view from all data directories
        metadata_files = []
        for data_dir in self.data_dirs:
            metadata_files.extend(list(data_dir.rglob('metadata.parquet')))
        
        if not metadata_files:
            raise FileNotFoundError(
                f"Expected metadata.parquet in each selected database directory, but none were found for {', '.join(str(d) for d in self.data_dirs)}"
            )
        
        import pyarrow.parquet as pq
        
        metadata_sample = pq.ParquetFile(metadata_files[0])
        metadata_columns = set(metadata_sample.schema.names)
        
        file_path_expr = "file_path" if "file_path" in metadata_columns else (
            "filename" if "filename" in metadata_columns else "NULL AS file_path"
        )
        if "file_path" not in metadata_columns:
            file_path_expr = file_path_expr if " AS " in file_path_expr else f"{file_path_expr} AS file_path"
        
        select_expressions = [file_path_expr]
        for column in ["subject", "chain", "isotype", "species", "disease", "vaccine", "total_sequences"]:
            if column in metadata_columns:
                select_expressions.append(column)
            else:
                select_expressions.append(f"NULL AS {column}")
        
        metadata_paths_str = "', '".join([str(f) for f in metadata_files])
        self.conn.execute(f"""
            CREATE OR REPLACE VIEW metadata AS 
            SELECT {', '.join(select_expressions)}
            FROM read_parquet(['{metadata_paths_str}'], union_by_name=true)
        """)
        
        # Create joined view with subject and other metadata
        # Need to match filename to file_path
        # filename is like '/path/to/V3.0/data/Heavy/Bulk/file.parquet' or '/path/to/data_test/Heavy/Bulk/file.parquet'
        # file_path is like 'Heavy/Bulk/file.parquet'
        # Extract path starting from Heavy/, Light/, or Paired/ to handle any database directory name
        self.conn.execute("""
            CREATE OR REPLACE VIEW antibodies AS
            SELECT a.*, m.subject, m.chain, m.isotype, m.species, m.disease, m.vaccine
            FROM antibodies_base a
            LEFT JOIN metadata m ON m.file_path = regexp_replace(a.source_file, '.*/(Heavy|Light|Paired)/(.*)', '\\1/\\2')
        """)

        # Update available columns to include metadata fields exposed through the joined view
        try:
            table_info = self.conn.execute("PRAGMA table_info('antibodies')").fetchall()
            if table_info:
                table_columns = [col[1] for col in table_info if len(col) > 1]
                existing_columns = self.schema.get('available_columns', [])
                # Preserve order while adding any new columns from the view
                merged = list(dict.fromkeys(existing_columns + table_columns))
                self.schema['available_columns'] = merged
        except Exception:
            # Non-fatal: fall back to previously detected columns if PRAGMA fails
            pass
        
        if progress_callback:
            progress_callback(0.8, "Counting total sequences...")
        
        # #region agent log
        _log_debug_event("AntibodySearchEngine._register_data", "Counting total sequences (metadata)", {})
        start_count = time.time()
        # #endregion

        total_sequences_row = self.conn.execute("""
            SELECT SUM(total_sequences) 
            FROM metadata 
            WHERE total_sequences IS NOT NULL
        """).fetchone()

        # #region agent log
        _log_debug_event("AntibodySearchEngine._register_data", "Total sequences counted", {"duration": time.time() - start_count})
        # #endregion

        if not total_sequences_row or total_sequences_row[0] is None:
            raise ValueError(
                "Metadata files must include non-null total_sequences values for every database."
            )
        self.total_sequences = int(total_sequences_row[0])

        # Create dedicated views per chain to restrict scans to selected directories
        def create_chain_view(chain_name: str, file_paths: List[str]) -> None:
            if not file_paths:
                return
            escaped_paths = [path.replace("'", "''") for path in file_paths]
            files_str = "', '".join(escaped_paths)
            chain_lower = chain_name.lower()
            base_view_name = f"antibodies_{chain_lower}_base"
            view_name = f"antibodies_{chain_lower}"
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW {base_view_name} AS 
                SELECT *, filename as source_file FROM read_parquet(['{files_str}'], 
                                                union_by_name=true,
                                                filename=true)
            """)
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW {view_name} AS
                SELECT a.*, m.subject, m.chain, m.isotype, m.species, m.disease, m.vaccine
                FROM {base_view_name} a
                LEFT JOIN metadata m ON m.file_path = regexp_replace(a.source_file, '.*/(Heavy|Light|Paired)/(.*)', '\\1/\\2')
            """)
            self.chain_views[chain_name] = view_name

        for chain_name, file_paths in chain_file_map.items():
            create_chain_view(chain_name, file_paths)
        
        # #region agent log
        _log_debug_event("AntibodySearchEngine._register_data", "Chain views created", {})
        # #endregion

        if progress_callback:
            progress_callback(1.0, "Search engine ready!")
        
        if verbose:
            print(f"Registered {len(parquet_files)} Parquet files")
            print(f"Total sequences: {self.total_sequences:,}")

    def _reset_inferred_lookup(self) -> None:
        """Clear any cached inferred pairing data."""
        self.inferred_v_pairs_df = None
        self.inferred_j_pairs_df = None
        self._inferred_lookup = {
            'V': {'Heavy': {}, 'Light': {}},
            'J': {'Heavy': {}, 'Light': {}}
        }

    def load_inferred_pairs(self, overlay_directories: Optional[List[Union[str, Path]]]) -> None:
        """
        Load inferred VH↔VL and JH↔JL pairing frequencies from overlay directories.

        Args:
            overlay_directories: List of directories containing inferred pairing files.
                                 Looks for:
                                 - adj_vh_vl_freq_table_for_search_wo_epsilon.parquet (VH-VL)
                                 - adj_jh_vj_freq_table_for_search_wo_epsilon.parquet (JH-JL)
        """
        if not overlay_directories:
            self._reset_inferred_lookup()
            return

        # Load VH-VL pairings
        v_tables: List[pd.DataFrame] = []
        # Load JH-JL pairings
        j_tables: List[pd.DataFrame] = []
        
        for overlay_dir in overlay_directories:
            try:
                overlay_path = Path(overlay_dir)
            except TypeError:
                overlay_path = Path(str(overlay_dir))
            
            # Try to load VH-VL file
            v_freq_path = overlay_path / "adj_vh_vl_freq_table_for_search_wo_epsilon.parquet"
            if v_freq_path.exists():
                try:
                    df = pd.read_parquet(v_freq_path)
                    v_tables.append(df)
                except Exception as exc:
                    print(f"⚠️ Failed to load VH-VL inferred pairings from {v_freq_path}: {exc}")
            
            # Try to load JH-JL file
            j_freq_path = overlay_path / "adj_jh_vj_freq_table_for_search_wo_epsilon.parquet"
            if j_freq_path.exists():
                try:
                    df = pd.read_parquet(j_freq_path)
                    j_tables.append(df)
                except Exception as exc:
                    print(f"⚠️ Failed to load JH-JL inferred pairings from {j_freq_path}: {exc}")

        # Process VH-VL pairings
        if v_tables:
            v_combined = pd.concat(v_tables, ignore_index=True)
            # Rename to internal format
            v_combined = v_combined.rename(columns={'vh_family': 'heavy_v_family', 'vl_family': 'light_v_family'})
            
            required_cols = {'heavy_v_family', 'light_v_family'}
            missing_cols = required_cols - set(v_combined.columns)
            if missing_cols:
                print(f"⚠️ VH-VL inferred pairing table missing columns: {missing_cols}")
            else:
                v_combined = v_combined.dropna(subset=['heavy_v_family', 'light_v_family'])
                if not v_combined.empty:
                    v_combined['heavy_v_family'] = v_combined['heavy_v_family'].astype(str).str.upper().str.strip()
                    v_combined['light_v_family'] = v_combined['light_v_family'].astype(str).str.upper().str.strip()

                    if 'h_to_l' in v_combined.columns:
                        v_combined['h_to_l'] = pd.to_numeric(v_combined['h_to_l'], errors='coerce')
                    if 'l_to_h' in v_combined.columns:
                        v_combined['l_to_h'] = pd.to_numeric(v_combined['l_to_h'], errors='coerce')
                    
                    drop_subset = [col for col in ('h_to_l', 'l_to_h') if col in v_combined.columns]
                    if drop_subset:
                        v_combined = v_combined.dropna(subset=drop_subset, how='all')
                    
                    if not v_combined.empty:
                        agg_dict = {}
                        if 'h_to_l' in v_combined.columns:
                            agg_dict['h_to_l'] = 'mean'
                        if 'l_to_h' in v_combined.columns:
                            agg_dict['l_to_h'] = 'mean'
                        
                        if agg_dict:
                            v_aggregated = v_combined.groupby(['heavy_v_family', 'light_v_family'], as_index=False).agg(agg_dict)
                            
                            if 'h_to_l' not in v_aggregated.columns:
                                v_aggregated['h_to_l'] = 0.0
                            if 'l_to_h' not in v_aggregated.columns:
                                v_aggregated['l_to_h'] = v_aggregated.groupby('light_v_family')['h_to_l'].transform(
                                    lambda values: (values / values.sum() * 100.0) if values.sum() else values * 0.0
                                )
                            
                            v_aggregated['h_to_l'] = v_aggregated['h_to_l'].fillna(0.0)
                            v_aggregated['l_to_h'] = v_aggregated['l_to_h'].fillna(0.0)
                            self.inferred_v_pairs_df = v_aggregated
        
        # Process JH-JL pairings
        if j_tables:
            j_combined = pd.concat(j_tables, ignore_index=True)
            # Rename to internal format
            j_combined = j_combined.rename(columns={'jh_family': 'heavy_j_family', 'jl_family': 'light_j_family'})
            
            required_cols = {'heavy_j_family', 'light_j_family'}
            missing_cols = required_cols - set(j_combined.columns)
            if missing_cols:
                print(f"⚠️ JH-JL inferred pairing table missing columns: {missing_cols}")
            else:
                j_combined = j_combined.dropna(subset=['heavy_j_family', 'light_j_family'])
                if not j_combined.empty:
                    j_combined['heavy_j_family'] = j_combined['heavy_j_family'].astype(str).str.upper().str.strip()
                    j_combined['light_j_family'] = j_combined['light_j_family'].astype(str).str.upper().str.strip()
                    
                    if 'h_to_l' in j_combined.columns:
                        j_combined['h_to_l'] = pd.to_numeric(j_combined['h_to_l'], errors='coerce')
                    if 'l_to_h' in j_combined.columns:
                        j_combined['l_to_h'] = pd.to_numeric(j_combined['l_to_h'], errors='coerce')

                    drop_subset = [col for col in ('h_to_l', 'l_to_h') if col in j_combined.columns]
                    if drop_subset:
                        j_combined = j_combined.dropna(subset=drop_subset, how='all')

                    if not j_combined.empty:
                        agg_dict = {}
                        if 'h_to_l' in j_combined.columns:
                            agg_dict['h_to_l'] = 'mean'
                        if 'l_to_h' in j_combined.columns:
                            agg_dict['l_to_h'] = 'mean'

                        if agg_dict:
                            j_aggregated = j_combined.groupby(['heavy_j_family', 'light_j_family'], as_index=False).agg(agg_dict)
                            
                            if 'h_to_l' not in j_aggregated.columns:
                                j_aggregated['h_to_l'] = 0.0
                            if 'l_to_h' not in j_aggregated.columns:
                                j_aggregated['l_to_h'] = j_aggregated.groupby('light_j_family')['h_to_l'].transform(
                                    lambda values: (values / values.sum() * 100.0) if values.sum() else values * 0.0
                                )

                            j_aggregated['h_to_l'] = j_aggregated['h_to_l'].fillna(0.0)
                            j_aggregated['l_to_h'] = j_aggregated['l_to_h'].fillna(0.0)
                            self.inferred_j_pairs_df = j_aggregated

        self._rebuild_inferred_lookup()

    def _rebuild_inferred_lookup(self) -> None:
        """Build fast lookup dictionaries from the inferred pairing dataframes for both V and J genes."""
        # Initialize lookups for V and J genes
        v_lookup_heavy: Dict[str, List[Tuple[str, float]]] = {}
        v_lookup_light: Dict[str, List[Tuple[str, float]]] = {}
        j_lookup_heavy: Dict[str, List[Tuple[str, float]]] = {}
        j_lookup_light: Dict[str, List[Tuple[str, float]]] = {}

        # Process VH-VL pairings
        if self.inferred_v_pairs_df is not None and not self.inferred_v_pairs_df.empty:
            df = self.inferred_v_pairs_df
            if 'h_to_l' not in df.columns:
                df['h_to_l'] = 0.0
            if 'l_to_h' not in df.columns:
                df['l_to_h'] = 0.0

            for heavy_family, group in df.groupby('heavy_v_family'):
                ordered = group.sort_values('h_to_l', ascending=False)
                v_lookup_heavy[heavy_family] = [
                    (partner, float(value))
                    for partner, value in zip(ordered['light_v_family'], ordered['h_to_l'])
                    if float(value) > 0
                ]

            for light_family, group in df.groupby('light_v_family'):
                ordered = group.sort_values('l_to_h', ascending=False)
                v_lookup_light[light_family] = [
                    (partner, float(value))
                    for partner, value in zip(ordered['heavy_v_family'], ordered['l_to_h'])
                    if float(value) > 0
                ]

        # Process JH-JL pairings
        if self.inferred_j_pairs_df is not None and not self.inferred_j_pairs_df.empty:
            df = self.inferred_j_pairs_df
            if 'h_to_l' not in df.columns:
                df['h_to_l'] = 0.0
            if 'l_to_h' not in df.columns:
                df['l_to_h'] = 0.0

            for heavy_family, group in df.groupby('heavy_j_family'):
                ordered = group.sort_values('h_to_l', ascending=False)
                j_lookup_heavy[heavy_family] = [
                    (partner, float(value))
                    for partner, value in zip(ordered['light_j_family'], ordered['h_to_l'])
                    if float(value) > 0
                ]

            for light_family, group in df.groupby('light_j_family'):
                ordered = group.sort_values('l_to_h', ascending=False)
                j_lookup_light[light_family] = [
                    (partner, float(value))
                    for partner, value in zip(ordered['heavy_j_family'], ordered['l_to_h'])
                    if float(value) > 0
                ]

        self._inferred_lookup = {
            'V': {'Heavy': v_lookup_heavy, 'Light': v_lookup_light},
            'J': {'Heavy': j_lookup_heavy, 'Light': j_lookup_light}
        }

    @staticmethod
    def _extract_v_family(gene_name: Optional[str]) -> Optional[str]:
        """Extract V family (e.g., IGHV3) from a full V gene string.
        
        Handles formats like:
        - IGHV3-30*01 -> IGHV3
        - IGHV1/OR15 -> IGHV1
        - IGHV4/OR15 -> IGHV4
        """
        if not gene_name:
            return None
        gene_name = str(gene_name).upper().strip()
        if not gene_name.startswith("IG"):
            return None
        # Remove allele suffix (e.g., *01)
        gene_name = gene_name.split('*', 1)[0]
        # Remove OR suffix (e.g., /OR15)
        gene_name = gene_name.split('/', 1)[0]
        # Extract family (e.g., IGHV3 from IGHV3-30)
        family = gene_name.split('-', 1)[0]
        return family if family else None
    
    @staticmethod
    def _extract_j_family(gene_name: Optional[str]) -> Optional[str]:
        """Extract J family (e.g., IGHJ4) from a full J gene string.
        
        Handles formats like:
        - IGHJ4*01 -> IGHJ4
        - IGHJ2 -> IGHJ2
        """
        if not gene_name:
            return None
        gene_name = str(gene_name).upper().strip()
        if not gene_name.startswith("IG"):
            return None
        # Remove allele suffix (e.g., *01)
        gene_name = gene_name.split('*', 1)[0]
        # Remove OR suffix (e.g., /OR15) - though unlikely for J genes
        gene_name = gene_name.split('/', 1)[0]
        # Extract family (e.g., IGHJ4 from IGHJ4-01)
        family = gene_name.split('-', 1)[0]
        return family if family else None

    def _get_inferred_partners(
        self,
        chain_type: str,
        gene_name: str,
        gene_type: str = 'V',
        top_n: Optional[int] = 3
    ) -> List[Tuple[str, float]]:
        """
        Return the top inferred partner families for a given V or J gene.

        Args:
            chain_type: 'Heavy' if the gene belongs to a heavy chain search, else 'Light'.
            gene_name: V or J gene string from dataset or query.
            gene_type: 'V' for V genes, 'J' for J genes (default: 'V').
            top_n: Number of partner families to return.
        """
        gene_type = gene_type.upper()
        if gene_type not in ('V', 'J'):
            return []
        
        lookup_dict = self._inferred_lookup.get(gene_type, {})
        lookup = lookup_dict.get(chain_type.capitalize(), {})
        if not lookup:
            return []

        if gene_type == 'V':
            family = self._extract_v_family(gene_name)
        else:  # J
            family = self._extract_j_family(gene_name)
        
        if not family:
            return []

        partners = lookup.get(family)
        if not partners:
            return []

        if top_n is None or top_n >= len(partners):
            return partners
        return partners[:top_n]

    def extract_v_family(self, gene_name: Optional[str]) -> Optional[str]:
        """Public helper to extract a V family from a gene string."""
        return self._extract_v_family(gene_name)
    
    def extract_j_family(self, gene_name: Optional[str]) -> Optional[str]:
        """Public helper to extract a J family from a gene string."""
        return self._extract_j_family(gene_name)

    def get_inferred_distribution(
        self,
        chain_type: str,
        gene_or_family: str,
        gene_type: str = 'V',
        top_n: Optional[int] = None
    ) -> List[Tuple[str, float]]:
        """Return inferred partner distribution for a heavy or light V or J family."""
        return self._get_inferred_partners(chain_type, gene_or_family, gene_type=gene_type, top_n=top_n)

    def _attach_inferred_partners(
        self,
        df: pd.DataFrame,
        chain_type: str,
        top_n: int = 3
    ) -> pd.DataFrame:
        """Append inferred partner summaries to result dataframes for both V and J genes."""
        if df is None or df.empty:
            return df

        df = df.copy()
        partner_prefix = 'inferred_light' if chain_type.lower() == 'heavy' else 'inferred_heavy'
        
        # Attach V gene inferred partners
        v_lookup = self._inferred_lookup.get('V', {}).get(chain_type.capitalize(), {})
        if v_lookup and 'v_call' in df.columns:
            v_summaries: List[str] = []
            v_top_family: List[Optional[str]] = []
            v_top_percent: List[Optional[float]] = []

            for gene in df['v_call']:
                partners = self._get_inferred_partners(chain_type, gene, gene_type='V', top_n=top_n)
                if partners:
                    v_summaries.append(", ".join(f"{partner} ({percent:.1f}%)" for partner, percent in partners))
                    v_top_family.append(partners[0][0])
                    v_top_percent.append(round(partners[0][1], 1))
                else:
                    v_summaries.append("")
                    v_top_family.append(None)
                    v_top_percent.append(None)

            if any(v_summaries):
                df[f'{partner_prefix}_v_partners'] = v_summaries
                df[f'{partner_prefix}_v_top_family'] = v_top_family
                df[f'{partner_prefix}_v_top_percent'] = v_top_percent
        
        # Attach J gene inferred partners
        j_lookup = self._inferred_lookup.get('J', {}).get(chain_type.capitalize(), {})
        if j_lookup and 'j_call' in df.columns:
            j_summaries: List[str] = []
            j_top_family: List[Optional[str]] = []
            j_top_percent: List[Optional[float]] = []

            for gene in df['j_call']:
                partners = self._get_inferred_partners(chain_type, gene, gene_type='J', top_n=top_n)
                if partners:
                    j_summaries.append(", ".join(f"{partner} ({percent:.1f}%)" for partner, percent in partners))
                    j_top_family.append(partners[0][0])
                    j_top_percent.append(round(partners[0][1], 1))
                else:
                    j_summaries.append("")
                    j_top_family.append(None)
                    j_top_percent.append(None)

            if any(j_summaries):
                df[f'{partner_prefix}_j_partners'] = j_summaries
                df[f'{partner_prefix}_j_top_family'] = j_top_family
                df[f'{partner_prefix}_j_top_percent'] = j_top_percent

        return df

    def _build_inferred_hint(self, gene_input: str, chain_type: str, gene_type: str = 'V', top_n: int = 3) -> Optional[str]:
        """Generate human-readable inferred partner summary for statistics."""
        if not gene_input:
            return None
        if any(sep in gene_input for sep in (',', '|')):
            return None
        partners = self._get_inferred_partners(chain_type, gene_input, gene_type=gene_type, top_n=top_n)
        if not partners:
            return None
        partner_label = "Light" if chain_type.lower() == 'heavy' else "Heavy"
        gene_label = gene_type.upper()  # 'V' or 'J'
        summary = ", ".join(f"{partner} ({percent:.1f}%)" for partner, percent in partners)
        return f"{partner_label} {gene_label} families: {summary}"
    
    def generate_similarity_pattern(self, motif: str, max_mismatches: int = 2) -> str:
        """
        Generate a regex pattern for similarity-based motif matching.
        
        This method uses amino acid similarity groups to allow matches with similar
        amino acids. When max_mismatches > 0, each position can match either the
        exact amino acid or similar ones (based on chemical properties).
        
        Args:
            motif: The motif pattern (e.g., "YY.D.*G")
            max_mismatches: Controls similarity matching behavior:
                - If > 0: Allows similar amino acids at each position (e.g., Y matches F, W, Y)
                - If 0: Requires exact amino acid matches (no similarity groups)
                Note: This does NOT limit the number of positions that can differ,
                but rather controls whether similarity groups are applied at each position.
        
        Returns:
            A regex pattern that matches sequences with similarity-based matching
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
            
            if char == '[':
                # Square bracket for explicit alternatives: [ABC] -> [ABC] in regex
                bracket_end = motif.find(']', i + 1)
                if bracket_end != -1:
                    bracket_content = motif[i + 1:bracket_end].upper()
                    # Validate that content contains only amino acids
                    if re.match(r'^[ACDEFGHIKLMNPQRSTVWY]+$', bracket_content):
                        regex_pattern += f'[{bracket_content}]'
                        i = bracket_end + 1
                        continue
                    else:
                        # Invalid bracket content - escape the bracket
                        regex_pattern += re.escape(char)
                else:
                    # Unmatched bracket - escape it
                    regex_pattern += re.escape(char)
            elif char == '*':
                # Check if followed by curly braces {n} or {n-m}
                if i + 1 < len(motif) and motif[i + 1] == '{':
                    # Find the closing brace
                    brace_end = motif.find('}', i + 1)
                    if brace_end != -1:
                        brace_content = motif[i + 2:brace_end]
                        if '-' in brace_content:
                            parts = brace_content.split('-')
                            n = parts[0].strip()
                            if len(parts) == 2 and parts[1].strip():
                                # Range: {n-m}
                                m = parts[1].strip()
                                regex_pattern += f'.{{{n},{m}}}'
                            else:
                                # Invalid format - escape the brace sequence
                                regex_pattern += re.escape(char) + re.escape('{') + re.escape(brace_content) + re.escape('}')
                                i = brace_end + 1
                                continue
                        else:
                            # Exact: {n}
                            regex_pattern += f'.{{{brace_content.strip()}}}'
                        i = brace_end + 1
                        continue
                # Wildcard - match any characters
                regex_pattern += '.*'
            elif char == '.':
                # Check if followed by curly braces {n} or {n-m}
                if i + 1 < len(motif) and motif[i + 1] == '{':
                    # Find the closing brace
                    brace_end = motif.find('}', i + 1)
                    if brace_end != -1:
                        brace_content = motif[i + 2:brace_end]
                        if '-' in brace_content:
                            parts = brace_content.split('-')
                            n = parts[0].strip()
                            if len(parts) == 2 and parts[1].strip():
                                # Range: {n-m}
                                m = parts[1].strip()
                                regex_pattern += f'.{{{n},{m}}}'
                            else:
                                # Invalid format - escape the brace sequence
                                regex_pattern += re.escape(char) + re.escape('{') + re.escape(brace_content) + re.escape('}')
                                i = brace_end + 1
                                continue
                        else:
                            # Exact: {n}
                            regex_pattern += f'.{{{brace_content.strip()}}}'
                        i = brace_end + 1
                        continue
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
            elif char == '{':
                # Standalone brace - escape it
                regex_pattern += re.escape(char)
            else:
                # Other characters (shouldn't happen with validation)
                regex_pattern += re.escape(char)
            
            i += 1
        
        return regex_pattern
    
    def _convert_motif_to_regex(self, motif: str) -> str:
        """
        Convert SQL LIKE-style motif pattern to regex pattern.
        Helper method to avoid code duplication in search methods.
        
        Args:
            motif: Motif pattern with wildcards (*, ., [], {})
        
        Returns:
            Regex pattern string
        """
        if not motif:
            return ""
        regex_pattern = ""
        i = 0
        while i < len(motif):
            char = motif[i].upper()
            
            if char == '[':
                # Square bracket for explicit alternatives: [ABC] -> [ABC] in regex
                bracket_end = motif.find(']', i + 1)
                if bracket_end != -1:
                    bracket_content = motif[i + 1:bracket_end].upper()
                    # Validate that content contains only amino acids
                    if re.match(r'^[ACDEFGHIKLMNPQRSTVWY]+$', bracket_content):
                        regex_pattern += f'[{bracket_content}]'
                        i = bracket_end + 1
                        continue
                    else:
                        # Invalid bracket content - escape the bracket
                        regex_pattern += re.escape(char)
                else:
                    # Unmatched bracket - escape it
                    regex_pattern += re.escape(char)
            elif char == '*':
                # Check if followed by curly braces {n} or {n-m}
                if i + 1 < len(motif) and motif[i + 1] == '{':
                    # Find the closing brace
                    brace_end = motif.find('}', i + 1)
                    if brace_end != -1:
                        brace_content = motif[i + 2:brace_end]
                        if '-' in brace_content:
                            parts = brace_content.split('-')
                            n = parts[0].strip()
                            if len(parts) == 2 and parts[1].strip():
                                # Range: {n-m}
                                m = parts[1].strip()
                                regex_pattern += f'.{{{n},{m}}}'
                            else:
                                # Invalid format - escape the brace sequence
                                regex_pattern += re.escape(char) + re.escape('{') + re.escape(brace_content) + re.escape('}')
                                i = brace_end + 1
                                continue
                        else:
                            # Exact: {n}
                            regex_pattern += f'.{{{brace_content.strip()}}}'
                        i = brace_end + 1
                        continue
                # Regular wildcard - match any characters
                regex_pattern += '.*'
            elif char == '.':
                # Check if followed by curly braces {n} or {n-m}
                if i + 1 < len(motif) and motif[i + 1] == '{':
                    # Find the closing brace
                    brace_end = motif.find('}', i + 1)
                    if brace_end != -1:
                        brace_content = motif[i + 2:brace_end]
                        if '-' in brace_content:
                            parts = brace_content.split('-')
                            n = parts[0].strip()
                            if len(parts) == 2 and parts[1].strip():
                                # Range: {n-m}
                                m = parts[1].strip()
                                regex_pattern += f'.{{{n},{m}}}'
                            else:
                                # Invalid format - escape the brace sequence
                                regex_pattern += re.escape(char) + re.escape('{') + re.escape(brace_content) + re.escape('}')
                                i = brace_end + 1
                                continue
                        else:
                            # Exact: {n}
                            regex_pattern += f'.{{{brace_content.strip()}}}'
                        i = brace_end + 1
                        continue
                # Single character wildcard
                regex_pattern += '.'
            elif char == '{':
                # Standalone brace - escape it
                regex_pattern += re.escape(char)
            else:
                # Regular character - escape special regex chars
                regex_pattern += re.escape(char)
            
            i += 1
        
        return regex_pattern
    
    def _parse_cdr_length_condition(self, column_name: str, length_str: Optional[str]) -> Optional[str]:
        """
        Parse CDR length string into SQL WHERE clause condition.
        
        Args:
            column_name: Name of the CDR length column (e.g., 'cdr1_length')
            length_str: Input string (e.g., "2", "2-5", ">2", "<5", ">=2", "<=10") or None
            
        Returns:
            SQL condition string or None if input is empty/invalid
        """
        import re
        if not length_str or not length_str.strip():
            return None
        
        length_str = length_str.strip()
        
        # Fixed value: "2" -> "cdr1_length = 2"
        if re.match(r'^\d+$', length_str):
            return f"{column_name} = {int(length_str)}"
        
        # Range: "2-5" -> "cdr1_length >= 2 AND cdr1_length <= 5"
        if re.match(r'^\d+-\d+$', length_str):
            parts = length_str.split('-')
            min_val = int(parts[0])
            max_val = int(parts[1])
            return f"{column_name} >= {min_val} AND {column_name} <= {max_val}"
        
        # Greater than: ">2" -> "cdr1_length > 2"
        if re.match(r'^>\d+$', length_str):
            val = int(length_str[1:])
            return f"{column_name} > {val}"
        
        # Greater than or equal: ">=2" -> "cdr1_length >= 2"
        if re.match(r'^>=\d+$', length_str):
            val = int(length_str[2:])
            return f"{column_name} >= {val}"
        
        # Less than: "<5" -> "cdr1_length < 5"
        if re.match(r'^<\d+$', length_str):
            val = int(length_str[1:])
            return f"{column_name} < {val}"
        
        # Less than or equal: "<=10" -> "cdr1_length <= 10"
        if re.match(r'^<=\d+$', length_str):
            val = int(length_str[2:])
            return f"{column_name} <= {val}"
        
        # If we get here, the input was invalid (should have been caught by validation)
        return None
    
    def _build_gene_pattern(self, column: str, gene: str, force_light_chain: bool = False) -> str:
        """
        Build SQL pattern for gene matching.
        
        Handles:
        - "3" → matches IGHV3-* (not IGHV4-34 or IGHV33-*)
        - "3-" → matches IGHV3-* 
        - "3-23" → matches IGHV3-23*
        - "3-23*01" → matches exact allele
        - For light chains: "2" matches both IGLV2/IGKV2, "L2" matches only IGLV2, "K2" matches only IGKV2
        
        Args:
            column: Column name (v_call, d_call, j_call)
            gene: Gene pattern to match
            
        Returns:
            SQL WHERE condition
        """
        gene = gene.strip()
        
        # Determine if this is a light chain column (allow override for forced light searches)
        is_light_chain = '_light' in column or force_light_chain
        
        # Determine which gene type this column represents
        is_v_gene = 'v_call' in column
        is_d_gene = 'd_call' in column
        is_j_gene = 'j_call' in column
        
        # For light chains, detect Lambda/Kappa prefix (L for Lambda, K for Kappa)
        light_chain_type = None  # None = both, 'L' = Lambda only, 'K' = Kappa only
        if is_light_chain:
            gene_upper = gene.upper()
            # Remove explicit IGK*/IGL* prefixes if present
            for prefix, chain_code in (
                ('IGLV', 'L'),
                ('IGKV', 'K'),
                ('IGLJ', 'L'),
                ('IGKJ', 'K'),
                ('IGLD', 'L'),
                ('IGKD', 'K'),
            ):
                if gene_upper.startswith(prefix):
                    light_chain_type = chain_code
                    gene = gene[len(prefix):]
                    gene_upper = gene.upper()
                    break
            # Check for Lambda/Kappa single-letter prefix (legacy input)
            if gene_upper.startswith('L'):
                light_chain_type = 'L'
                gene = gene[1:] if len(gene) > 1 else gene
                gene_upper = gene.upper()
            elif gene_upper.startswith('K'):
                light_chain_type = 'K'
                gene = gene[1:] if len(gene) > 1 else gene
                gene_upper = gene.upper()
            # Remove leading J for light-chain J genes if provided
            if is_j_gene and gene_upper.startswith('J'):
                gene = gene[1:] if len(gene) > 1 else ''
                gene_upper = gene.upper()
        else:
            # Strip heavy-chain prefixes if provided explicitly
            gene_upper = gene.upper()
            for heavy_prefix in ('IGHV', 'IGHD', 'IGHJ'):
                if gene_upper.startswith(heavy_prefix):
                    gene = gene[len(heavy_prefix):]
                    gene_upper = gene.upper()
                    break
            if is_j_gene and gene_upper.startswith('J'):
                gene = gene[1:] if len(gene) > 1 else ''
                gene_upper = gene.upper()
        
        # If just a number (e.g., "3"), auto-add dash to match family
        if gene.isdigit():
            if not is_j_gene:
                gene = gene + '-'
        
        # Helper function to build light chain pattern
        def build_light_chain_pattern(gene_pattern: str, is_v: bool, is_j: bool) -> tuple:
            """Returns (pattern_string, is_or_pattern)"""
            if is_v:
                if light_chain_type == 'L':
                    return (f"IGLV{gene_pattern}%", False)
                elif light_chain_type == 'K':
                    return (f"IGKV{gene_pattern}%", False)
                else:
                    # Search both Lambda and Kappa
                    return (f"IGLV{gene_pattern}%", f"IGKV{gene_pattern}%", True)
            elif is_j:
                if light_chain_type == 'L':
                    return (f"IGLJ{gene_pattern}%", False)
                elif light_chain_type == 'K':
                    return (f"IGKJ{gene_pattern}%", False)
                else:
                    # Search both Lambda and Kappa
                    return (f"IGLJ{gene_pattern}%", f"IGKJ{gene_pattern}%", True)
            else:
                return (f"IGKV{gene_pattern}%", False)  # Default for other cases
        
        # Build pattern for the specific gene type based on column
        pattern_result = None
        is_or_pattern = False
        
        if gene.endswith('-'):
            # Family search (e.g., "3-"): match IGHV3-* but not IGHV33-*
            if is_v_gene:
                if is_light_chain:
                    pattern_result = build_light_chain_pattern(gene, True, False)
                else:
                    pattern = f"IGHV{gene}%"
            elif is_d_gene:
                pattern = f"IGHD{gene}%" if not is_light_chain else f"IGKD{gene}%"
            elif is_j_gene:
                if is_light_chain:
                    pattern_result = build_light_chain_pattern(gene, False, True)
                else:
                    pattern = f"IGHJ{gene}%"
            else:
                pattern = f"IGHV{gene}%" if not is_light_chain else f"IGKV{gene}%"
        elif '*' in gene:
            # Allele search (e.g., "3-30*01"): match exact allele, * is literal in SQL LIKE
            if is_v_gene:
                if is_light_chain:
                    pattern_result = build_light_chain_pattern(gene, True, False)
                else:
                    pattern = f"IGHV{gene}%"
            elif is_d_gene:
                pattern = f"IGHD{gene}%" if not is_light_chain else f"IGKD{gene}%"
            elif is_j_gene:
                if is_light_chain:
                    pattern_result = build_light_chain_pattern(gene, False, True)
                else:
                    pattern = f"IGHJ{gene}%"
            else:
                pattern = f"IGHV{gene}%" if not is_light_chain else f"IGKV{gene}%"
        elif '-' in gene:
            # Gene search (e.g., "3-30"): match IGHV3-30* but not IGHV3-300*
            # Add * to ensure it matches allele or end of string
            if is_v_gene:
                if is_light_chain:
                    pattern_result = build_light_chain_pattern(gene + '*', True, False)
                else:
                    pattern = f"IGHV{gene}*%"
            elif is_d_gene:
                pattern = f"IGHD{gene}*%" if not is_light_chain else f"IGKD{gene}*%"
            elif is_j_gene:
                if is_light_chain:
                    pattern_result = build_light_chain_pattern(gene + '*', False, True)
                else:
                    pattern = f"IGHJ{gene}*%"
            else:
                pattern = f"IGHV{gene}*%" if not is_light_chain else f"IGKV{gene}*%"
        else:
            # Exact match or already has wildcard
            if is_v_gene:
                if is_light_chain:
                    pattern_result = build_light_chain_pattern(gene, True, False)
                else:
                    pattern = f"IGHV{gene}%"
            elif is_d_gene:
                pattern = f"IGHD{gene}%" if not is_light_chain else f"IGKD{gene}%"
            elif is_j_gene:
                if is_light_chain:
                    pattern_result = build_light_chain_pattern(gene, False, True)
                else:
                    pattern = f"IGHJ{gene}%"
            else:
                pattern = f"IGHV{gene}%" if not is_light_chain else f"IGKV{gene}%"
        
        # Handle pattern result from light chain helper
        if pattern_result is not None:
            if len(pattern_result) == 3 and pattern_result[2]:  # OR pattern
                pattern1, pattern2, _ = pattern_result
                return f"({column} LIKE '{pattern1}' OR {column} LIKE '{pattern2}')"
            else:
                pattern, _ = pattern_result
                return f"{column} LIKE '{pattern}'"
        
        return f"{column} LIKE '{pattern}'"
    
    def search(
        self,
        chain_mode: str = "paired",
        heavy_v: str = "",
        heavy_d: str = "",
        heavy_j: str = "",
        heavy_cdr1_length: Optional[str] = None,
        heavy_cdr2_length: Optional[str] = None,
        heavy_cdr3_length: Optional[str] = None,
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
        light_cdr1_length: Optional[str] = None,
        light_cdr2_length: Optional[str] = None,
        light_cdr3_length: Optional[str] = None,
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
        verbose: bool = False
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
        """Search for antibody sequences.
        
        Args:
            chain_mode: `'paired'`, `'heavy'`, or `'light'` to control which chain logic to apply.
            heavy_*: Heavy-chain filters (used for paired searches and heavy-mode unpaired searches).
            light_*: Light-chain filters (used for paired searches and light-mode unpaired searches).
            full_results: When True return full sequence rows, otherwise return subject-level stats.
            limit: Optional limit for result rows when `full_results` is True.
            verbose: When True, print search summary (total hits, search time, etc.) immediately.
            
        CDR Motif Search Behavior:
            - When similarity=False (default): Exact pattern matching with wildcards (*, ., [], {}).
              The mismatches parameter is ignored in this mode.
            - When similarity=True: Uses amino acid similarity groups. The mismatches parameter controls
              whether similarity groups are applied:
              * mismatches > 0: Allows similar amino acids at each position (e.g., Y matches F, W, Y)
              * mismatches = 0: Requires exact amino acid matches even in similarity mode
        
        Returns:
            Tuple of `(results_df, stats_df, statistics_dict)`.
            - results_df: Full sequence rows if full_results=True (limited), or stats_df if full_results=False
            - stats_df: Subject-level statistics breakdown (always calculated)
            - statistics: Aggregated statistics dictionary
        """
        start_time = time.time()
        
        # #region agent log
        try:
            mem_limit = self.conn.execute("SELECT current_setting('memory_limit')").fetchone()
            _log_debug_event("AntibodySearchEngine.search", "Search started", {
                "chain_mode": chain_mode,
                "full_results": full_results,
                "limit": limit,
                "memory_limit": str(mem_limit[0]) if mem_limit else "unknown"
            })
        except Exception as e:
            _log_debug_event("AntibodySearchEngine.search", "Error logging start", {"error": str(e)})
        # #endregion

        # Debug logging: Track query start
        logger.debug(f"Query started - Chain mode: {chain_mode}, Full results: {full_results}, Limit: {limit}")
        # Add parameter logging
        logger.debug(f"Search params - Heavy V: {heavy_v}, J: {heavy_j}, Light V: {light_v}, J: {light_j}")
        
        resolved_mode = (chain_mode or "").lower()
        if resolved_mode not in {"paired", "heavy", "light"}:
            resolved_mode = "paired" if self.schema.get('search_type') == 'paired' else "heavy"
        if resolved_mode == "paired" and self.schema.get('search_type') != 'paired':
            resolved_mode = "heavy"
        
        if resolved_mode == 'paired':
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
                full_results, limit, start_time, verbose
            )
        else:
            chain_type = 'Light' if resolved_mode == 'light' else 'Heavy'
            v_gene = light_v if chain_type == 'Light' else heavy_v
            d_gene = "" if chain_type == 'Light' else heavy_d
            j_gene = light_j if chain_type == 'Light' else heavy_j
            cdr1_len = light_cdr1_length if chain_type == 'Light' else heavy_cdr1_length
            cdr2_len = light_cdr2_length if chain_type == 'Light' else heavy_cdr2_length
            cdr3_len = light_cdr3_length if chain_type == 'Light' else heavy_cdr3_length
            cdr1_motif_val = light_cdr1_motif if chain_type == 'Light' else heavy_cdr1_motif
            cdr2_motif_val = light_cdr2_motif if chain_type == 'Light' else heavy_cdr2_motif
            cdr3_motif_val = light_cdr3_motif if chain_type == 'Light' else heavy_cdr3_motif
            cdr1_sim = light_cdr1_similarity if chain_type == 'Light' else heavy_cdr1_similarity
            cdr2_sim = light_cdr2_similarity if chain_type == 'Light' else heavy_cdr2_similarity
            cdr3_sim = light_cdr3_similarity if chain_type == 'Light' else heavy_cdr3_similarity
            cdr1_mm = light_cdr1_mismatches if chain_type == 'Light' else heavy_cdr1_mismatches
            cdr2_mm = light_cdr2_mismatches if chain_type == 'Light' else heavy_cdr2_mismatches
            cdr3_mm = light_cdr3_mismatches if chain_type == 'Light' else heavy_cdr3_mismatches
            
            return self._search_unpaired(
                v_gene, d_gene, j_gene,
                cdr1_len, cdr2_len, cdr3_len,
                cdr1_motif_val, cdr2_motif_val, cdr3_motif_val,
                cdr1_sim, cdr2_sim, cdr3_sim,
                cdr1_mm, cdr2_mm, cdr3_mm,
                chain_type,
                full_results, limit, start_time, verbose
            )
    
    def _search_unpaired(
        self,
        ighv: str = "",
        ighd: str = "",
        ighj: str = "",
        cdr1_length: Optional[str] = None,
        cdr2_length: Optional[str] = None,
        cdr3_length: Optional[str] = None,
        cdr1_motif: str = "",
        cdr2_motif: str = "",
        cdr3_motif: str = "",
        cdr1_similarity: bool = False,
        cdr2_similarity: bool = False,
        cdr3_similarity: bool = False,
        cdr1_mismatches: int = 2,
        cdr2_mismatches: int = 2,
        cdr3_mismatches: int = 2,
        chain_type: str = "Heavy",
        full_results: bool = False,
        limit: Optional[int] = None,
        start_time: float = None,
        verbose: bool = False
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
        """Search unpaired data (original implementation)."""
        if start_time is None:
            start_time = time.time()
        
        # Build WHERE clause
        table_name = self.chain_views.get(chain_type, 'antibodies')
        conditions = []
        is_light_unpaired = chain_type.lower() == 'light' if chain_type else False
        
        # Filter by chain column when available (supports light-only datasets)
        # BUT: Skip this filter if we're using a chain-specific view (chain_views),
        # since the view already restricts to that chain type
        is_chain_specific_view = chain_type in self.chain_views
        if chain_type and 'chain' in self.schema.get('available_columns', []) and not is_chain_specific_view:
            conditions.append(f"chain = '{chain_type}'")
        
        # Narrow scan to the selected directories for the requested chain when possible
        source_prefixes = self.chain_dir_prefixes.get(chain_type, set()) if chain_type else set()
        if source_prefixes and 'source_file' in self.schema.get('available_columns', []):
            source_conditions = []
            for prefix in source_prefixes:
                escaped_prefix = prefix.replace("'", "''")
                source_conditions.append(f"source_file LIKE '{escaped_prefix}%'")
            if source_conditions:
                conditions.append(f"({' OR '.join(source_conditions)})")
        
        def _collect_gene_conditions(column: str, value: str, force_light: bool) -> Optional[str]:
            if not value:
                return None
            parts = [part.strip() for part in re.split(r'[,\|]', value) if part.strip()]
            if not parts:
                return None
            patterns = [
                self._build_gene_pattern(column, part, force_light_chain=force_light)
                for part in parts
            ]
            return f"({' OR '.join(patterns)})" if patterns else None
        
        v_clause = _collect_gene_conditions('v_call', ighv, is_light_unpaired)
        if v_clause:
            conditions.append(v_clause)
        
        d_clause = _collect_gene_conditions('d_call', ighd, is_light_unpaired)
        if d_clause:
            conditions.append(d_clause)
        
        j_clause = _collect_gene_conditions('j_call', ighj, is_light_unpaired)
        if j_clause:
            conditions.append(j_clause)
        
        if cdr1_length is not None:
            condition = self._parse_cdr_length_condition('cdr1_length', cdr1_length)
            if condition:
                conditions.append(condition)
        
        if cdr2_length is not None:
            condition = self._parse_cdr_length_condition('cdr2_length', cdr2_length)
            if condition:
                conditions.append(condition)
        
        if cdr3_length is not None:
            condition = self._parse_cdr_length_condition('cdr3_length', cdr3_length)
            if condition:
                conditions.append(condition)
        
        # Use class method instead of duplicate local function
        # When similarity=False: exact pattern matching (mismatches parameter is ignored)
        # When similarity=True: uses similarity groups based on mismatches parameter
        if cdr1_motif:
            if cdr1_similarity:
                # Use similarity pattern with mismatch tolerance
                regex_pattern = self.generate_similarity_pattern(cdr1_motif, cdr1_mismatches)
            else:
                # Exact pattern matching - mismatches parameter is not applicable
                regex_pattern = self._convert_motif_to_regex(cdr1_motif)
            conditions.append(f"cdr1_aa ~ '{regex_pattern}'")
        
        if cdr2_motif:
            if cdr2_similarity:
                # Use similarity pattern with mismatch tolerance
                regex_pattern = self.generate_similarity_pattern(cdr2_motif, cdr2_mismatches)
            else:
                # Exact pattern matching - mismatches parameter is not applicable
                regex_pattern = self._convert_motif_to_regex(cdr2_motif)
            conditions.append(f"cdr2_aa ~ '{regex_pattern}'")
        
        if cdr3_motif:
            if cdr3_similarity:
                # Use similarity pattern with mismatch tolerance
                regex_pattern = self.generate_similarity_pattern(cdr3_motif, cdr3_mismatches)
            else:
                # Exact pattern matching - mismatches parameter is not applicable
                regex_pattern = self._convert_motif_to_regex(cdr3_motif)
            conditions.append(f"cdr3_aa ~ '{regex_pattern}'")
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Log WHERE clause length
        logger.debug(f"Unpaired WHERE clause constructed. Length: {len(where_clause)}")
        
        if full_results:
            logger.debug("Executing unpaired full results query...")
            # Return full sequence data
            query = f"""
                SELECT *
                FROM {table_name}
                WHERE {where_clause}
                {f'LIMIT {limit}' if limit else ''}
            """
            # #region agent log
            start_sample = time.time()
            # #endregion
            results_df = self.conn.execute(query).df()
            # #region agent log
            _log_debug_event("AntibodySearchEngine._search_unpaired", "Sample query completed", {
                "duration": time.time() - start_sample,
                "rows": len(results_df) if not results_df.empty else 0
            })
            # #endregion
            results_df = self._attach_inferred_partners(results_df, chain_type)
            
            # Get subject statistics (can calculate total_hits in same query)
            # #region agent log
            start_stats = time.time()
            # #endregion
            stats_query = f"""
                SELECT 
                    subject,
                    COUNT(*) as hits
                FROM {table_name}
                WHERE {where_clause}
                GROUP BY subject
            """
            stats_df = self.conn.execute(stats_query).df()
            # #region agent log
            _log_debug_event("AntibodySearchEngine._search_unpaired", "Stats query completed", {
                "duration": time.time() - start_stats,
                "subjects": len(stats_df) if not stats_df.empty else 0
            })
            # #endregion
            # Calculate total_hits directly from stats_df while it's in memory
            total_hits = int(stats_df['hits'].sum()) if not stats_df.empty else 0
            
        else:
            logger.debug("Executing unpaired statistics only query...")
            # Return statistics only (much faster)
            query = f"""
                SELECT 
                    subject,
                    COUNT(*) as hits
                FROM {table_name}
                WHERE {where_clause}
                GROUP BY subject
            """
            results_df = self.conn.execute(query).df()
            stats_df = results_df
            # Calculate total_hits directly from stats_df while it's in memory
        total_hits = int(stats_df['hits'].sum()) if not stats_df.empty else 0
        
        # Use the existing metadata view instead of reading parquet files directly!
        # Much more efficient - the view was already created during initialization
        total_sequences_lookup = None
        try:
            chain_filter_clause = ""
            if chain_type:
                chain_filter_clause = f" WHERE lower(chain) = '{chain_type.lower()}'"
            metadata_query = f"""
                SELECT subject, SUM(total_sequences) as total
                FROM metadata{chain_filter_clause}
                GROUP BY subject
            """
            total_sequences_lookup = self.conn.execute(metadata_query).df()
        except Exception:
            total_sequences_lookup = None
        
        # Fallback: derive totals directly from antibodies table if metadata missing
        if (total_sequences_lookup is None or total_sequences_lookup.empty):
            chain_where = ""
            if chain_type and 'chain' in self.schema.get('available_columns', []):
                chain_where = f" WHERE lower(chain) = '{chain_type.lower()}'"
            total_sequences_query = f"""
                SELECT subject, COUNT(*) as total_sequences
                FROM {table_name}
                {chain_where}
                GROUP BY subject
            """
            try:
                total_sequences_lookup = self.conn.execute(total_sequences_query).df()
            except Exception:
                total_sequences_lookup = None
        
        # Build stats_df with ALL subjects (including those with zero hits)
        if total_sequences_lookup is not None and not total_sequences_lookup.empty:
            # Start with all subjects from total_sequences_lookup
            # Rename 'total' column to 'total_sequences' if needed
            if 'total' in total_sequences_lookup.columns:
                all_subjects_df = total_sequences_lookup.rename(columns={'total': 'total_sequences'}).copy()
            else:
                all_subjects_df = total_sequences_lookup.copy()
            
            # Merge with stats_df (subjects with hits) using LEFT join
            # This adds hits column to all subjects, filling with 0 for subjects without hits
            if not stats_df.empty:
                # Prepare stats_df for merge (ensure hits column exists)
                if 'hits' not in stats_df.columns:
                    stats_df['hits'] = 0
                if 'num_files' not in stats_df.columns and 'num_files' in all_subjects_df.columns:
                    stats_df['num_files'] = 0
                
                # Merge: start from all_subjects_df, add hits from stats_df
                stats_df = all_subjects_df.merge(
                    stats_df[['subject', 'hits'] + (['num_files'] if 'num_files' in stats_df.columns else [])],
                    on='subject',
                    how='left'
                )
                # Fill NaN values (subjects with no hits) with 0
                stats_df['hits'] = stats_df['hits'].fillna(0).astype(int)
                if 'num_files' in stats_df.columns:
                    stats_df['num_files'] = stats_df['num_files'].fillna(0).astype(int)
            else:
                # No hits at all - create stats_df with all subjects and zero hits
                stats_df = all_subjects_df.copy()
                stats_df['hits'] = 0
                if 'num_files' in stats_df.columns:
                    stats_df['num_files'] = 0
            
            # Ensure total_sequences is properly set
            stats_df['total_sequences'] = stats_df['total_sequences'].fillna(0).astype(int)
            
            # Calculate percentage and per_million for all subjects
            stats_df['percentage'] = 0.0
            stats_df.loc[stats_df['total_sequences'] > 0, 'percentage'] = (
                stats_df['hits'] / stats_df['total_sequences'] * 100
            ).round(2)
            stats_df['per_million'] = 0.0
            stats_df.loc[stats_df['total_sequences'] > 0, 'per_million'] = (
                stats_df['hits'] / stats_df['total_sequences'] * 1000000
            ).round(0)
        elif not stats_df.empty:
            # Fallback: if we can't get total_sequences_lookup, use stats_df as-is
            if 'total_sequences' not in stats_df.columns:
                stats_df['total_sequences'] = 0
            stats_df['total_sequences'] = stats_df['total_sequences'].fillna(0).astype(int)
            stats_df['percentage'] = 0.0
            stats_df.loc[stats_df['total_sequences'] > 0, 'percentage'] = (
                stats_df['hits'] / stats_df['total_sequences'] * 100
            ).round(2)
            stats_df['per_million'] = 0.0
            stats_df.loc[stats_df['total_sequences'] > 0, 'per_million'] = (
                stats_df['hits'] / stats_df['total_sequences'] * 1000000
            ).round(0)
        else:
            # No results and no metadata - create empty stats_df with proper columns
            import pandas as pd
            stats_df = pd.DataFrame(columns=['subject', 'hits', 'total_sequences', 'percentage', 'per_million'])
        
        search_time = time.time() - start_time
        
        query_params = {'chain_type': chain_type}
        if chain_type and chain_type.lower() == 'light':
            query_params.update({
                'light_v': ighv,
                'light_j': ighj,
                'light_cdr1_length': cdr1_length,
                'light_cdr2_length': cdr2_length,
                'light_cdr3_length': cdr3_length,
                'light_cdr1_motif': cdr1_motif,
                'light_cdr2_motif': cdr2_motif,
                'light_cdr3_motif': cdr3_motif,
                'light_cdr1_similarity': cdr1_similarity,
                'light_cdr2_similarity': cdr2_similarity,
                'light_cdr3_similarity': cdr3_similarity,
                'light_cdr1_mismatches': cdr1_mismatches,
                'light_cdr2_mismatches': cdr2_mismatches,
                'light_cdr3_mismatches': cdr3_mismatches
            })
        else:
            query_params.update({
                'heavy_v': ighv,
                'heavy_d': ighd,
                'heavy_j': ighj,
                'heavy_cdr1_length': cdr1_length,
                'heavy_cdr2_length': cdr2_length,
                'heavy_cdr3_length': cdr3_length,
                'heavy_cdr1_motif': cdr1_motif,
                'heavy_cdr2_motif': cdr2_motif,
                'heavy_cdr3_motif': cdr3_motif,
                'heavy_cdr1_similarity': cdr1_similarity,
                'heavy_cdr2_similarity': cdr2_similarity,
                'heavy_cdr3_similarity': cdr3_similarity,
                'heavy_cdr1_mismatches': cdr1_mismatches,
                'heavy_cdr2_mismatches': cdr2_mismatches,
                'heavy_cdr3_mismatches': cdr3_mismatches
            })
        
        statistics = {
            'total_hits': total_hits,
            'total_sequences': self.total_sequences,
            'percentage': round(total_hits / self.total_sequences * 100, 2) if self.total_sequences > 0 else 0,
            'per_million': round(total_hits / self.total_sequences * 1000000, 1) if self.total_sequences > 0 else 0,
            'search_time': round(search_time, 2),
            'query_params': query_params
        }

        # Check if any inferred overlays are active (V or J)
        v_lookup = self._inferred_lookup.get('V', {}).get(chain_type.capitalize(), {})
        j_lookup = self._inferred_lookup.get('J', {}).get(chain_type.capitalize(), {})
        overlay_active = bool(v_lookup) or bool(j_lookup)
        statistics['inferred_overlay_active'] = overlay_active
        
        if overlay_active:
            hints = []
            # Build V gene hint if V gene is searched
            if ighv:
                v_hint = self._build_inferred_hint(ighv, chain_type, gene_type='V')
                if v_hint:
                    hints.append(v_hint)
            # Build J gene hint if J gene is searched
            if ighj:
                j_hint = self._build_inferred_hint(ighj, chain_type, gene_type='J')
                if j_hint:
                    hints.append(j_hint)
            
            if hints:
                statistics['inferred_partner_hint'] = " | ".join(hints)
        
        # Print verbose output if requested
        if verbose:
            self._print_search_summary(statistics, chain_type, full_results, limit)
        
        # Debug logging: Track successful query execution details
        try:
            # Calculate total data size in bytes
            results_size = results_df.memory_usage(deep=True).sum() if not results_df.empty else 0
            stats_size = stats_df.memory_usage(deep=True).sum() if not stats_df.empty else 0
            total_data_size = results_size + stats_size
            
            # Format sizes for readability
            def format_size(size_bytes):
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if size_bytes < 1024.0:
                        return f"{size_bytes:.2f} {unit}"
                    size_bytes /= 1024.0
                return f"{size_bytes:.2f} TB"
            
            logger.debug(
                f"Query executed successfully - Chain: {chain_type}, "
                f"Runtime: {search_time:.3f}s, "
                f"Total hits: {total_hits:,}, "
                f"Results size: {format_size(results_size)}, "
                f"Stats size: {format_size(stats_size)}, "
                f"Total data size: {format_size(total_data_size)}"
            )
        except Exception as e:
            logger.debug(f"Error calculating data size for logging: {e}")
        
        # Always return stats_df so users don't need to call search() twice
        # When full_results=False, results_df == stats_df (they're the same)
        
        # #region agent log
        _log_debug_event("AntibodySearchEngine._search_unpaired", "Search completed", {
            "total_hits": total_hits,
            "search_time": search_time,
            "stats_df_rows": len(stats_df) if not stats_df.empty else 0
        })
        # #endregion

        return results_df, stats_df, statistics
    
    def _search_paired(
        self,
        heavy_v: str = "",
        heavy_d: str = "",
        heavy_j: str = "",
        heavy_cdr1_length: Optional[str] = None,
        heavy_cdr2_length: Optional[str] = None,
        heavy_cdr3_length: Optional[str] = None,
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
        light_cdr1_length: Optional[str] = None,
        light_cdr2_length: Optional[str] = None,
        light_cdr3_length: Optional[str] = None,
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
        start_time: float = None,
        verbose: bool = False
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
        """Search paired data with separate heavy and light chain criteria."""
        if start_time is None:
            start_time = time.time()
        
        conditions = []
        
        # Use class method instead of duplicate local function
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
                    condition = self._parse_cdr_length_condition(col, heavy_cdr1_length)
                    if condition:
                        conditions.append(condition)
        
        if heavy_cdr2_length is not None:
            for col in self.schema['length_columns']['cdr2_length']:
                if '_heavy' in col:
                    condition = self._parse_cdr_length_condition(col, heavy_cdr2_length)
                    if condition:
                        conditions.append(condition)
        
        if heavy_cdr3_length is not None:
            for col in self.schema['length_columns']['cdr3_length']:
                if '_heavy' in col:
                    condition = self._parse_cdr_length_condition(col, heavy_cdr3_length)
                    if condition:
                        conditions.append(condition)
        
        # Heavy chain CDR motifs
        # When similarity=False: exact pattern matching (mismatches parameter is ignored)
        # When similarity=True: uses similarity groups based on mismatches parameter
        if heavy_cdr1_motif:
            if heavy_cdr1_similarity:
                # Use similarity pattern with mismatch tolerance
                regex_pattern = self.generate_similarity_pattern(heavy_cdr1_motif, heavy_cdr1_mismatches)
            else:
                # Exact pattern matching - mismatches parameter is not applicable
                regex_pattern = self._convert_motif_to_regex(heavy_cdr1_motif)
            for col in self.schema['chain_columns']['cdr1_aa']:
                if '_heavy' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        if heavy_cdr2_motif:
            if heavy_cdr2_similarity:
                # Use similarity pattern with mismatch tolerance
                regex_pattern = self.generate_similarity_pattern(heavy_cdr2_motif, heavy_cdr2_mismatches)
            else:
                # Exact pattern matching - mismatches parameter is not applicable
                regex_pattern = self._convert_motif_to_regex(heavy_cdr2_motif)
            for col in self.schema['chain_columns']['cdr2_aa']:
                if '_heavy' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        if heavy_cdr3_motif:
            if heavy_cdr3_similarity:
                # Use similarity pattern with mismatch tolerance
                regex_pattern = self.generate_similarity_pattern(heavy_cdr3_motif, heavy_cdr3_mismatches)
            else:
                # Exact pattern matching - mismatches parameter is not applicable
                regex_pattern = self._convert_motif_to_regex(heavy_cdr3_motif)
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
                            light_v_conditions.append(self._build_gene_pattern(col, g, force_light_chain=True))
                if light_v_conditions:
                    conditions.append(f"({' OR '.join(light_v_conditions)})")
            else:
                light_v_conditions = []
                for col in self.schema['chain_columns']['v_call']:
                    if '_light' in col:
                        light_v_conditions.append(self._build_gene_pattern(col, light_v, force_light_chain=True))
                if light_v_conditions:
                    conditions.append(f"({' OR '.join(light_v_conditions)})")
        
        if light_d:
            separator = ',' if ',' in light_d else '|'
            if separator in light_d:
                light_d_conditions = []
                for g in light_d.split(separator):
                    for col in self.schema['chain_columns']['d_call']:
                        if '_light' in col:
                            light_d_conditions.append(self._build_gene_pattern(col, g, force_light_chain=True))
                if light_d_conditions:
                    conditions.append(f"({' OR '.join(light_d_conditions)})")
            else:
                light_d_conditions = []
                for col in self.schema['chain_columns']['d_call']:
                    if '_light' in col:
                        light_d_conditions.append(self._build_gene_pattern(col, light_d, force_light_chain=True))
                if light_d_conditions:
                    conditions.append(f"({' OR '.join(light_d_conditions)})")
        
        if light_j:
            separator = ',' if ',' in light_j else '|'
            if separator in light_j:
                light_j_conditions = []
                for g in light_j.split(separator):
                    for col in self.schema['chain_columns']['j_call']:
                        if '_light' in col:
                            light_j_conditions.append(self._build_gene_pattern(col, g, force_light_chain=True))
                if light_j_conditions:
                    conditions.append(f"({' OR '.join(light_j_conditions)})")
            else:
                light_j_conditions = []
                for col in self.schema['chain_columns']['j_call']:
                    if '_light' in col:
                        light_j_conditions.append(self._build_gene_pattern(col, light_j, force_light_chain=True))
                if light_j_conditions:
                    conditions.append(f"({' OR '.join(light_j_conditions)})")
        
        # Light chain CDR lengths
        if light_cdr1_length is not None:
            for col in self.schema['length_columns']['cdr1_length']:
                if '_light' in col:
                    condition = self._parse_cdr_length_condition(col, light_cdr1_length)
                    if condition:
                        conditions.append(condition)
        
        if light_cdr2_length is not None:
            for col in self.schema['length_columns']['cdr2_length']:
                if '_light' in col:
                    condition = self._parse_cdr_length_condition(col, light_cdr2_length)
                    if condition:
                        conditions.append(condition)
        
        if light_cdr3_length is not None:
            for col in self.schema['length_columns']['cdr3_length']:
                if '_light' in col:
                    condition = self._parse_cdr_length_condition(col, light_cdr3_length)
                    if condition:
                        conditions.append(condition)
        
        # Light chain CDR motifs
        # When similarity=False: exact pattern matching (mismatches parameter is ignored)
        # When similarity=True: uses similarity groups based on mismatches parameter
        if light_cdr1_motif:
            if light_cdr1_similarity:
                # Use similarity pattern with mismatch tolerance
                regex_pattern = self.generate_similarity_pattern(light_cdr1_motif, light_cdr1_mismatches)
            else:
                # Exact pattern matching - mismatches parameter is not applicable
                regex_pattern = self._convert_motif_to_regex(light_cdr1_motif)
            for col in self.schema['chain_columns']['cdr1_aa']:
                if '_light' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        if light_cdr2_motif:
            if light_cdr2_similarity:
                # Use similarity pattern with mismatch tolerance
                regex_pattern = self.generate_similarity_pattern(light_cdr2_motif, light_cdr2_mismatches)
            else:
                # Exact pattern matching - mismatches parameter is not applicable
                regex_pattern = self._convert_motif_to_regex(light_cdr2_motif)
            for col in self.schema['chain_columns']['cdr2_aa']:
                if '_light' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        if light_cdr3_motif:
            if light_cdr3_similarity:
                # Use similarity pattern with mismatch tolerance
                regex_pattern = self.generate_similarity_pattern(light_cdr3_motif, light_cdr3_mismatches)
            else:
                # Exact pattern matching - mismatches parameter is not applicable
                regex_pattern = self._convert_motif_to_regex(light_cdr3_motif)
            for col in self.schema['chain_columns']['cdr3_aa']:
                if '_light' in col:
                    conditions.append(f"{col} ~ '{regex_pattern}'")
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Log WHERE clause length
        logger.debug(f"Paired WHERE clause constructed. Length: {len(where_clause)}")
        
        if full_results:
            logger.debug("Executing paired full results query...")
            # Return full sequence data
            query = f"""
                SELECT *
                FROM antibodies
                WHERE {where_clause}
                {f'LIMIT {limit}' if limit else ''}
            """
            # #region agent log
            start_sample = time.time()
            # #endregion
            results_df = self.conn.execute(query).df()
            # #region agent log
            _log_debug_event("AntibodySearchEngine._search_paired", "Sample query completed", {
                "duration": time.time() - start_sample,
                "rows": len(results_df) if not results_df.empty else 0
            })
            # #endregion
            
            # Get subject statistics (can calculate total_hits from this)
            # #region agent log
            start_stats = time.time()
            # #endregion
            stats_query = f"""
                SELECT 
                    subject,
                    COUNT(*) as hits
                FROM antibodies
                WHERE {where_clause}
                GROUP BY subject
            """
            stats_df = self.conn.execute(stats_query).df()
            # #region agent log
            _log_debug_event("AntibodySearchEngine._search_paired", "Stats query completed", {
                "duration": time.time() - start_stats,
                "subjects": len(stats_df) if not stats_df.empty else 0
            })
            # #endregion
            
        else:
            logger.debug("Executing paired statistics only query...")
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
        
            # Calculate total_hits directly from stats_df while it's in memory
        total_hits = int(stats_df['hits'].sum()) if not stats_df.empty else 0
        
        # Use the existing metadata view instead of reading parquet files directly!
        # Much more efficient - the view was already created during initialization
        total_sequences_lookup = None
        try:
            metadata_query = """
                SELECT subject, SUM(total_sequences) as total
                FROM metadata
                GROUP BY subject
            """
            total_sequences_lookup = self.conn.execute(metadata_query).df()
        except Exception:
            total_sequences_lookup = None
        
        if (total_sequences_lookup is None or total_sequences_lookup.empty):
            total_sequences_query = """
                SELECT subject, COUNT(*) as total_sequences
                FROM antibodies
                GROUP BY subject
            """
            try:
                total_sequences_lookup = self.conn.execute(total_sequences_query).df()
            except Exception:
                total_sequences_lookup = None
        
        # Build stats_df with ALL subjects (including those with zero hits)
        if total_sequences_lookup is not None and not total_sequences_lookup.empty:
            # Start with all subjects from total_sequences_lookup
            # Rename 'total' column to 'total_sequences' if needed
            if 'total' in total_sequences_lookup.columns:
                all_subjects_df = total_sequences_lookup.rename(columns={'total': 'total_sequences'}).copy()
            else:
                all_subjects_df = total_sequences_lookup.copy()
            
            # Merge with stats_df (subjects with hits) using LEFT join
            # This adds hits column to all subjects, filling with 0 for subjects without hits
            if not stats_df.empty:
                # Prepare stats_df for merge (ensure hits column exists)
                if 'hits' not in stats_df.columns:
                    stats_df['hits'] = 0
                if 'num_files' not in stats_df.columns and 'num_files' in all_subjects_df.columns:
                    stats_df['num_files'] = 0
                
                # Merge: start from all_subjects_df, add hits from stats_df
                stats_df = all_subjects_df.merge(
                    stats_df[['subject', 'hits'] + (['num_files'] if 'num_files' in stats_df.columns else [])],
                    on='subject',
                    how='left'
                )
                # Fill NaN values (subjects with no hits) with 0
                stats_df['hits'] = stats_df['hits'].fillna(0).astype(int)
                if 'num_files' in stats_df.columns:
                    stats_df['num_files'] = stats_df['num_files'].fillna(0).astype(int)
            else:
                # No hits at all - create stats_df with all subjects and zero hits
                stats_df = all_subjects_df.copy()
                stats_df['hits'] = 0
                if 'num_files' in stats_df.columns:
                    stats_df['num_files'] = 0
            
            # Ensure total_sequences is properly set
            stats_df['total_sequences'] = stats_df['total_sequences'].fillna(0).astype(int)
            
            # Calculate percentage and per_million for all subjects
            stats_df['percentage'] = 0.0
            stats_df.loc[stats_df['total_sequences'] > 0, 'percentage'] = (
                stats_df['hits'] / stats_df['total_sequences'] * 100
            ).round(2)
            stats_df['per_million'] = 0.0
            stats_df.loc[stats_df['total_sequences'] > 0, 'per_million'] = (
                stats_df['hits'] / stats_df['total_sequences'] * 1000000
            ).round(0)
        elif not stats_df.empty:
            # Fallback: if we can't get total_sequences_lookup, use stats_df as-is
            if 'total_sequences' not in stats_df.columns:
                stats_df['total_sequences'] = 0
            stats_df['total_sequences'] = stats_df['total_sequences'].fillna(0).astype(int)
            stats_df['percentage'] = 0.0
            stats_df.loc[stats_df['total_sequences'] > 0, 'percentage'] = (
                stats_df['hits'] / stats_df['total_sequences'] * 100
            ).round(2)
            stats_df['per_million'] = 0.0
            stats_df.loc[stats_df['total_sequences'] > 0, 'per_million'] = (
                stats_df['hits'] / stats_df['total_sequences'] * 1000000
            ).round(0)
        else:
            # No results and no metadata - create empty stats_df with proper columns
            import pandas as pd
            stats_df = pd.DataFrame(columns=['subject', 'hits', 'total_sequences', 'percentage', 'per_million'])
        
        search_time = time.time() - start_time
        
        statistics = {
            'total_hits': total_hits,
            'total_sequences': self.total_sequences,
            'percentage': round(total_hits / self.total_sequences * 100, 2) if self.total_sequences > 0 else 0,
            'per_million': round(total_hits / self.total_sequences * 1000000, 1) if self.total_sequences > 0 else 0,
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
        
        # Print verbose output if requested
        if verbose:
            self._print_search_summary(statistics, "paired", full_results, limit)
        
        # Debug logging: Track successful query execution details
        try:
            # Calculate total data size in bytes
            results_size = results_df.memory_usage(deep=True).sum() if not results_df.empty else 0
            stats_size = stats_df.memory_usage(deep=True).sum() if not stats_df.empty else 0
            total_data_size = results_size + stats_size
            
            # Format sizes for readability
            def format_size(size_bytes):
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if size_bytes < 1024.0:
                        return f"{size_bytes:.2f} {unit}"
                    size_bytes /= 1024.0
                return f"{size_bytes:.2f} TB"
            
            logger.debug(
                f"Query executed successfully - Chain: paired, "
                f"Runtime: {search_time:.3f}s, "
                f"Total hits: {total_hits:,}, "
                f"Results size: {format_size(results_size)}, "
                f"Stats size: {format_size(stats_size)}, "
                f"Total data size: {format_size(total_data_size)}"
            )
        except Exception as e:
            logger.debug(f"Error calculating data size for logging: {e}")
        
        # Always return stats_df so users don't need to call search() twice
        # When full_results=False, results_df == stats_df (they're the same)
        
        # #region agent log
        _log_debug_event("AntibodySearchEngine._search_paired", "Search completed", {
            "total_hits": total_hits,
            "search_time": search_time,
            "stats_df_rows": len(stats_df) if not stats_df.empty else 0
        })
        # #endregion

        return results_df, stats_df, statistics
    
    def _print_search_summary(self, statistics: Dict, chain_mode: str, full_results: bool, limit: Optional[int]):
        """Print a concise summary of search results when verbose=True."""
        total_hits = statistics.get('total_hits', 0)
        search_time = statistics.get('search_time', 0)
        percentage = statistics.get('percentage', 0)
        per_million = statistics.get('per_million', 0)
        
        # Format numbers with thousand separators
        hits_str = f"{total_hits:,}" if total_hits > 0 else "0"
        time_str = f"{search_time:.2f}s" if search_time < 60 else f"{search_time/60:.1f}m"
        
        # Build summary message
        mode_str = chain_mode.capitalize() if chain_mode else "Search"
        result_type = "full sequences" if full_results else "statistics"
        limit_str = f" (limited to {limit:,})" if limit else ""
        
        print(f"{mode_str} search completed: {hits_str} hits found ({percentage:.2f}%, {per_million:.0f} per million)")
        print(f"  Returned {result_type}{limit_str} | Search time: {time_str}")
    
    def get_available_genes(self) -> Dict[str, List[str]]:
        """
        Utility method: Get list of available V, D, J genes in database.
        
        Primarily used for testing, debugging, or programmatic API access.
        Not used by the Streamlit web interface.
        
        Returns:
            Dictionary with keys 'v_genes', 'd_genes', 'j_genes' containing
            sorted lists of available gene names.
        """
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
        """
        Utility method: Get information about the current database configuration.
        
        Primarily used for testing, debugging, or programmatic API access.
        Not used by the Streamlit web interface.
        
        Returns:
            Dictionary containing:
            - 'data_dir': Path to data directory
            - 'db_path': DuckDB database path
            - 'total_sequences': Total number of sequences in database
            - 'is_memory_db': Whether using in-memory database
        """
        return {
            'data_dir': str(self.data_dir),
            'db_path': self.db_path,
            'total_sequences': self.total_sequences,
            'is_memory_db': self.db_path == ":memory:"
        }
    
    ## Thread configuration utility methods (for testing/debugging) ##
    def get_current_threads(self) -> int:
        """
        Utility method: Get the current number of threads DuckDB is using.
        
        Primarily used for testing, debugging, or performance tuning.
        Not used by the Streamlit web interface.
        
        Returns:
            Number of threads currently configured for DuckDB.
        """
        result = self.conn.execute("SELECT current_setting('threads')").fetchone()
        return int(result[0]) if result else 0

    def print_thread_info(self):
        """
        Utility method: Print current thread configuration.
        
        Primarily used for testing, debugging, or performance tuning.
        Not used by the Streamlit web interface.
        """
        threads = self.get_current_threads()
        print(f"Current DuckDB thread count: {threads}")

    def configure_threads(self, num_threads: int):
        """
        Utility method: Configure the number of threads DuckDB uses for query execution.
        
        Primarily used for testing, debugging, or performance tuning.
        Not used by the Streamlit web interface.
        This can be called on an existing connection without reloading the database.
        
        Args:
            num_threads: Number of threads to use (1 to CPU count)
        """
        if num_threads < 1:
            raise ValueError("Number of threads must be at least 1")
        
        self.conn.execute(f"SET threads = {num_threads}")
        print(f"✓ DuckDB reconfigured to use {num_threads} threads")
        
        # Verify the setting
        actual_threads = self.get_current_threads()
        print(f"✓ Current thread setting: {actual_threads}")

    def force_rebuild_metadata(self) -> None:
        """
        Utility method: Force rebuild of registered metadata and dataset views.
        
        Primarily used for testing, debugging, or when database structure changes.
        Not used by the Streamlit web interface (metadata is auto-rebuilt on reload).
        """
        self.schema = self._detect_schema()
        verbose = _get_verbose_default()
        self._register_data(progress_callback=None, verbose=verbose)

    ## Thread configuration utility methods end here ##

    def close(self):
        """
        Utility method: Close database connection.
        
        Primarily used for testing, cleanup, or programmatic API access.
        Not used by the Streamlit web interface (connection persists for session).
        
        Note: Closing the connection will make the engine unusable. Create a new
        instance if you need to perform additional searches.
        """
        self.conn.close()
