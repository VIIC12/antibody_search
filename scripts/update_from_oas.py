#!/usr/bin/env python3
"""
OAS Database Update Script - Version 2
Clean, step-by-step approach for indexing and updating OAS data.

Step 1: Build complete JSON index of all studies on the server.
"""

import argparse
import json
import logging
import pickle
import re
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional
from urllib.parse import urljoin

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
    metadata: Dict[str, Dict[str, str]]  # {json_filename: metadata_dict}
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
    # Format: <a href="filename">filename</a> ... date time size
    # This matches the table format: <td><a href="name">name</a></td><td>date</td><td>size</td>
    pattern = r'<a href="([^"]+)">[^<]+</a>.*?(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}).*?(\d+[KMG]?|-)'
    
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


def parse_metadata_json(json_url: str) -> Optional[Dict[str, str]]:
    """
    Download and parse a JSON metadata file.
    
    Args:
        json_url: URL to the JSON file
    
    Returns parsed metadata as dict, or None if parsing failed.
    """
    try:
        response = requests.get(json_url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Extract relevant metadata fields
        metadata = {}
        
        # Map common field names
        field_mapping = {
            'Species': 'species',
            'Disease': 'disease', 
            'Vaccine': 'vaccine',
            'Isotype': 'isotype',
            'Subject ID': 'subject_id',
            'Chain': 'chain'
        }
        
        for json_key, metadata_key in field_mapping.items():
            if json_key in data:
                value = data[json_key]
                if isinstance(value, str):
                    metadata[metadata_key] = value.lower()
                else:
                    metadata[metadata_key] = str(value).lower()
        
        return metadata
        
    except Exception as e:
        logger.debug(f"Failed to parse JSON metadata from {json_url}: {e}")
        return None


def update_json_index_incrementally() -> Dict[str, StudyInfo]:
    """
    Update the JSON index incrementally, only processing changed studies and files.
    
    Returns updated complete index.
    """
    logger.info("🔄 Updating JSON index incrementally...")
    
    # Load existing index
    existing_index = load_json_index()
    
    if not existing_index:
        logger.info("No existing index found, performing full build...")
        return build_complete_json_index()
    
    updated_index = existing_index.copy()
    
    # Scan both paired and unpaired directories
    directories_to_scan = [
        (PAIRED_DIR, True),
        (UNPAIRED_DIR, False)
    ]
    
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


def build_complete_json_index() -> Dict[str, StudyInfo]:
    """
    Build a complete index of all JSON files and their metadata from the OAS server.
    
    Returns dict with study_path as key and StudyInfo as value.
    """
    logger.info("🔍 Building complete JSON index from OAS server...")
    
    complete_index = {}
    
    # Scan both paired and unpaired directories
    directories_to_scan = [
        (PAIRED_DIR, True),
        (UNPAIRED_DIR, False)
    ]
    
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


def inspect_index():
    """Inspect the current JSON index and show statistics."""
    index = load_json_index()
    
    if not index:
        print("❌ No index found!")
        return
    
    print(f"📊 JSON Index Statistics:")
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
    
    # Show some examples
    print(f"\n📋 Sample studies:")
    for i, (study_path, study) in enumerate(list(index.items())[:5]):
        print(f"  {i+1}. {study_path}")
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

Incremental updates:
- Only processes studies that have changed based on directory timestamps
- Only re-parses JSON files that are new or have been modified
- Much faster for regular updates

Examples:
  # Update index incrementally (default behavior)
  python scripts/update_from_oas_v2.py
  
  # Force complete rebuild of the index
  python scripts/update_from_oas_v2.py --rebuild
  
  # Show what would be updated without actually updating
  python scripts/update_from_oas_v2.py --dry-run
  
  # Inspect current index statistics
  python scripts/update_from_oas_v2.py --inspect
        """
    )
    
    parser.add_argument(
        '--rebuild',
        action='store_true',
        help='Force complete rebuild of the JSON index (ignore incremental updates)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without actually updating the index'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--inspect',
        action='store_true',
        help='Inspect the current JSON index and show statistics'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.inspect:
        inspect_index()
        return
    
    logger.info("="*60)
    logger.info("ABDB V3.0 - OAS Database Update Script v2")
    logger.info("Step 1: Build/Update JSON Index with Incremental Updates")
    logger.info("="*60)
    
    # Check if index already exists
    existing_index = load_json_index()
    
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No changes will be saved")
        if existing_index:
            logger.info(f"  📊 Current index: {len(existing_index)} studies")
            total_json_files = sum(len(study.json_files) for study in existing_index.values())
            logger.info(f"  📄 Current JSON files: {total_json_files}")
        
        # Show what would be updated (without actually updating)
        logger.info("  🔄 Would check for updates...")
        # TODO: Implement dry-run logic to show what would be updated
        logger.info("  💡 Dry-run mode completed")
        return
    
    if args.rebuild:
        logger.info("🔨 Force rebuilding complete index...")
        complete_index = build_complete_json_index()
    else:
        if existing_index:
            logger.info("🔄 Updating existing index incrementally...")
            complete_index = update_json_index_incrementally()
        else:
            logger.info("🆕 No existing index found, building complete index...")
            complete_index = build_complete_json_index()
    
    # Save the index
    save_json_index(complete_index)
    
    logger.info("🎉 Step 1 complete! JSON index is ready for searching.")


if __name__ == "__main__":
    main()
