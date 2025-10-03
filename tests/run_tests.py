#!/usr/bin/env python3
"""
Test runner for AntibodySearchEngine tests.

Usage:
    python run_tests.py
    python run_tests.py -v  # verbose output
    python run_tests.py --coverage  # with coverage report
"""

import sys
import subprocess
from pathlib import Path

def run_tests(verbose=False, coverage=False):
    """Run the test suite."""
    test_dir = Path(__file__).parent
    test_file = test_dir / "test_search_engine.py"
    
    cmd = ["python", "-m", "pytest"]
    
    if verbose:
        cmd.append("-v")
    
    if coverage:
        cmd.extend(["--cov=src.search_engine", "--cov-report=html", "--cov-report=term"])
    
    cmd.append(str(test_file))
    
    print(f"Running tests with command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=test_dir.parent)
    return result.returncode

if __name__ == "__main__":
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    coverage = "--coverage" in sys.argv
    
    exit_code = run_tests(verbose=verbose, coverage=coverage)
    sys.exit(exit_code)
