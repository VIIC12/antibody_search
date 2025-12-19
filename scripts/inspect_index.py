#!/usr/bin/env python3
"""
Inspect the OAS JSON index (data/oas_json_index.pkl).
"""

import pickle
import json
from pathlib import Path
from typing import Dict, List, NamedTuple

# Define the classes that were used to create the pickle file
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

def inspect_index():
    """Inspect the JSON index and show detailed information."""
    index_file = Path("data/oas_json_index.pkl")
    
    if not index_file.exists():
        print("❌ Index file not found!")
        return
    
    print("📊 Loading JSON Index...")
    with open(index_file, 'rb') as f:
        index_data = pickle.load(f)
    
    print(f"📊 Index Structure:")
    print(f"  Type: {type(index_data)}")
    print(f"  Keys: {list(index_data.keys())}")
    
    if 'index' in index_data:
        index = index_data['index']
        print(f"\n📁 Index Contents:")
        print(f"  Total studies: {len(index)}")
        print(f"  Built at: {index_data.get('built_at', 'Unknown')}")
        print(f"  Total JSON files: {index_data.get('total_json_files', 'Unknown')}")
        print(f"  Total with metadata: {index_data.get('total_with_metadata', 'Unknown')}")
        
        # Show study breakdown
        paired_studies = sum(1 for study in index.values() if study.is_paired)
        unpaired_studies = len(index) - paired_studies
        print(f"  Paired studies: {paired_studies}")
        print(f"  Unpaired studies: {unpaired_studies}")
        
        # Show first few studies with detailed metadata
        print(f"\n📋 Sample Studies with Metadata:")
        for i, (study_path, study_info) in enumerate(list(index.items())[:3]):
            print(f"  {i+1}. {study_path}")
            print(f"     Is paired: {study_info.is_paired}")
            print(f"     JSON files: {len(study_info.json_files)}")
            print(f"     Metadata entries: {len(study_info.metadata)}")
            print(f"     Last modified: {study_info.last_modified}")
            
            # Show sample metadata
            if study_info.metadata:
                sample_filename = list(study_info.metadata.keys())[0]
                sample_metadata = study_info.metadata[sample_filename]
                print(f"     Sample metadata from {sample_filename}:")
                print(f"       Keys: {list(sample_metadata.keys())}")
                print(f"       Full metadata:")
                for key, value in sample_metadata.items():
                    print(f"         {key}: {value}")
            print()
        
        # Show statistics about metadata fields
        print(f"📊 Metadata Field Analysis:")
        all_metadata_keys = set()
        for study_info in index.values():
            for metadata in study_info.metadata.values():
                all_metadata_keys.update(metadata.keys())
        
        print(f"  Unique metadata fields found: {len(all_metadata_keys)}")
        print(f"  Sample fields: {list(sorted(all_metadata_keys))[:10]}")
        
        # Show some examples of different field values
        print(f"\n📋 Sample Field Values:")
        field_samples = {}
        for study_info in index.values():
            for metadata in study_info.metadata.values():
                for key, value in metadata.items():
                    if key not in field_samples:
                        field_samples[key] = set()
                    field_samples[key].add(str(value))
                    if len(field_samples[key]) >= 5:  # Limit to 5 examples per field
                        continue
        
        for field, values in list(field_samples.items())[:5]:
            print(f"  {field}: {list(values)[:3]}...")
    
    else:
        print("❌ Invalid index format!")

if __name__ == "__main__":
    inspect_index()
