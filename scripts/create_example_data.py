#!/usr/bin/env python
"""Build examples/minimal from small real OAS Parquet files already under data/.

Requires a local OAS conversion (data/Heavy, data/Light, data/Paired) only when
regenerating. The committed examples/minimal tree is enough for try-out.

Copies or subsamples a few tiny subject files so the Streamlit Example Search
masks still return hits, while keeping the package well under 1 MB.

Output layout matches what the UI discovers under ABHUNTER_DB_PATH:

  examples/minimal/Heavy/Demo/*.parquet + metadata.parquet
  examples/minimal/Light/Demo/*.parquet + metadata.parquet
  examples/minimal/Paired/Demo/*.parquet + metadata.parquet
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path
from typing import Iterable, List

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "data"
DEFAULT_OUT = PROJECT_ROOT / "examples" / "minimal"

# Motif used by components/search/search_forms.py EXAMPLE_SEARCH_CRITERIA
HEAVY_EXAMPLE_MOTIF_REGEX = re.compile(r".{15}.*[FI]W[ST].{8}.*", re.IGNORECASE)

HEAVY_SOURCE = "Heavy/IGHM/SRR7663068_Heavy_IGHM.parquet"
HEAVY_SUBSAMPLE_N = 50

LIGHT_FILES = [
    # 13 sequences; includes IGKV3 / IGKJ2 / QQY* CDR3 length 9
    "Light/Bulk/SRR8365333_1_Light_Bulk.parquet",
    # 22 sequences; extra diversity
    "Light/Bulk/SRR8365359_1_Light_Bulk.parquet",
]

PAIRED_SOURCE = "Paired/All/Human_colon_16S8157817_S35_1_Paired_All.parquet"
PAIRED_SUBSAMPLE_N = 40


def _require_source(source_root: Path, relative: str) -> Path:
    path = source_root / relative
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run a local OAS download/convert first, or pass --source."
        )
    return path


def _metadata_rows(source_root: Path, relative_paths: Iterable[str]) -> pd.DataFrame:
    """Pull metadata rows for the given files from the per-subdir metadata.parquet."""
    rows: List[pd.DataFrame] = []
    for relative in relative_paths:
        chain, subdir, filename = Path(relative).parts
        meta_path = source_root / chain / subdir / "metadata.parquet"
        if not meta_path.exists():
            raise FileNotFoundError(f"Missing metadata for {relative}: {meta_path}")
        meta = pd.read_parquet(meta_path)
        if "file_path" not in meta.columns:
            raise ValueError(f"{meta_path} has no file_path column")
        match = meta[meta["file_path"] == relative]
        if match.empty:
            match = meta[meta["file_path"].astype(str).str.endswith(filename)]
        if match.empty:
            raise ValueError(f"No metadata row for {relative} in {meta_path}")
        rows.append(match.copy())
    return pd.concat(rows, ignore_index=True)


def _subject_from_meta(source_root: Path, relative: str) -> dict:
    return _metadata_rows(source_root, [relative]).iloc[0].to_dict()


def _write_subsample_metadata(
    out_dir: Path,
    *,
    chain: str,
    filename: str,
    source_relative: str,
    source_root: Path,
    n_sequences: int,
) -> None:
    src_meta = _subject_from_meta(source_root, source_relative)
    meta = pd.DataFrame(
        [
            {
                "file_path": f"{chain}/Demo/{filename}",
                "chain": chain,
                "file_source": src_meta.get(
                    "file_source", filename.replace(".parquet", ".csv")
                ),
                "species": src_meta.get("species", "human"),
                "subject": src_meta.get("subject", f"Demo-{chain}"),
                "disease": src_meta.get("disease", "None"),
                "vaccine": src_meta.get("vaccine", "None"),
                "isotype": src_meta.get("isotype", "All"),
                "total_sequences": n_sequences,
            }
        ]
    )
    meta.to_parquet(out_dir / "metadata.parquet", index=False)


def _write_heavy_subsample(source_root: Path, output_root: Path) -> None:
    """Subsample a real heavy file including Example Search motif hits."""
    src = _require_source(source_root, HEAVY_SOURCE)
    df = pd.read_parquet(src)
    hit_mask = (
        df["d_call"].astype(str).str.contains(r"IGHD3-3", na=False)
        & (df["cdr3_length"] >= 29)
        & df["cdr3_aa"].astype(str).apply(
            lambda s: bool(HEAVY_EXAMPLE_MOTIF_REGEX.search(s))
        )
    )
    hits = df[hit_mask]
    if hits.empty:
        raise RuntimeError(f"No heavy Example Search hits in {HEAVY_SOURCE}")

    others = df[~hit_mask]
    n_others = max(0, HEAVY_SUBSAMPLE_N - len(hits))
    sample = pd.concat([hits, others.head(n_others)], ignore_index=True)

    out_dir = output_root / "Heavy" / "Demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = "demo_heavy_subsample.parquet"
    sample.to_parquet(out_dir / out_name, index=False)
    _write_subsample_metadata(
        out_dir,
        chain="Heavy",
        filename=out_name,
        source_relative=HEAVY_SOURCE,
        source_root=source_root,
        n_sequences=len(sample),
    )
    print(
        f"Wrote Heavy subsample {out_name}: {len(sample)} rows "
        f"({len(hits)} Example Search hits) from {HEAVY_SOURCE}"
    )


def _copy_light_files(source_root: Path, output_root: Path) -> None:
    out_dir = output_root / "Light" / "Demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    for relative in LIGHT_FILES:
        src = _require_source(source_root, relative)
        shutil.copy2(src, out_dir / src.name)
        print(
            f"Copied {relative} ({src.stat().st_size} bytes, "
            f"{len(pd.read_parquet(src))} rows)"
        )

    meta = _metadata_rows(source_root, LIGHT_FILES).copy()
    meta["file_path"] = [
        f"Light/Demo/{Path(p).name}" for p in meta["file_path"].astype(str)
    ]
    meta["chain"] = "Light"
    meta.to_parquet(out_dir / "metadata.parquet", index=False)
    print(f"Wrote {out_dir / 'metadata.parquet'} ({len(meta)} rows)")


def _write_paired_subsample(source_root: Path, output_root: Path) -> None:
    """Write a small real paired subset that includes an Example Search hit."""
    src = _require_source(source_root, PAIRED_SOURCE)
    df = pd.read_parquet(src)
    hit_mask = (
        df["v_call_heavy"].astype(str).str.contains(r"IGHV1-69", na=False)
        & df["j_call_heavy"].astype(str).str.contains(r"IGHJ6", na=False)
        & df["cdr3_length_heavy"].between(18, 22)
        & df["v_call_light"].astype(str).str.contains(r"IGKV3", na=False)
        & df["j_call_light"].astype(str).str.contains(r"IGKJ4", na=False)
        & (df["cdr3_length_light"] == 9)
    )
    hits = df[hit_mask]
    if hits.empty:
        raise RuntimeError(f"No paired Example Search hits in {PAIRED_SOURCE}")

    others = df[~hit_mask]
    n_others = max(0, PAIRED_SUBSAMPLE_N - len(hits))
    sample = pd.concat([hits, others.head(n_others)], ignore_index=True)

    out_dir = output_root / "Paired" / "Demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = "demo_paired_subsample.parquet"
    sample.to_parquet(out_dir / out_name, index=False)
    _write_subsample_metadata(
        out_dir,
        chain="Paired",
        filename=out_name,
        source_relative=PAIRED_SOURCE,
        source_root=source_root,
        n_sequences=len(sample),
    )
    print(
        f"Wrote Paired subsample {out_name}: {len(sample)} rows "
        f"({len(hits)} Example Search hits) from {PAIRED_SOURCE}"
    )


def create_example_data(source_root: Path, output_root: Path) -> None:
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    _write_heavy_subsample(source_root, output_root)
    _copy_light_files(source_root, output_root)
    _write_paired_subsample(source_root, output_root)

    total = sum(p.stat().st_size for p in output_root.rglob("*.parquet"))
    print(f"Example data ready at {output_root} ({total / 1024:.1f} KB total)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Local OAS data root (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output root (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args()
    create_example_data(args.source.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
