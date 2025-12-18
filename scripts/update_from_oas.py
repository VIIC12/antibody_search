#!/usr/bin/env python3
"""
OAS Database Update Script - Version 2
Clean, step-by-step approach for indexing and updating OAS data.

Step 1: Build complete JSON index of all studies on the server.
"""

import argparse
import json
import logging
import os
import pickle
import re
import requests
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional
from urllib.parse import urljoin

# Configure NumExpr to use all available cores
os.environ['NUMEXPR_MAX_THREADS'] = str(os.cpu_count())

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# OAS Server Configuration
OAS_BASE_URL = "https://opig.stats.ox.ac.uk/webapps/ngsdb/"
PAIRED_DIR = "paired/"
UNPAIRED_DIR = "unpaired/"

# Index file location
JSON_INDEX_FILE = "data/oas_json_index.pkl"


class FileInfo(NamedTuple):
    """Information about a file on the server."""
    name: str
    url: str
    size: str
    last_modified: str


class StudyInfo(NamedTuple):
    """Information about a study's JSON files and metadata."""
    study_path: str
    is_paired: bool
    json_files: List[FileInfo]
    metadata: Dict[str, Dict]  # {json_filename: full_metadata_dict}
    last_modified: str  # Study directory last modified timestamp


def parse_directory_listing(html_content: str, base_url: str) -> List[FileInfo]:
    """
    Parse Apache directory listing HTML to extract file information.
    
    Args:
        html_content: HTML content of directory listing
        base_url: Base URL of the directory
    
    Returns list of FileInfo objects.
    """
    files = []
    
    # Pattern to match table rows in Apache directory listing
    # Format: <tr><td>...</td><td><a href="filename">filename</a></td><td align="right">date</td><td align="right">size</td></tr>
    # This matches the exact table structure with proper row boundaries
    pattern = r'<tr><td[^>]*><img[^>]*></td><td><a href="([^"]+)">[^<]+</a></td><td align="right">(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*</td><td align="right">(\d+[KMG]?|-)\s*</td>'
    
    for match in re.finditer(pattern, html_content, re.DOTALL):
        filename = match.group(1)
        last_modified = match.group(2).strip()
        size = match.group(3).strip()
        
        # Skip parent directory links
        if filename.startswith('/') or filename == '../':
            continue
            
        # Skip if size is just a dash (directories)
        if size == '-':
            continue
            
        # Build full URL
        file_url = urljoin(base_url, filename)
        
        files.append(FileInfo(
            name=filename,
            url=file_url,
            size=size,
            last_modified=last_modified
        ))
    
    return files


def get_study_directories(base_url: str, directory: str) -> List[tuple]:
    """
    Get list of study directories from a top-level directory (paired/ or unpaired/).
    
    Args:
        base_url: Base URL for the OAS server
        directory: Directory to scan (e.g., "paired/")
    
    Returns list of (directory_name, last_modified) tuples.
    """
    url = urljoin(base_url, directory)
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Parse directory listing to find directories
        # Look for table rows with folder icons and directory links
        directories = []
        
        # Pattern to match directory entries: <a href="dirname/">dirname/</a> ... date
        pattern = r'<a href="([^/]+/)"[^>]*>[^<]+</a>.*?(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})'
        
        for match in re.finditer(pattern, response.text, re.DOTALL):
            dir_name = match.group(1).rstrip('/')
            last_modified = match.group(2).strip()
            
            # Skip parent directory
            if dir_name == '..':
                continue
                
            directories.append((dir_name, last_modified))
        
        logger.info(f"Found {len(directories)} studies in {directory}")
        return directories
        
    except Exception as e:
        logger.error(f"Failed to get study directories from {directory}: {e}")
        return []


def get_json_files_from_study(base_url: str, study_path: str, is_paired: bool = True) -> List[FileInfo]:
    """
    Get JSON metadata files from a specific study.
    
    Automatically detects whether to use json/ or json_paired/ subdirectory.
    
    Args:
        base_url: Base URL for the OAS server
        study_path: Path to the study directory
        is_paired: Whether this is a paired study
    
    Returns list of FileInfo objects for JSON files.
    """
    # Try both possible subdirectory names
    json_subdirs = ["json_paired/", "json/"] if is_paired else ["json/", "json_paired/"]
    
    for json_subdir in json_subdirs:
        json_url = urljoin(base_url, f"{study_path}/{json_subdir}")
        
        try:
            response = requests.get(json_url, timeout=30)
            response.raise_for_status()
            
            # Parse directory listing for JSON files
            files = parse_directory_listing(response.text, json_url)
            
            # Filter to only JSON files
            json_files = [f for f in files if f.name.endswith('.json')]
            
            if json_files:  # Found JSON files in this subdirectory
                logger.debug(f"Found {len(json_files)} JSON files in {json_url}")
                return json_files
            else:
                logger.debug(f"No JSON files found in {json_url}")
                
        except Exception as e:
            logger.debug(f"Failed to access {json_url}: {e}")
            continue  # Try next subdirectory
    
    # If we get here, neither subdirectory worked
    logger.warning(f"Failed to get JSON files from {study_path} - tried both json/ and json_paired/")
    return []


def parse_metadata_json(json_url: str) -> Optional[Dict]:
    """
    Download and parse a JSON metadata file, saving ALL data.
    
    Args:
        json_url: URL to the JSON file
    
    Returns parsed metadata as dict with ALL fields, or None if parsing failed.
    """
    try:
        response = requests.get(json_url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Return ALL data from JSON file, preserving original structure
        return data
        
    except Exception as e:
        logger.debug(f"Failed to parse JSON metadata from {json_url}: {e}")
        return None


def update_json_index_incrementally(directories: List[str] = None) -> Dict[str, StudyInfo]:
    """
    Update the JSON index incrementally, only processing changed studies and files.
    
    Args:
        directories: List of directories to update ('paired', 'unpaired', or both)
                     If None, updates both directories.
    
    Returns updated complete index.
    """
    logger.info("🔄 Updating JSON index incrementally...")
    
    # Load existing index
    existing_index = load_json_index()
    
    if not existing_index:
        logger.info("No existing index found, performing full build...")
        return build_complete_json_index(directories)
    
    if directories is None:
        directories = ['paired', 'unpaired']
    
    updated_index = existing_index.copy()
    
    # Scan specified directories
    directories_to_scan = []
    if 'paired' in directories:
        directories_to_scan.append((PAIRED_DIR, True))
    if 'unpaired' in directories:
        directories_to_scan.append((UNPAIRED_DIR, False))
    
    stats = {
        'studies_checked': 0,
        'studies_updated': 0,
        'studies_new': 0,
        'studies_unchanged': 0,
        'files_parsed': 0,
        'files_unchanged': 0
    }
    
    for directory, is_paired in directories_to_scan:
        logger.info(f"📁 Checking {directory}...")
        
        # Get all study directories
        study_dirs = get_study_directories(OAS_BASE_URL, directory)
        
        for study_dir, current_timestamp in study_dirs:
            study_path = f"{directory}{study_dir}"
            stats['studies_checked'] += 1
            
            cached_study = updated_index.get(study_path)
            
            # Check if study needs updating
            if not study_needs_update(study_path, current_timestamp, cached_study):
                stats['studies_unchanged'] += 1
                continue
            
            logger.info(f"  📂 Processing: {study_dir}")
            
            # Get current JSON files from server
            current_json_files = get_json_files_from_study(OAS_BASE_URL, study_path, is_paired)
            
            if not current_json_files:
                logger.warning(f"    ⚠️  No JSON files found in {study_path}")
                continue
            
            if not cached_study:
                # New study - parse all files
                stats['studies_new'] += 1
                logger.info(f"    🆕 New study - parsing all {len(current_json_files)} JSON files")
                
                metadata = {}
                for json_file in current_json_files:
                    logger.debug(f"    📄 Parsing: {json_file.name}")
                    parsed_metadata = parse_metadata_json(json_file.url)
                    if parsed_metadata:
                        metadata[json_file.name] = parsed_metadata
                        stats['files_parsed'] += 1
                
                # Create new study info
                study_info = StudyInfo(
                    study_path=study_path,
                    is_paired=is_paired,
                    json_files=current_json_files,
                    metadata=metadata,
                    last_modified=current_timestamp
                )
                
                updated_index[study_path] = study_info
                stats['studies_updated'] += 1
                
            else:
                # Existing study - check for file changes
                stats['studies_updated'] += 1
                new_files, changed_files, unchanged_files = get_changed_files(
                    current_json_files, cached_study.json_files
                )
                
                logger.info(f"    📊 Files: {len(new_files)} new, {len(changed_files)} changed, {len(unchanged_files)} unchanged")
                
                if not new_files and not changed_files:
                    # No file changes, just update timestamp
                    updated_study = StudyInfo(
                        study_path=study_path,
                        is_paired=is_paired,
                        json_files=current_json_files,
                        metadata=cached_study.metadata,
                        last_modified=current_timestamp
                    )
                    updated_index[study_path] = updated_study
                    stats['files_unchanged'] += len(unchanged_files)
                    continue
                
                # Parse new and changed files
                updated_metadata = cached_study.metadata.copy()
                
                files_to_parse = new_files + changed_files
                for json_file in files_to_parse:
                    logger.debug(f"    📄 Parsing: {json_file.name}")
                    parsed_metadata = parse_metadata_json(json_file.url)
                    if parsed_metadata:
                        updated_metadata[json_file.name] = parsed_metadata
                        stats['files_parsed'] += 1
                
                stats['files_unchanged'] += len(unchanged_files)
                
                # Create updated study info
                study_info = StudyInfo(
                    study_path=study_path,
                    is_paired=is_paired,
                    json_files=current_json_files,
                    metadata=updated_metadata,
                    last_modified=current_timestamp
                )
                
                updated_index[study_path] = study_info
    
    # Log statistics
    logger.info(f"🎉 Incremental update complete!")
    logger.info(f"  📊 Studies checked: {stats['studies_checked']}")
    logger.info(f"  🆕 New studies: {stats['studies_new']}")
    logger.info(f"  📝 Updated studies: {stats['studies_updated']}")
    logger.info(f"  ⏭️  Unchanged studies: {stats['studies_unchanged']}")
    logger.info(f"  📄 Files parsed: {stats['files_parsed']}")
    logger.info(f"  ⏭️  Files unchanged: {stats['files_unchanged']}")
    
    total_json_files = sum(len(study.json_files) for study in updated_index.values())
    total_with_metadata = sum(len(study.metadata) for study in updated_index.values())
    
    logger.info(f"  📊 Total studies: {len(updated_index)}")
    logger.info(f"  📄 Total JSON files: {total_json_files}")
    logger.info(f"  📋 JSON files with metadata: {total_with_metadata}")
    
    return updated_index


def determine_indexing_scope(filters: Dict[str, str]) -> List[str]:
    """
    Determine which directories to index based on search criteria.
    
    Args:
        filters: Filter criteria (species, disease, vaccine, chain, isotype)
    
    Returns:
        List of directories to index ('paired', 'unpaired', or both)
    """
    chain_filter = filters.get('Chain')
    
    # If chain filter is specified, only index the relevant directory
    if chain_filter:
        chain_values = [v.strip().lower() for v in str(chain_filter).split()]
        
        # Check if any chain value indicates paired data
        paired_indicators = ['paired']
        unpaired_indicators = ['heavy', 'light']
        
        has_paired = any(indicator in chain_values for indicator in paired_indicators)
        has_unpaired = any(indicator in chain_values for indicator in unpaired_indicators)
        
        if has_paired and not has_unpaired:
            return ['paired']
        elif has_unpaired and not has_paired:
            return ['unpaired']
        # If both or neither, index both directories
    
    # Default: index both directories
    return ['paired', 'unpaired']


def build_complete_json_index(directories: List[str] = None) -> Dict[str, StudyInfo]:
    """
    Build a complete index of all JSON files and their metadata from the OAS server.
    
    Args:
        directories: List of directories to index ('paired', 'unpaired', or both)
                   If None, indexes both directories.
    
    Returns dict with study_path as key and StudyInfo as value.
    """
    if directories is None:
        directories = ['paired', 'unpaired']
    
    logger.info(f"🔍 Building JSON index from OAS server for directories: {', '.join(directories)}")
    
    complete_index = {}
    
    # Scan specified directories
    directories_to_scan = []
    if 'paired' in directories:
        directories_to_scan.append((PAIRED_DIR, True))
    if 'unpaired' in directories:
        directories_to_scan.append((UNPAIRED_DIR, False))
    
    for directory, is_paired in directories_to_scan:
        logger.info(f"📁 Scanning {directory}...")
        
        # Get all study directories
        study_dirs = get_study_directories(OAS_BASE_URL, directory)
        
        for study_dir, last_modified in study_dirs:
            study_path = f"{directory}{study_dir}"
            logger.info(f"  📂 Processing: {study_dir}")
            
            # Get JSON files from this study
            json_files = get_json_files_from_study(OAS_BASE_URL, study_path, is_paired)
            
            if not json_files:
                logger.warning(f"    ⚠️  No JSON files found in {study_path}")
                continue
            
            # Parse metadata for each JSON file
            metadata = {}
            for json_file in json_files:
                logger.debug(f"    📄 Parsing: {json_file.name}")
                
                parsed_metadata = parse_metadata_json(json_file.url)
                if parsed_metadata:
                    metadata[json_file.name] = parsed_metadata
                else:
                    logger.debug(f"    ❌ Failed to parse: {json_file.name}")
            
            # Store study information
            study_info = StudyInfo(
                study_path=study_path,
                is_paired=is_paired,
                json_files=json_files,
                metadata=metadata,
                last_modified=last_modified
            )
            
            complete_index[study_path] = study_info
            
            logger.info(f"    ✅ Indexed {len(metadata)} JSON files with metadata")
    
    logger.info(f"🎉 Complete JSON index built!")
    logger.info(f"  📊 Total studies indexed: {len(complete_index)}")
    
    total_json_files = sum(len(study.json_files) for study in complete_index.values())
    total_with_metadata = sum(len(study.metadata) for study in complete_index.values())
    
    logger.info(f"  📄 Total JSON files: {total_json_files}")
    logger.info(f"  📋 JSON files with metadata: {total_with_metadata}")
    
    return complete_index


def load_json_index() -> Dict[str, StudyInfo]:
    """
    Load the JSON index from disk.
    
    Returns the loaded index or empty dict if file doesn't exist.
    """
    index_file = Path(JSON_INDEX_FILE)
    index_file.parent.mkdir(parents=True, exist_ok=True)
    
    if index_file.exists():
        try:
            logger.info(f"📂 Loading existing JSON index from {index_file}")
            with open(index_file, 'rb') as f:
                index_data = pickle.load(f)
                
                # Handle both old format (direct dict) and new format (with metadata)
                if isinstance(index_data, dict) and 'index' in index_data:
                    return index_data['index']
                else:
                    return index_data
                    
        except Exception as e:
            logger.warning(f"Failed to load JSON index: {e}")
    
    return {}


def load_json_index_metadata() -> Dict:
    """
    Load the JSON index metadata from disk (built_at timestamp, etc.).
    
    Returns dict with metadata or empty dict if file doesn't exist or has old format.
    """
    index_file = Path(JSON_INDEX_FILE)
    
    if index_file.exists():
        try:
            with open(index_file, 'rb') as f:
                index_data = pickle.load(f)
                
                # Check if it's the new format with metadata
                if isinstance(index_data, dict) and 'index' in index_data:
                    # Return metadata (everything except 'index')
                    metadata = {k: v for k, v in index_data.items() if k != 'index'}
                    return metadata
                    
        except Exception as e:
            logger.debug(f"Failed to load JSON index metadata: {e}")
    
    return {}


def save_json_index(index: Dict[str, StudyInfo]):
    """
    Save the JSON index to disk.
    
    Args:
        index: Complete JSON index to save
    """
    try:
        index_file = Path(JSON_INDEX_FILE)
        index_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Add metadata about the index
        index_data = {
            'index': index,
            'built_at': datetime.now().isoformat(),
            'total_studies': len(index),
            'total_json_files': sum(len(study.json_files) for study in index.values()),
            'total_with_metadata': sum(len(study.metadata) for study in index.values())
        }
        
        with open(index_file, 'wb') as f:
            pickle.dump(index_data, f)
        
        logger.info(f"💾 JSON index saved to {index_file}")
        logger.info(f"  📊 {len(index)} studies, {index_data['total_json_files']} JSON files")
        
    except Exception as e:
        logger.error(f"Failed to save JSON index: {e}")


def study_needs_update(study_path: str, current_timestamp: str, cached_study: StudyInfo = None) -> bool:
    """
    Check if a study needs to be updated based on modification timestamp.
    
    Args:
        study_path: Path to the study
        current_timestamp: Current modification timestamp from server
        cached_study: Cached study info from index
    
    Returns True if study needs update.
    """
    if not cached_study:
        logger.debug(f"  📝 New study: {study_path}")
        return True
    
    if current_timestamp != cached_study.last_modified:
        logger.debug(f"  📝 Modified study: {study_path} ({cached_study.last_modified} -> {current_timestamp})")
        return True
    
    logger.debug(f"  ⏭️  Unchanged study: {study_path}")
    return False


def get_changed_files(current_files: List[FileInfo], cached_files: List[FileInfo]) -> tuple:
    """
    Compare current and cached file lists to identify changes.
    
    Args:
        current_files: Current list of files from server
        cached_files: Cached list of files from index
    
    Returns tuple of (new_files, changed_files, unchanged_files)
    """
    # Create lookup dict for cached files
    cached_lookup = {f.name: f for f in cached_files}
    
    new_files = []
    changed_files = []
    unchanged_files = []
    
    for current_file in current_files:
        cached_file = cached_lookup.get(current_file.name)
        
        if not cached_file:
            # New file
            new_files.append(current_file)
        elif current_file.last_modified != cached_file.last_modified:
            # Changed file
            changed_files.append(current_file)
        else:
            # Unchanged file
            unchanged_files.append(current_file)
    
    return new_files, changed_files, unchanged_files


def validate_search_criteria(index: Dict[str, StudyInfo], filters: Dict[str, str]) -> List[str]:
    """
    Validate that search criteria values exist in the index.
    
    Args:
        index: Complete JSON index
        filters: Filter criteria to validate
    
    Returns list of validation errors (empty if all valid).
    """
    errors = []
    
    # Collect all unique values for each field from the index
    field_values = {
        'Species': set(),
        'Disease': set(), 
        'Vaccine': set(),
        'Chain': set(),
        'Isotype': set()
    }
    
    for study_info in index.values():
        for metadata in study_info.metadata.values():
            for field in field_values.keys():
                if field in metadata and metadata[field] is not None:
                    field_values[field].add(str(metadata[field]))
    
    # Check each filter value
    for filter_key, filter_value in filters.items():
        if filter_value is None:  # No filter specified
            continue
            
        if filter_key in field_values:
            available_values = field_values[filter_key]
            
            # Split filter value by spaces to handle multiple selections
            filter_values = [v.strip() for v in str(filter_value).split()]
            invalid_values = []
            
            for filter_val in filter_values:
                if filter_val not in available_values:
                    invalid_values.append(filter_val)
            
            if invalid_values:
                # Find closest matches for better error message
                closest_matches = []
                for invalid_val in invalid_values:
                    invalid_lower = invalid_val.lower()
                    for val in available_values:
                        if invalid_lower in str(val).lower() or str(val).lower() in invalid_lower:
                            closest_matches.append(val)
                
                error_msg = f"No studies found with {filter_key}='{filter_value}'"
                if invalid_values:
                    error_msg += f" (invalid values: {', '.join(invalid_values)})"
                if closest_matches:
                    error_msg += f". Did you mean: {', '.join(sorted(set(closest_matches))[:5])}?"
                else:
                    error_msg += f". Available values: {', '.join(sorted(list(available_values)[:10]))}"
                    if len(available_values) > 10:
                        error_msg += f" (and {len(available_values) - 10} more...)"
                
                errors.append(error_msg)
    
    return errors


def matches_filter_criteria(metadata: Dict, filters: Dict[str, str]) -> bool:
    """
    Check if metadata matches the specified filter criteria.
    
    Args:
        metadata: JSON metadata dictionary
        filters: Filter criteria (species, disease, vaccine, chain, isotype)
                 Values can be space-separated for multiple selections
    
    Returns True if all specified criteria match.
    """
    for filter_key, filter_value in filters.items():
        if filter_value is None:  # No filter specified for this field
            continue
            
        if filter_key in metadata:
            metadata_value = str(metadata[filter_key]).lower()
            
            # Split filter value by spaces to handle multiple selections
            filter_values = [v.strip().lower() for v in str(filter_value).split()]
            
            # Check if metadata value matches any of the specified filter values
            if metadata_value not in filter_values:
                return False
        else:
            # Field not found in metadata
            return False
    
    return True


def parse_file_size(size_str: str) -> int:
    """
    Parse file size string to bytes.
    
    Args:
        size_str: Size string like "1.5K", "2M", "500"
    
    Returns:
        Size in bytes
    """
    size_str = size_str.strip()
    
    if not size_str or size_str == '-':
        return 0
    
    # Remove commas
    size_str = size_str.replace(',', '')
    
    # Try to parse as number with unit
    match = re.match(r'([\d.]+)([KMG]?)', size_str)
    if match:
        number = float(match.group(1))
        unit = match.group(2).upper()
        
        multipliers = {
            '': 1,
            'K': 1024,
            'M': 1024 * 1024,
            'G': 1024 * 1024 * 1024
        }
        
        return int(number * multipliers.get(unit, 1))
    
    # Try to parse as plain number
    try:
        return int(size_str)
    except ValueError:
        logger.warning(f"Could not parse size string: {size_str}")
        return 0


def get_csv_files_for_study(study_path: str, study_info, base_url: str) -> List[Dict]:
    """
    Get CSV.gz files for a study from the server.
    
    Args:
        study_path: Path to the study
        study_info: StudyInfo object
        base_url: Base URL of OAS server
    
    Returns:
        List of file information dicts with 'name', 'size_bytes', 'url'
    """
    csv_files = []
    
    # Determine CSV subdirectory
    if study_info.is_paired:
        csv_subdirs = ["csv_paired/", "csv/"]
    else:
        csv_subdirs = ["csv/"]
    
    # Get CSV.gz files from each subdirectory
    for csv_subdir in csv_subdirs:
        csv_url = f"{base_url}{study_path}/{csv_subdir}"
        
        try:
            response = requests.get(csv_url, timeout=30)
            response.raise_for_status()
            
            logger.debug(f"Accessing CSV directory: {csv_url}")
            
            # Parse directory listing for CSV.gz files
            # Pattern matches: <tr><td>...</td><td><a href="filename">filename</a></td><td align="right">date</td><td align="right">size</td></tr>
            # The actual structure has valign attributes and slightly different formatting
            pattern = r'<tr><td[^>]*><img[^>]*></td><td><a href="([^"]+\.csv\.gz)">[^<]+</a></td><td[^>]*>(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*</td><td align="right">([^<]+)</td>'
            
            matches = list(re.finditer(pattern, response.text, re.DOTALL))
            logger.debug(f"Found {len(matches)} CSV.gz files in {csv_url}")
            
            for match in matches:
                filename = match.group(1)
                last_modified = match.group(2).strip()
                size_str = match.group(3).strip()
                
                size_bytes = parse_file_size(size_str)
                
                # Build full URL
                file_url = f"{csv_url}{filename}"
                
                csv_files.append({
                    'name': filename,
                    'size_bytes': size_bytes,
                    'url': file_url,
                    'last_modified': last_modified
                })
                
        except Exception as e:
            logger.debug(f"Failed to access {csv_url}: {e}")
            continue
    
    return csv_files


def calculate_total_size_for_criteria(index: Dict, filters: Dict[str, str], base_url: str) -> Dict:
    """
    Calculate total file size for files matching the criteria.
    
    Args:
        index: Complete JSON index
        filters: Filter criteria
        base_url: Base URL of OAS server
    
    Returns:
        Dictionary with statistics about matching files
    """
    logger.info("🔍 Calculating file sizes for matching files...")
    
    matching_files = []
    total_size_bytes = 0
    studies_processed = 0
    
    for study_path, study_info in index.items():
        files_to_check = []
        
        # Check each JSON file's metadata to see if it matches
        for json_filename, metadata in study_info.metadata.items():
            if matches_filter_criteria(metadata, filters):
                # This JSON file matches, so we need to find its corresponding CSV.gz file
                csv_filename = json_filename.replace('.json', '.csv.gz')
                files_to_check.append((json_filename, csv_filename, metadata))
        
        if not files_to_check:
            continue
        
        studies_processed += 1
        logger.debug(f"📂 Processing study: {study_path}")
        
        # Get CSV.gz files for this study
        try:
            csv_files = get_csv_files_for_study(study_path, study_info, base_url)
            
            # Create lookup for CSV files by filename
            csv_lookup = {f['name']: f for f in csv_files}
            
            # Find matching files
            for json_filename, csv_filename, metadata in files_to_check:
                if csv_filename in csv_lookup:
                    csv_info = csv_lookup[csv_filename]
                    file_size = csv_info['size_bytes']
                    
                    matching_files.append({
                        'study_path': study_path,
                        'json_filename': json_filename,
                        'csv_filename': csv_filename,
                        'size_bytes': file_size,
                        'metadata': metadata
                    })
                    
                    total_size_bytes += file_size
                    logger.debug(f"  ✓ {csv_filename}: {file_size / (1024*1024):.1f} MB")
                else:
                    logger.warning(f"  ⚠️  CSV file not found: {csv_filename}")
                    
        except Exception as e:
            logger.error(f"  ❌ Failed to get CSV files for {study_path}: {e}")
    
    logger.info(f"📊 File size calculation complete:")
    logger.info(f"  Matching files: {len(matching_files)}")
    logger.info(f"  Studies processed: {studies_processed}")
    
    # Convert to human-readable sizes
    total_size_gb = total_size_bytes / (1024 * 1024 * 1024)
    total_size_mb = total_size_bytes / (1024 * 1024)
    
    return {
        'total_files': len(matching_files),
        'total_size_bytes': total_size_bytes,
        'total_size_gb': total_size_gb,
        'total_size_mb': total_size_mb,
        'matching_files': matching_files,
        'studies_processed': studies_processed
    }


def filter_and_display_matches(index: Dict[str, StudyInfo], filters: Dict[str, str], verbose: bool = False):
    """
    Filter studies based on criteria and display matching studies/JSON files with file size information.
    
    Args:
        index: Complete JSON index
        filters: Filter criteria
        verbose: If True, show detailed file information. If False, show summary only.
    """
    logger.info("🔍 Filtering studies based on criteria...")
    
    # Show active filters
    active_filters = {k: v for k, v in filters.items() if v is not None}
    if active_filters:
        logger.info(f"📋 Active filters: {active_filters}")
    else:
        logger.info("📋 No filters specified - showing all studies")
    
    matching_studies = []
    total_matching_files = 0
    total_matching_sequences = 0
    total_matching_total_sequences = 0
    files_with_unique = 0
    files_with_total = 0
    files_missing_total = 0
    
    for study_path, study_info in index.items():
        matching_files = []
        
        for json_filename, metadata in study_info.metadata.items():
            if matches_filter_criteria(metadata, filters):
                matching_files.append((json_filename, metadata))
        
        if matching_files:
            matching_studies.append((study_path, study_info, matching_files))
            total_matching_files += len(matching_files)
            
            # Calculate unique sequences and total sequences for this study
            study_sequences = 0
            study_total_sequences = 0
            for json_filename, metadata in matching_files:
                # Count unique sequences
                has_unique = 'Unique sequences' in metadata and metadata['Unique sequences'] is not None
                if has_unique:
                    files_with_unique += 1
                    try:
                        unique_seq = metadata['Unique sequences']
                        if isinstance(unique_seq, (int, float)):
                            study_sequences += int(unique_seq)
                        elif isinstance(unique_seq, str) and unique_seq.isdigit():
                            study_sequences += int(unique_seq)
                    except (ValueError, TypeError):
                        pass
                
                # Count total sequences
                has_total = 'Total sequences' in metadata and metadata['Total sequences'] is not None
                if has_total:
                    files_with_total += 1
                    try:
                        total_seq = metadata['Total sequences']
                        if isinstance(total_seq, (int, float)):
                            study_total_sequences += int(total_seq)
                        elif isinstance(total_seq, str) and total_seq.isdigit():
                            study_total_sequences += int(total_seq)
                    except (ValueError, TypeError):
                        pass
                else:
                    files_missing_total += 1
            
            total_matching_sequences += study_sequences
            total_matching_total_sequences += study_total_sequences
    
    # Calculate file sizes for matching files
    size_results = calculate_total_size_for_criteria(index, filters, OAS_BASE_URL)
    
    # Display results
    logger.info(f"\n📊 Filter Results:")
    logger.info(f"  Matching studies: {len(matching_studies)}")
    logger.info(f"  Matching JSON files: {total_matching_files}")
    logger.info(f"  Total unique sequences: {total_matching_sequences:,}")
    logger.info(f"  Total sequences: {total_matching_total_sequences:,}")
    
    # Show warning if some files are missing "Total sequences" value
    if files_missing_total > 0:
        missing_percentage = (files_missing_total / total_matching_files * 100) if total_matching_files > 0 else 0
        logger.warning(f"\n⚠️  WARNING: {files_missing_total} out of {total_matching_files} matching files ({missing_percentage:.1f}%) are missing the 'Total sequences' value.")
        logger.warning(f"   The 'Total sequences' sum shown above ({total_matching_total_sequences:,}) is INCOMPLETE")
        logger.warning(f"   and does not include sequences from these {files_missing_total} files.")
    
    # Display file size information
    logger.info(f"\n💾 File Size Information:")
    logger.info(f"  Total matching files: {size_results['total_files']}")
    logger.info(f"  Total file size: {size_results['total_size_gb']:.2f} GB ({size_results['total_size_mb']:.1f} MB)")
    
    if matching_studies:
        if verbose:
            logger.info(f"\n📋 Matching Studies and JSON Files:")
            for i, (study_path, study_info, matching_files) in enumerate(matching_studies):
                logger.info(f"  {i+1}. {study_path}")
                logger.info(f"     Type: {'Paired' if study_info.is_paired else 'Unpaired'}")
                logger.info(f"     Total JSON files: {len(study_info.json_files)}")
                logger.info(f"     Matching files: {len(matching_files)}")
                logger.info(f"     Last modified: {study_info.last_modified}")
                
                # Show matching files
                for j, (json_filename, metadata) in enumerate(matching_files):
                    logger.info(f"       {j+1}. {json_filename}")
                    logger.info(f"          Species: {metadata.get('Species', 'N/A')}")
                    logger.info(f"          Disease: {metadata.get('Disease', 'N/A')}")
                    logger.info(f"          Vaccine: {metadata.get('Vaccine', 'N/A')}")
                    logger.info(f"          Chain: {metadata.get('Chain', 'N/A')}")
                    logger.info(f"          Isotype: {metadata.get('Isotype', 'N/A')}")
                    logger.info(f"          Author: {metadata.get('Author', 'N/A')}")
                logger.info("")
        else:
            # Show summary only
            logger.info(f"\n📋 Matching Studies Summary:")
            for i, (study_path, study_info, matching_files) in enumerate(matching_studies):
                logger.info(f"  {i+1}. {study_path} ({'Paired' if study_info.is_paired else 'Unpaired'}) - {len(matching_files)} matching files")
            logger.info(f"\n💡 Use --verbose to see detailed file information")
    else:
        logger.info("❌ No studies match the specified criteria")
    
    return matching_studies


def check_existing_files(matching_studies: List, output_dir: Path) -> Dict:
    """
    Check which files already exist and which need to be downloaded/updated.
    
    Args:
        matching_studies: List of matching studies from filter_and_display_matches
        output_dir: Directory where Parquet files are stored
    
    Returns:
        Dictionary with 'existing', 'new', 'updated' file lists
    """
    existing_files = []
    new_files = []
    updated_files = []
    
    for study_path, study_info, matching_files in matching_studies:
        for json_filename, metadata in matching_files:
            # Convert JSON filename to Parquet filename
            parquet_filename = json_filename.replace('.json', '.parquet')
            
            # Determine output subdirectory
            chain_type = metadata.get('Chain', 'Unknown').replace(' ', '_')
            isotype = metadata.get('Isotype', 'Unknown').replace(' ', '_')
            if isotype.lower() == 'all':
                isotype = 'All'
            
            parquet_path = output_dir / chain_type / isotype / parquet_filename
            
            file_info = {
                'study_path': study_path,
                'json_filename': json_filename,
                'parquet_filename': parquet_filename,
                'parquet_path': parquet_path,
                'metadata': metadata
            }
            
            if parquet_path.exists():
                # File exists - check if it needs updating
                # For now, we'll assume any existing file is up-to-date
                # In the future, we could check file modification times or checksums
                existing_files.append(file_info)
            else:
                # File doesn't exist - needs to be downloaded
                new_files.append(file_info)
    
    return {
        'existing': existing_files,
        'new': new_files,
        'updated': updated_files  # For future implementation
    }


def preview_download_plan(matching_studies: List, output_dir: Path):
    """
    Preview what files would be downloaded without actually downloading, including file size information.
    
    Args:
        matching_studies: List of matching studies from filter_and_display_matches
        output_dir: Directory where Parquet files would be stored
    """
    logger.info("🔍 Analyzing download plan...")
    
    file_status = check_existing_files(matching_studies, output_dir)
    
    total_files = len(file_status['existing']) + len(file_status['new']) + len(file_status['updated'])
    
    logger.info(f"\n📊 Download Plan Summary:")
    logger.info(f"  Total matching files: {total_files}")
    logger.info(f"  Files already exist: {len(file_status['existing'])}")
    logger.info(f"  New files to download: {len(file_status['new'])}")
    logger.info(f"  Files to update: {len(file_status['updated'])}")
    
    # Calculate file sizes for new files that would be downloaded
    if file_status['new']:
        logger.info(f"\n📥 New files to download (with sizes):")
        total_download_size_mb = 0
        
        for file_info in file_status['new'][:10]:  # Show first 10
            # Try to get file size from the study info
            study_path = file_info['study_path']
            csv_filename = file_info['json_filename'].replace('.json', '.csv.gz')
            
            # Find the study info to get file size
            study_info = None
            for study_path_check, study_info_check, _ in matching_studies:
                if study_path_check == study_path:
                    study_info = study_info_check
                    break
            
            if study_info:
                try:
                    csv_files = get_csv_files_for_study(study_path, study_info, OAS_BASE_URL)
                    csv_lookup = {f['name']: f for f in csv_files}
                    
                    if csv_filename in csv_lookup:
                        file_size_mb = csv_lookup[csv_filename]['size_bytes'] / (1024 * 1024)
                        total_download_size_mb += file_size_mb
                        logger.info(f"  • {file_info['parquet_filename']}: {file_size_mb:.1f} MB ({file_info['metadata'].get('Species', 'N/A')})")
                    else:
                        logger.info(f"  • {file_info['parquet_filename']}: Size unknown ({file_info['metadata'].get('Species', 'N/A')})")
                except Exception as e:
                    logger.info(f"  • {file_info['parquet_filename']}: Size unknown ({file_info['metadata'].get('Species', 'N/A')})")
            else:
                logger.info(f"  • {file_info['parquet_filename']}: Size unknown ({file_info['metadata'].get('Species', 'N/A')})")
        
        if len(file_status['new']) > 10:
            logger.info(f"  ... and {len(file_status['new']) - 10} more files")
        
        if total_download_size_mb > 0:
            total_download_size_gb = total_download_size_mb / 1024
            logger.info(f"\n💾 Estimated download size: {total_download_size_gb:.2f} GB ({total_download_size_mb:.1f} MB)")
    
    if file_status['existing']:
        logger.info(f"\n✅ Files already downloaded:")
        for file_info in file_status['existing'][:5]:  # Show first 5
            logger.info(f"  • {file_info['parquet_filename']} ({file_info['metadata'].get('Species', 'N/A')})")
        if len(file_status['existing']) > 5:
            logger.info(f"  ... and {len(file_status['existing']) - 5} more")
    
    if file_status['updated']:
        logger.info(f"\n🔄 Files to update:")
        for file_info in file_status['updated']:
            logger.info(f"  • {file_info['parquet_filename']} ({file_info['metadata'].get('Species', 'N/A')})")
    
    logger.info(f"\n💡 Use --download-and-convert to actually download and convert the files.")


def limit_matching_studies(matching_studies: List, max_files: int) -> tuple:
    """
    Limit the number of files in matching_studies to max_files.
    
    Args:
        matching_studies: List of (study_path, study_info, matching_files) tuples
        max_files: Maximum number of files to include
    
    Returns:
        Tuple of (limited_matching_studies, total_files_before_limit, total_files_after_limit)
    """
    if max_files is None:
        total_files = sum(len(files) for _, _, files in matching_studies)
        return matching_studies, total_files, total_files
    
    limited_studies = []
    files_counted = 0
    total_files_before = sum(len(files) for _, _, files in matching_studies)
    
    for study_path, study_info, matching_files in matching_studies:
        if files_counted >= max_files:
            break
        
        # Calculate how many files we can take from this study
        remaining_slots = max_files - files_counted
        files_to_take = min(len(matching_files), remaining_slots)
        
        if files_to_take > 0:
            limited_files = matching_files[:files_to_take]
            limited_studies.append((study_path, study_info, limited_files))
            files_counted += files_to_take
    
    return limited_studies, total_files_before, files_counted


def download_and_convert_study_files(matching_studies: List, tmp_dir: Path, output_dir: Path, keep_csv: bool = False, max_files: int = None) -> bool:
    """
    Download CSV.gz files for a study, convert to Parquet, and clean up.
    
    Args:
        matching_studies: List of matching studies from filter_and_display_matches
        tmp_dir: Temporary directory for downloads
        output_dir: Directory to save converted Parquet files
        keep_csv: If True, keep CSV.gz files in tmp_dir instead of deleting them
        max_files: Maximum number of files to download (None = no limit)
    
    Returns True if all conversions successful.
    """
    logger.info("📥 Starting download and conversion workflow...")
    
    # Apply file limit if specified
    if max_files is not None:
        matching_studies, total_before, total_after = limit_matching_studies(matching_studies, max_files)
        logger.info(f"📊 File limit applied: {max_files} files (out of {total_before} matching files)")
        if total_before > total_after:
            logger.info(f"   ⚠️  Limiting download to first {total_after} files")
    
    # Import conversion functions from convert_to_parquet.py
    import sys
    sys.path.append(str(Path(__file__).parent))
    from convert_to_parquet import convert_file, create_metadata_table
    
    total_files = 0
    successful_conversions = 0
    skipped_files = 0
    conversion_stats = []  # Collect stats for metadata file creation
    
    # Compression statistics
    total_downloaded_mb = 0.0
    total_parquet_mb = 0.0
    
    for study_path, study_info, matching_files in matching_studies:
        logger.info(f"📂 Processing study: {study_path}")
        
        # Get the study directory name
        study_dir = study_path.split('/')[-1]
        
        # Create temporary study subdirectory
        study_tmp_dir = tmp_dir / study_dir
        study_tmp_dir.mkdir(parents=True, exist_ok=True)
        
        # Process each file in this study
        for json_filename, metadata in matching_files:
            # Convert JSON filename to Parquet filename and check if it already exists
            parquet_filename = json_filename.replace('.json', '.parquet')
            
            # Determine output subdirectory
            chain_type = metadata.get('Chain', 'Unknown').replace(' ', '_')
            isotype = metadata.get('Isotype', 'Unknown').replace(' ', '_')
            if isotype.lower() == 'all':
                isotype = 'All'
            
            parquet_path = output_dir / chain_type / isotype / parquet_filename
            
            # Check if file already exists
            if parquet_path.exists():
                logger.info(f"  ⏭️  Skipping {parquet_filename} (already exists)")
                skipped_files += 1
                continue
            
            # Convert JSON filename to CSV.gz filename
            csv_filename = json_filename.replace('.json', '.csv.gz')
            
            # Build CSV.gz URL - try both possible directory structures
            if study_info.is_paired:
                # For paired studies, try csv_paired/ first, then csv/
                csv_urls = [
                    f"{OAS_BASE_URL}{study_path}/csv_paired/{csv_filename}",
                    f"{OAS_BASE_URL}{study_path}/csv/{csv_filename}"
                ]
            else:
                # For unpaired studies, use csv/
                csv_urls = [f"{OAS_BASE_URL}{study_path}/csv/{csv_filename}"]
            
            # Download file to temp directory
            temp_csv_path = study_tmp_dir / csv_filename
            
            # Try each possible URL until one works
            downloaded = False
            logger.info(f"  📥 Downloading: {csv_filename}")
            for csv_url in csv_urls:
                try:
                    response = requests.get(csv_url, timeout=60)
                    response.raise_for_status()
                    
                    with open(temp_csv_path, 'wb') as f:
                        f.write(response.content)
                    
                    file_size_mb = temp_csv_path.stat().st_size / (1024 * 1024)
                    logger.info(f"    ✅ Downloaded: {file_size_mb:.1f} MB")
                    
                    # Convert immediately to Parquet using the imported function
                    logger.info(f"    🔄 Converting to Parquet...")
                    stats = convert_file(temp_csv_path, output_dir, extraction_level=1)
                    
                    if "error" not in stats:
                        successful_conversions += 1
                        conversion_stats.append(stats)  # Collect stats for metadata
                        
                        # Collect compression statistics
                        csv_size_mb = stats.get("input_size_mb", file_size_mb)
                        parquet_size_mb = stats.get("output_size_mb", 0)
                        compression_ratio = stats.get("compression_ratio", 1.0)
                        
                        total_downloaded_mb += csv_size_mb
                        total_parquet_mb += parquet_size_mb
                        
                        logger.info(f"    ✅ Converted successfully: {stats['rows']} rows, {csv_size_mb:.1f}MB → {parquet_size_mb:.1f}MB ({compression_ratio:.1f}x compression)")
                        downloaded = True
                        break  # Success, no need to try other URLs
                    else:
                        logger.error(f"    ❌ Conversion failed: {stats['error']}")
                        break  # Conversion failed, no point trying other URLs
                    
                except Exception as e:
                    # Try next URL if this one failed
                    continue
            
            if not downloaded:
                logger.error(f"    ❌ Failed to download {csv_filename} from any URL")
                # Clean up temp file if it exists
                if temp_csv_path.exists():
                    temp_csv_path.unlink()
                continue
            
            # Delete the CSV.gz file immediately after successful conversion (unless keep_csv is True)
            if temp_csv_path.exists():
                if keep_csv:
                    logger.debug(f"    💾 Kept CSV file: {csv_filename}")
                else:
                    temp_csv_path.unlink()
                    logger.debug(f"    🗑️  Deleted temporary file: {csv_filename}")
            
            total_files += 1
        
        # Remove empty study temp directory
        try:
            study_tmp_dir.rmdir()
            logger.debug(f"    🗑️  Removed empty temp directory: {study_dir}")
        except OSError:
            pass  # Directory not empty or doesn't exist
    
    # Create metadata files for all converted files at the end
    if conversion_stats:
        logger.info("📋 Creating metadata files for converted Parquet files...")
        create_metadata_table(conversion_stats, output_dir)
    
    # Show compression summary
    if successful_conversions > 0:
        overall_compression = total_downloaded_mb / total_parquet_mb if total_parquet_mb > 0 else 1.0
        logger.info(f"\n📊 Compression Summary:")
        logger.info(f"  📥 Total downloaded (CSV.gz): {total_downloaded_mb:.1f} MB")
        logger.info(f"  📦 Total converted (Parquet): {total_parquet_mb:.1f} MB")
        logger.info(f"  🗜️  Overall compression ratio: {overall_compression:.1f}x")
        logger.info(f"  💾 Space saved: {total_downloaded_mb - total_parquet_mb:.1f} MB ({(1 - total_parquet_mb/total_downloaded_mb)*100:.1f}%)")
    
    logger.info(f"🎉 Processing complete! Processed {total_files} files, {successful_conversions} successful conversions, {skipped_files} files already existed")
    return successful_conversions > 0 or skipped_files > 0




def convert_to_parquet(downloaded_files: List[Path], output_dir: Path) -> bool:
    """
    Convert downloaded CSV.gz files to Parquet format using convert_to_parquet.py.
    
    Args:
        downloaded_files: List of downloaded CSV.gz file paths
        output_dir: Directory to save converted Parquet files
    
    Returns True if conversion successful.
    """
    if not downloaded_files:
        logger.warning("No files to convert")
        return False
    
    logger.info("🔄 Converting CSV.gz files to Parquet format...")
    
    # Create temporary directory for conversion
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Copy files to temp directory for conversion
        temp_files = []
        for file_path in downloaded_files:
            temp_file = temp_path / file_path.name
            temp_file.write_bytes(file_path.read_bytes())
            temp_files.append(temp_file)
        
        # Run convert_to_parquet.py
        try:
            cmd = [
                'python', 'scripts/convert_to_parquet.py',
                '--input', str(temp_path),
                '--output', str(output_dir),
                '--extraction-level', '1'
            ]
            
            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path.cwd())
            
            if result.returncode == 0:
                logger.info("✅ Conversion successful!")
                logger.info("Conversion output:")
                for line in result.stdout.split('\n'):
                    if line.strip():
                        logger.info(f"  {line}")
                return True
            else:
                logger.error("❌ Conversion failed!")
                logger.error("Error output:")
                for line in result.stderr.split('\n'):
                    if line.strip():
                        logger.error(f"  {line}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to run conversion: {e}")
            return False


def inspect_index():
    """Inspect the current JSON index and show statistics and available filter options."""
    index = load_json_index()
    index_metadata = load_json_index_metadata()
    
    if not index:
        print("❌ No index found!")
        return
    
    # Display index update information
    print(f"📊 JSON Index Statistics:")
    
    if index_metadata and 'built_at' in index_metadata:
        built_at_str = index_metadata['built_at']
        try:
            built_at = datetime.fromisoformat(built_at_str)
            now = datetime.now()
            age = now - built_at
            
            # Format the age nicely
            if age.days > 0:
                age_str = f"{age.days} day{'s' if age.days != 1 else ''}"
                if age.seconds > 3600:
                    hours = age.seconds // 3600
                    age_str += f" and {hours} hour{'s' if hours != 1 else ''}"
            elif age.seconds > 3600:
                hours = age.seconds // 3600
                minutes = (age.seconds % 3600) // 60
                age_str = f"{hours} hour{'s' if hours != 1 else ''}"
                if minutes > 0:
                    age_str += f" and {minutes} minute{'s' if minutes != 1 else ''}"
            elif age.seconds > 60:
                minutes = age.seconds // 60
                age_str = f"{minutes} minute{'s' if minutes != 1 else ''}"
            else:
                age_str = f"{age.seconds} second{'s' if age.seconds != 1 else ''}"
            
            print(f"  Last updated: {built_at.strftime('%Y-%m-%d %H:%M:%S')} ({age_str} ago)")
            
            # Always warn that index may not be up to date (since --inspect doesn't check server)
            if age.days > 0:
                print(f"  ⚠️  WARNING: Index may not be up to date (last updated {age_str} ago)!")
            else:
                print(f"  ⚠️  WARNING: Index may not be up to date!")
            print(f"     Run the script without --inspect to check for updates on the OAS server.")
        except (ValueError, TypeError) as e:
            print(f"  Last updated: {built_at_str} (could not parse timestamp)")
    else:
        print(f"  ⚠️  WARNING: Index metadata not available (may be from older version)")
        print(f"     Index may not be up to date!")
        print(f"     Run the script without --inspect to update the index and check for new files.")
    
    print(f"  Studies: {len(index)}")
    
    total_json_files = sum(len(study.json_files) for study in index.values())
    total_metadata = sum(len(study.metadata) for study in index.values())
    
    print(f"  JSON files: {total_json_files}")
    print(f"  Metadata entries: {total_metadata}")
    
    # Show study breakdown
    paired_studies = sum(1 for study in index.values() if study.is_paired)
    unpaired_studies = len(index) - paired_studies
    
    print(f"  Paired studies: {paired_studies}")
    print(f"  Unpaired studies: {unpaired_studies}")
    
    # Calculate total unique sequences and total sequences
    total_unique_sequences = 0
    total_sequences = 0
    for study_info in index.values():
        for metadata in study_info.metadata.values():
            # Count unique sequences
            if 'Unique sequences' in metadata and metadata['Unique sequences'] is not None:
                try:
                    # Handle different formats of unique sequences
                    unique_seq = metadata['Unique sequences']
                    if isinstance(unique_seq, (int, float)):
                        total_unique_sequences += int(unique_seq)
                    elif isinstance(unique_seq, str) and unique_seq.isdigit():
                        total_unique_sequences += int(unique_seq)
                except (ValueError, TypeError):
                    # Skip invalid values
                    pass
            
            # Count total sequences
            if 'Total sequences' in metadata and metadata['Total sequences'] is not None:
                try:
                    # Handle different formats of total sequences
                    total_seq = metadata['Total sequences']
                    if isinstance(total_seq, (int, float)):
                        total_sequences += int(total_seq)
                    elif isinstance(total_seq, str) and total_seq.isdigit():
                        total_sequences += int(total_seq)
                except (ValueError, TypeError):
                    # Skip invalid values
                    pass
    
    print(f"  Total unique sequences: {total_unique_sequences:,}")
    print(f"  Total sequences: {total_sequences:,}")
    
    # Show available filter options
    print(f"\n🔍 Available Filter Options:")
    
    # Collect all unique values for each filter field
    field_values = {
        'Species': set(),
        'Disease': set(), 
        'Vaccine': set(),
        'Chain': set(),
        'Isotype': set()
    }
    
    for study_info in index.values():
        for metadata in study_info.metadata.values():
            for field in field_values.keys():
                if field in metadata and metadata[field] is not None:
                    field_values[field].add(str(metadata[field]))
    
    # Display available values for each field
    for field, values in field_values.items():
        sorted_values = sorted(list(values))
        print(f"\n  📋 {field}:")
        print(f"     Total unique values: {len(sorted_values)}")
        
        # Show all values, grouped in lines of 5
        for i in range(0, len(sorted_values), 5):
            line_values = sorted_values[i:i+5]
            quoted_values = [f'"{v}"' for v in line_values]
            print(f"     {', '.join(quoted_values)}")
    
    # Show some examples
    print(f"\n📋 Sample studies:")
    for i, (study_path, study) in enumerate(list(index.items())[:5]):
        print(f"  {i+1}. {study_path}")
        print(f"     Type: {'Paired' if study.is_paired else 'Unpaired'}")
        print(f"     JSON files: {len(study.json_files)}")
        print(f"     Last modified: {study.last_modified}")
        if study.metadata:
            sample_metadata = list(study.metadata.values())[0]
            print(f"     Sample metadata: {sample_metadata}")


def main():
    """Main function - Step 1: Build/Update JSON index with incremental updates."""
    parser = argparse.ArgumentParser(
        description='OAS Database Update Script v2 - Step 1: Build/Update JSON Index',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Step 1: Build or update JSON index of all studies on OAS server.

This step:
- Scans all studies in paired/ and unpaired/ directories
- Downloads and parses JSON metadata files (incrementally if index exists)
- Builds/updates a complete index with metadata for fast searching
- Saves the index to data/oas_json_index.pkl
- Always shows file size information for matching files

Incremental updates:
- Only processes studies that have changed based on directory timestamps
- Only re-parses JSON files that are new or have been modified
- Much faster for regular updates

Examples:
  # Update index incrementally (default behavior) - shows file sizes
  python scripts/update_from_oas.py
  
  # Force complete rebuild of the index - shows file sizes
  python scripts/update_from_oas.py --rebuild
  
  # Inspect current index statistics
  python scripts/update_from_oas.py --inspect
  
  # Search with filters and see file sizes
  python scripts/update_from_oas.py --species "human" --chain "heavy"
  
  # Download only first 10 matching files (for testing)
  python scripts/update_from_oas.py --species "human" --download-and-convert --max-files 10
        """
    )
    
    parser.add_argument(
        '--rebuild',
        action='store_true',
        help='Force complete rebuild of the JSON index (ignore incremental updates)'
    )
    
    # Filtering arguments
    parser.add_argument(
        '--species',
        type=str,
        default=None,
        help='Filter by species (e.g., "human", "mouse", "human mouse"). If not specified, includes all species.'
    )
    
    parser.add_argument(
        '--disease',
        type=str,
        default=None,
        help='Filter by disease (e.g., "SARS-COV-2", "HIV", "None SARS-COV-2"). If not specified, includes all diseases.'
    )
    
    parser.add_argument(
        '--vaccine',
        type=str,
        default=None,
        help='Filter by vaccine (e.g., "Comirnaty", "Vaxzevria", "None Comirnaty"). If not specified, includes all vaccines.'
    )
    
    parser.add_argument(
        '--chain',
        type=str,
        default=None,
        help='Filter by chain type (e.g., "Paired", "Heavy", "Light", "Paired Heavy" for Paired + Heavy chains). If not specified, includes all chain types.'
    )
    
    parser.add_argument(
        '--isotype',
        type=str,
        default=None,
        help='Filter by isotype (e.g., "IGHG", "IGHM", "All IGHG"). If not specified, includes all isotypes.'
    )
    
    parser.add_argument(
        '--inspect',
        action='store_true',
        help='Inspect the current JSON index and show statistics'
    )
    
    parser.add_argument(
        '--download-and-convert',
        action='store_true',
        help='Download and convert matching CSV.gz files to Parquet format'
    )
    
    parser.add_argument(
        '--preview',
        action='store_true',
        help='Preview what files would be downloaded without actually downloading'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed information about matching studies and files'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        default='data',
        help='Output directory for converted Parquet files (default: data)'
    )
    
    parser.add_argument(
        '--tmp-dir',
        type=str,
        default='data/tmp',
        help='Temporary directory for downloads (default: data/tmp)'
    )
    
    parser.add_argument(
        '--keep-csv',
        action='store_true',
        help='Keep downloaded CSV.gz files in tmp-dir instead of deleting them after conversion'
    )
    
    parser.add_argument(
        '--max-files',
        type=int,
        default=None,
        help='Maximum number of files to download (limits downloads even if more files match criteria)'
    )
    
    args = parser.parse_args()
    
    if args.inspect:
        inspect_index()
        return
    
    logger.info("="*60)
    logger.info("ABDB V3.0 - OAS Database Update Script v2")
    logger.info("Step 1: Build/Update JSON Index with Incremental Updates")
    logger.info("="*60)
    
    # Check if index already exists
    # Determine indexing scope based on search criteria
    filters = {
        'Species': args.species,
        'Disease': args.disease,
        'Vaccine': args.vaccine,
        'Chain': args.chain,
        'Isotype': args.isotype
    }
    
    indexing_directories = determine_indexing_scope(filters)
    logger.info(f"🎯 Selective indexing: {', '.join(indexing_directories)} directories")
    
    existing_index = load_json_index()
    
    # Always run Step 1: Update/rebuild index
    if args.rebuild:
        logger.info("🔨 Force rebuilding index for selected directories...")
        complete_index = build_complete_json_index(indexing_directories)
    else:
        if existing_index:
            logger.info("🔄 Updating existing index incrementally...")
            complete_index = update_json_index_incrementally(indexing_directories)
        else:
            logger.info("🆕 No existing index found, building index for selected directories...")
            complete_index = build_complete_json_index(indexing_directories)
    
    # Save the index
    save_json_index(complete_index)
    
    logger.info("🎉 Step 1 complete! JSON index is ready for searching.")
    
    # Step 2: Apply filters and show matching studies/files
    
    # Validate search criteria first
    validation_errors = validate_search_criteria(complete_index, filters)
    if validation_errors:
        logger.error("\n❌ Search criteria validation failed:")
        for error in validation_errors:
            logger.error(f"  • {error}")
        logger.error("\n💡 Please check your search criteria and try again.")
        logger.error("   Use --inspect to see all available filter options.")
        return
    
    # Filter and display matches
    matching_studies = filter_and_display_matches(complete_index, filters, args.verbose)
    
    if matching_studies:
        logger.info(f"\n✅ Found {len(matching_studies)} studies with matching criteria")
        logger.info("📋 These studies contain JSON files that match your filter criteria")
        
        if args.preview:
            logger.info("\n" + "="*60)
            logger.info("Step 2: Preview Download Plan")
            logger.info("="*60)
            
            # Apply file limit if specified for preview
            if args.max_files is not None:
                matching_studies, total_before, total_after = limit_matching_studies(matching_studies, args.max_files)
                logger.info(f"📊 File limit applied: {args.max_files} files (out of {total_before} matching files)")
                if total_before > total_after:
                    logger.info(f"   ⚠️  Preview shows first {total_after} files only")
            
            # Create output directory path for checking
            output_dir = Path(args.output_dir)
            preview_download_plan(matching_studies, output_dir)
            
        elif args.download_and_convert:
            logger.info("\n" + "="*60)
            logger.info("Step 2: Download and Convert Matching Files")
            logger.info("="*60)
            
            # Create output directory
            output_dir = Path(args.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Create temporary directory
            tmp_dir = Path(args.tmp_dir)
            tmp_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                # Download and convert files (with immediate cleanup)
                # Note: download_and_convert_study_files will apply the max_files limit internally
                success = download_and_convert_study_files(matching_studies, tmp_dir, output_dir, args.keep_csv, args.max_files)
                
                if success:
                    logger.info(f"\n🎉 Complete workflow finished!")
                    logger.info(f"📁 Converted files saved to: {output_dir}")
                    if args.keep_csv:
                        logger.info(f"💾 CSV.gz files kept in: {tmp_dir}")
                    else:
                        logger.info(f"📊 Files processed with immediate cleanup")
                else:
                    logger.error("❌ Download and conversion failed!")
                    
            finally:
                # Clean up temporary directory (unless keep_csv is True)
                if not args.keep_csv and tmp_dir.exists():
                    import shutil
                    try:
                        shutil.rmtree(tmp_dir)
                        logger.info(f"🗑️  Cleaned up temporary directory: {tmp_dir}")
                    except Exception as e:
                        logger.warning(f"⚠️  Could not clean up temp directory: {e}")
                elif args.keep_csv:
                    logger.info(f"💾 Temporary directory preserved: {tmp_dir}")
        else:
            logger.info("💡 Next step: Use --preview to see what would be downloaded, or --download-and-convert to download and convert matching CSV.gz files to Parquet")
    else:
        logger.info("\n❌ No studies match the specified criteria")
        logger.info("💡 Try adjusting your filter criteria or use --inspect to see available options")


if __name__ == "__main__":
    main()