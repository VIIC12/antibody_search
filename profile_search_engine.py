#!/usr/bin/env python
"""
Profile the search engine using cProfile to identify bottlenecks.

This script profiles the AntibodySearchEngine search operations and generates
detailed performance reports showing where time is spent.

Based on: https://docs.python.org/3/library/profile.html#module-cProfile
"""

import cProfile
import pstats
from pstats import SortKey
import sys
from pathlib import Path
from typing import Optional, Union

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from search_engine import AntibodySearchEngine


def profile_search(
    data_dir: str = "data/parquet",
    chain_mode: str = "heavy",
    heavy_v: str = "",
    heavy_j: str = "",
    heavy_cdr3_motif: str = "",
    heavy_cdr3_length: Optional[int] = None,
    light_v: str = "",
    light_j: str = "",
    full_results: bool = True,
    limit: Optional[int] = 100,
    output_file: Optional[str] = None,
    sort_by: Union[str, SortKey] = SortKey.CUMULATIVE,
):
    """
    Profile a search operation and generate performance report.

    Args:
        data_dir: Directory containing Parquet files
        chain_mode: Search mode ('paired', 'heavy', or 'light')
        heavy_v: Heavy chain V gene filter
        heavy_j: Heavy chain J gene filter
        heavy_cdr3_motif: Heavy chain CDR3 motif filter
        heavy_cdr3_length: Heavy chain CDR3 length filter
        light_v: Light chain V gene filter
        light_j: Light chain J gene filter
        full_results: Whether to return full sequence data
        limit: Maximum number of results to return
        output_file: Optional file path to save profile report
        sort_by: How to sort stats (SortKey enum or string like 'cumulative', 'time', 'calls')
    """
    print("=" * 80)
    print("Profiling Search Engine")
    print("=" * 80)
    print(f"Data directory: {data_dir}")
    print(f"Chain mode: {chain_mode}")
    print(f"Heavy V: {heavy_v}")
    print(f"Heavy J: {heavy_j}")
    print(f"Heavy CDR3 motif: {heavy_cdr3_motif}")
    print(f"Heavy CDR3 length: {heavy_cdr3_length}")
    print(f"Full results: {full_results}")
    print(f"Limit: {limit}")
    print("=" * 80)
    print()

    # Use context manager for profiling (cProfile supports this)
    with cProfile.Profile() as profiler:
        # Initialize search engine
        print("Initializing search engine...")
        engine = AntibodySearchEngine(
            data_dir=data_dir, verbose=True, db_path=":memory:"
        )
        print("Search engine initialized.")
        print()

        # Execute search
        print("Executing search...")
        results = engine.search(
            chain_mode=chain_mode,
            heavy_v=heavy_v,
            heavy_j=heavy_j,
            heavy_cdr1_length=">=2",
            heavy_cdr3_motif=heavy_cdr3_motif,
            heavy_cdr3_length=heavy_cdr3_length,
            light_v=light_v,
            light_j=light_j,
            full_results=full_results,
            limit=limit,
            verbose=True,
        )

        if results:
            results_df, stats_df, statistics = results
            print(f"Search completed. Found {len(results_df)} results.")
            print(f"Statistics: {statistics}")
        else:
            print("Search completed with no results.")

    print()
    print("=" * 80)
    print("Performance Profile Report")
    print("=" * 80)
    print()

    # Create Stats object from profiler
    stats = pstats.Stats(profiler)

    # Strip directory paths for cleaner output
    stats.strip_dirs()

    # Convert string sort_by to SortKey if needed
    if isinstance(sort_by, str):
        sort_key_map = {
            "cumulative": SortKey.CUMULATIVE,
            "time": SortKey.TIME,
            "calls": SortKey.CALLS,
            "name": SortKey.NAME,
            "tottime": SortKey.TIME,
            "ncalls": SortKey.CALLS,
        }
        sort_key = sort_key_map.get(sort_by.lower(), SortKey.CUMULATIVE)
    else:
        sort_key = sort_by

    # Sort by the specified metric
    stats.sort_stats(sort_key)

    # Print top functions
    print(
        f"Top 50 functions sorted by {sort_key.name if hasattr(sort_key, 'name') else sort_by}:"
    )
    print("-" * 80)
    stats.print_stats(50)

    # Print additional analysis
    print()
    print("=" * 80)
    print("Detailed Analysis")
    print("=" * 80)

    # Print by cumulative time (best for understanding algorithm efficiency)
    print("\nTop 30 functions by cumulative time:")
    print("(Useful for identifying high-level algorithm bottlenecks)")
    print("-" * 80)
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_stats(30)

    # Print by total time (best for identifying hot loops)
    print("\nTop 30 functions by total time:")
    print("(Useful for identifying 'hot loops' that should be optimized)")
    print("-" * 80)
    stats.sort_stats(SortKey.TIME)
    stats.print_stats(30)

    # Print by number of calls (useful for identifying surprising call counts)
    print("\nTop 30 functions by number of calls:")
    print("(Useful for identifying bugs or inline-expansion opportunities)")
    print("-" * 80)
    stats.sort_stats(SortKey.CALLS)
    stats.print_stats(30)

    # Use get_stats_profile() for detailed function analysis (Python 3.9+)
    print("\n" + "=" * 80)
    print("Function Profile Details (Top 10 by total time)")
    print("=" * 80)
    try:
        stats_profile = stats.get_stats_profile()
        func_profiles = stats_profile.func_profiles

        # Sort by total time
        sorted_funcs = sorted(
            func_profiles.items(), key=lambda x: x[1].tottime, reverse=True
        )[:10]

        for func_name, func_profile in sorted_funcs:
            if func_profile.tottime > 0:
                print(f"\nFunction: {func_name}")
                print(f"  Total time: {func_profile.tottime:.4f}s")
                print(f"  Cumulative time: {func_profile.cumulative_time:.4f}s")
                print(f"  Calls: {func_profile.call_count}")
                if func_profile.callers:
                    print("  Called by:")
                    for caller, call_info in list(func_profile.callers.items())[
                        :5
                    ]:
                        print(f"    {caller}: {call_info.call_count} calls")
    except AttributeError:
        # Fallback for Python < 3.9
        print("(Detailed function profile requires Python 3.9+)")

    # Print callers for top functions
    print("\n" + "=" * 80)
    print("Caller Analysis (Top 10 functions by cumulative time)")
    print("=" * 80)
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_callers(10)

    # Print callees for top functions
    print("\n" + "=" * 80)
    print("Callee Analysis (Top 10 functions by cumulative time)")
    print("=" * 80)
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_callees(10)

    # Save to file if requested
    if output_file:
        print(f"\nSaving full profile report to {output_file}...")
        with open(output_file, "w", encoding="utf-8") as f:
            stats.sort_stats(SortKey.CUMULATIVE)
            stats.print_stats(file=f)
            f.write("\n" + "=" * 80 + "\n")
            f.write("Caller Analysis\n")
            f.write("=" * 80 + "\n")
            stats.print_callers(file=f)
            f.write("\n" + "=" * 80 + "\n")
            f.write("Callee Analysis\n")
            f.write("=" * 80 + "\n")
            stats.print_callees(file=f)
        print(f"Profile report saved to {output_file}")

    return profiler, stats


def main():
    """Main entry point with example profiling scenarios."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Profile the search engine to identify bottlenecks"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/parquet",
        help="Directory containing Parquet files (default: data/parquet)",
    )
    parser.add_argument(
        "--chain-mode",
        type=str,
        choices=["paired", "heavy", "light"],
        default="heavy",
        help="Search mode (default: heavy)",
    )
    parser.add_argument(
        "--heavy-v",
        type=str,
        default="",
        help="Heavy chain V gene filter (default: IGHV3-23)",
    )
    parser.add_argument(
        "--heavy-j", type=str, default="", help="Heavy chain J gene filter"
    )
    parser.add_argument(
        "--heavy-cdr3-motif",
        type=str,
        default="",
        help="Heavy chain CDR3 motif filter",
    )
    parser.add_argument(
        "--heavy-cdr3-length",
        type=int,
        default=None,
        help="Heavy chain CDR3 length filter",
    )
    parser.add_argument(
        "--light-v", type=str, default="", help="Light chain V gene filter"
    )
    parser.add_argument(
        "--light-j", type=str, default="", help="Light chain J gene filter"
    )
    parser.add_argument(
        "--full-results",
        action="store_true",
        default=True,
        help="Return full sequence data (default: True)",
    )
    parser.add_argument(
        "--no-full-results",
        dest="full_results",
        action="store_false",
        help="Don't return full sequence data",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of results to return (default: 100)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path for profile report",
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        default="cumulative",
        choices=["cumulative", "time", "calls", "name", "tottime", "ncalls"],
        help="How to sort profile stats: 'cumulative' (algorithm efficiency), "
        "'time' (hot loops), 'calls' (call frequency) (default: cumulative)",
    )

    args = parser.parse_args()

    profile_search(
        data_dir=args.data_dir,
        chain_mode=args.chain_mode,
        heavy_v=args.heavy_v,
        heavy_j=args.heavy_j,
        heavy_cdr3_motif=args.heavy_cdr3_motif,
        heavy_cdr3_length=args.heavy_cdr3_length,
        light_v=args.light_v,
        light_j=args.light_j,
        full_results=args.full_results,
        limit=args.limit,
        output_file=args.output,
        sort_by=args.sort_by,
    )


if __name__ == "__main__":
    main()
