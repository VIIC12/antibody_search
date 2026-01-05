"""
Download manager for handling async download tasks and state management.

This module provides a centralized way to manage background download tasks,
executor lifecycle, and state tracking for all download types.
"""

import streamlit as st
import concurrent.futures
import time
import hashlib
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class DownloadState:
    """State information for a download task."""
    status: str  # "idle", "running", "completed", "failed"
    result: Optional[Dict[str, Any]]
    start_time: Optional[float]
    error: Optional[str]
    download_id: str


class DownloadManager:
    """Manages async download tasks with simplified state management."""
    
    _EXECUTOR_KEY = "_download_manager_executor"
    _MAX_WORKERS = 4
    
    @staticmethod
    def _get_executor() -> concurrent.futures.ProcessPoolExecutor:
        """Get or create shared executor."""
        executor = st.session_state.get(DownloadManager._EXECUTOR_KEY)
        if executor is None:
            executor = concurrent.futures.ProcessPoolExecutor(max_workers=DownloadManager._MAX_WORKERS)
            st.session_state[DownloadManager._EXECUTOR_KEY] = executor
        return executor
    
    @staticmethod
    def _cleanup_executor() -> None:
        """Clean up broken executor."""
        if DownloadManager._EXECUTOR_KEY in st.session_state:
            try:
                executor = st.session_state[DownloadManager._EXECUTOR_KEY]
                executor.shutdown(wait=False)
            except Exception:
                pass
            del st.session_state[DownloadManager._EXECUTOR_KEY]
    
    @staticmethod
    def generate_download_id(
        search_params: Dict[str, Any],
        download_type: str,
        is_paired: bool = False,
        chain_label: Optional[str] = None,
        key_suffix: str = ""
    ) -> str:
        """
        Generate a unique download ID based on search parameters.
        
        Args:
            search_params: Search parameters dictionary
            download_type: Type of download ("full_results", "fasta", "stats", "plots")
            is_paired: Whether this is a paired search
            chain_label: Optional chain label ("paired", "heavy", "light")
            key_suffix: Optional suffix for uniqueness
            
        Returns:
            Unique download ID string
        """
        seed = {
            "search_params": search_params,
            "download_type": download_type,
            "is_paired": is_paired,
            "chain_label": chain_label,
            "key_suffix": key_suffix
        }
        seed_str = str(sorted(seed.items()))
        seed_hash = hashlib.md5(seed_str.encode()).hexdigest()[:12]
        suffix = f"{key_suffix}_" if key_suffix else ""
        return f"{suffix}{download_type}_{seed_hash}"
    
    @staticmethod
    def get_state(download_id: str) -> DownloadState:
        """
        Get current state of a download task, checking for completion if running.
        
        Args:
            download_id: Unique download ID
            
        Returns:
            DownloadState object with current status
        """
        future_key = f"{download_id}_future"
        status_key = f"{download_id}_status"
        result_key = f"{download_id}_result"
        start_time_key = f"{download_id}_start_time"
        
        # Initialize state if not exists
        if status_key not in st.session_state:
            st.session_state[status_key] = "idle"
        if result_key not in st.session_state:
            st.session_state[result_key] = None
        if start_time_key not in st.session_state:
            st.session_state[start_time_key] = None
        
        status = st.session_state[status_key]
        
        # Check if task is complete (non-blocking)
        if status == "running":
            future = st.session_state.get(future_key)
            if future is not None and future.done():
                try:
                    result = future.result()
                    st.session_state[future_key] = None
                    st.session_state[result_key] = result
                    if result.get('success'):
                        st.session_state[status_key] = "completed"
                        # Show toast notification
                        download_type = download_id.split('_')[0] if '_' in download_id else "download"
                        st.toast(f"{download_type.title()} is ready for download!", icon="⬇")
                    else:
                        st.session_state[status_key] = "failed"
                    status = st.session_state[status_key]
                except (concurrent.futures.process.BrokenProcessPool, Exception) as e:
                    # Clean up broken executor
                    DownloadManager._cleanup_executor()
                    st.session_state[future_key] = None
                    st.session_state[status_key] = "failed"
                    st.session_state[result_key] = {'success': False, 'error': str(e)}
                    status = "failed"
        
        return DownloadState(
            status=status,
            result=st.session_state[result_key],
            start_time=st.session_state[start_time_key],
            error=st.session_state[result_key].get('error') if st.session_state[result_key] else None,
            download_id=download_id
        )
    
    @staticmethod
    def submit_task(
        download_id: str,
        task_func,
        *args,
        **kwargs
    ) -> None:
        """
        Submit a download task to the background executor.
        
        Args:
            download_id: Unique download ID
            task_func: Function to execute in background
            *args: Positional arguments for task_func
            **kwargs: Keyword arguments for task_func
        """
        future_key = f"{download_id}_future"
        status_key = f"{download_id}_status"
        result_key = f"{download_id}_result"
        start_time_key = f"{download_id}_start_time"
        
        try:
            executor = DownloadManager._get_executor()
            future = executor.submit(task_func, *args, **kwargs)
            st.session_state[future_key] = future
            st.session_state[start_time_key] = time.time()
            st.session_state[status_key] = "running"
            st.session_state[result_key] = None
        except concurrent.futures.process.BrokenProcessPool:
            # Recreate executor and retry
            DownloadManager._cleanup_executor()
            executor = DownloadManager._get_executor()
            future = executor.submit(task_func, *args, **kwargs)
            st.session_state[future_key] = future
            st.session_state[start_time_key] = time.time()
            st.session_state[status_key] = "running"
            st.session_state[result_key] = None
    
    @staticmethod
    def reset(download_id: str) -> None:
        """
        Reset a download task to idle state.
        
        Args:
            download_id: Unique download ID
        """
        future_key = f"{download_id}_future"
        status_key = f"{download_id}_status"
        result_key = f"{download_id}_result"
        start_time_key = f"{download_id}_start_time"
        
        st.session_state[status_key] = "idle"
        st.session_state[result_key] = None
        st.session_state[start_time_key] = None
        st.session_state[future_key] = None
    
    @staticmethod
    def get_phase_estimate(download_id: str, download_type: str = "default") -> str:
        """
        Estimate current phase based on elapsed time.
        
        Args:
            download_id: Unique download ID
            download_type: Type of download for phase estimation
            
        Returns:
            Phase description string
        """
        state = DownloadManager.get_state(download_id)
        if state.start_time is None:
            return "Initializing..."
        
        elapsed = time.time() - state.start_time
        
        # Phase estimates based on download type
        if download_type == "full_results":
            if elapsed < 3:
                return "Initializing..."
            elif elapsed < 10:
                return "Searching database..."
            elif elapsed < 30:
                return "Processing results..."
            elif elapsed < 60:
                return "Creating Parquet file..."
            else:
                return "Finalizing..."
        elif download_type == "fasta":
            if elapsed < 3:
                return "Initializing..."
            elif elapsed < 10:
                return "Processing..."
            elif elapsed < 30:
                return "Generating..."
            elif elapsed < 60:
                return "Finalizing..."
            else:
                return "Almost done..."
        elif download_type == "plots":
            if elapsed < 3:
                return "Initializing..."
            elif elapsed < 10:
                return "Rendering plots..."
            elif elapsed < 30:
                return "Creating archive..."
            else:
                return "Finalizing..."
        else:
            # Default phase estimation
            if elapsed < 3:
                return "Initializing..."
            elif elapsed < 10:
                return "Processing..."
            elif elapsed < 30:
                return "Generating..."
            else:
                return "Finalizing..."

