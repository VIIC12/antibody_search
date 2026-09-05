#!/usr/bin/env python3
"""
Simple sequential file-size comparison for the ABHunter OAS subset.

Filters: Species=human, Disease=None, Vaccine=None

For each matching file, one at a time:
  1. Download csv.gz  -> add size
  2. Unzip to .csv    -> add size
  3. Convert to parquet (ALL data columns; first-row OAS JSON -> parquet file metadata)
  4. Delete the three files (unless --keep)

Resume-capable: progress is saved after each file in --out.
Already-successful files are skipped on re-run; failed ones are retried.

Needs: oas_json_index.pkl in the current directory (or --index), pandas, pyarrow, requests
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import pickle
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

OAS_BASE_URL = "https://opig.stats.ox.ac.uk/webapps/ngsdb/"
FILTERS = {"Species": "human", "Disease": "None", "Vaccine": "None"}


class FileInfo(NamedTuple):
    name: str
    url: str
    size: str
    last_modified: str


class StudyInfo(NamedTuple):
    study_path: str
    is_paired: bool
    json_files: List[FileInfo]
    metadata: Dict[str, Dict]
    last_modified: str


def bytes_to_gb(n: int) -> float:
    """SI gigabytes (10^9 bytes)."""
    return n / 1_000**3


def bytes_to_mb(n: int) -> float:
    """SI megabytes (10^6 bytes)."""
    return n / 1_000**2


def chain_kind(entry: dict) -> str:
    """Classify as paired / heavy / light from study_path (and filename for unpaired)."""
    study_path = str(entry.get("study_path") or "")
    name = str(entry.get("csv_filename") or "")
    stored = str(entry.get("chain") or "").strip().lower()
    prefix = study_path.split("/")[0].lower() if study_path else ""

    if stored in ("paired", "heavy", "light"):
        return stored
    if prefix == "paired" or stored == "paired":
        return "paired"

    lower_name = name.lower()
    if "_light_" in lower_name or "_light." in lower_name:
        return "light"
    if "_heavy_" in lower_name or "_heavy." in lower_name:
        return "heavy"
    if "paired" in lower_name:
        return "paired"
    return "unknown"


def size_block(n_files: int, gz: int, csv: int, pq: int) -> dict:
    return {
        "n_files": n_files,
        "csv_gz_bytes": gz,
        "csv_bytes": csv,
        "parquet_bytes": pq,
        "csv_gz_gb": round(bytes_to_gb(gz), 4),
        "csv_gb": round(bytes_to_gb(csv), 4),
        "parquet_gb": round(bytes_to_gb(pq), 4),
        "csv_gz_mb": round(bytes_to_mb(gz), 1),
        "csv_mb": round(bytes_to_mb(csv), 1),
        "parquet_mb": round(bytes_to_mb(pq), 1),
    }


def summarize_ok(ok_entries: Dict[str, dict]) -> Dict[str, dict]:
    """SI totals overall and split by paired / heavy / light."""
    groups = {"all": [], "paired": [], "heavy": [], "light": [], "unknown": []}
    for entry in ok_entries.values():
        groups["all"].append(entry)
        groups[chain_kind(entry)].append(entry)

    out = {}
    for key, entries in groups.items():
        if key == "unknown" and not entries:
            continue
        out[key] = size_block(
            len(entries),
            sum(int(v["csv_gz_bytes"]) for v in entries),
            sum(int(v["csv_bytes"]) for v in entries),
            sum(int(v["parquet_bytes"]) for v in entries),
        )
    return out


def resolve_index(path: Optional[Path]) -> Path:
    """Prefer --index, else ./oas_json_index.pkl in the current working directory."""
    if path is not None:
        p = path.expanduser()
        if not p.exists():
            raise FileNotFoundError(f"Index not found: {p}")
        return p.resolve()
    cwd_index = Path.cwd() / "oas_json_index.pkl"
    if cwd_index.exists():
        return cwd_index.resolve()
    raise FileNotFoundError(
        "oas_json_index.pkl not found in the current directory. "
        "Pass --index PATH or run from the directory that contains it."
    )


def load_index(path: Path) -> Dict[str, StudyInfo]:
    sys.modules.setdefault("__main__", sys.modules[__name__])
    with open(path, "rb") as f:
        data = pickle.load(f)
    if isinstance(data, dict) and "index" in data:
        return data["index"]
    return data


def matches(metadata: Dict) -> bool:
    for key, wanted in FILTERS.items():
        if key not in metadata or metadata[key] is None:
            return False
        if str(metadata[key]).lower() != str(wanted).lower():
            return False
    return True


def collect_targets(index: Dict[str, StudyInfo]) -> List[Tuple[str, bool, str, Dict]]:
    """Return list of (study_path, is_paired, csv_filename, metadata)."""
    targets = []
    for study_path, study in index.items():
        for json_name, metadata in study.metadata.items():
            if not matches(metadata):
                continue
            chain = str(metadata.get("Chain", ""))
            if chain not in ("Heavy", "Light", "Paired"):
                continue
            targets.append(
                (
                    study_path,
                    study.is_paired,
                    json_name.replace(".json", ".csv.gz"),
                    metadata,
                )
            )
    return targets


def is_done(entry: dict) -> bool:
    if not entry or not entry.get("ok"):
        return False
    for key in ("csv_gz_bytes", "csv_bytes", "parquet_bytes"):
        if key not in entry or entry[key] is None:
            return False
    return True


def load_progress(path: Path) -> Dict[str, dict]:
    """Load resume progress; empty/corrupt file => start fresh."""
    candidates = [path, path.with_suffix(path.suffix + ".tmp")]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            if candidate.stat().st_size == 0:
                logger.warning(f"Progress file is empty: {candidate}")
                continue
            with open(candidate, "r") as f:
                data = json.load(f)
            files = data.get("files", {}) if isinstance(data, dict) else {}
            if not isinstance(files, dict):
                files = {}
            logger.info(f"Loaded progress: {candidate} ({len(files)} entries)")
            return files
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read progress {candidate}: {e}")
            corrupt = candidate.with_name(candidate.name + ".corrupt")
            try:
                if not corrupt.exists():
                    candidate.replace(corrupt)
            except OSError:
                pass
    logger.info(f"No usable progress at {path} — starting fresh")
    return {}


def save_progress(path: Path, files: Dict[str, dict]) -> None:
    ok_entries = {k: v for k, v in files.items() if is_done(v)}
    failed_entries = {k: v for k, v in files.items() if not is_done(v)}
    payload = {
        "filters": FILTERS,
        "updated_at": datetime.now().isoformat(),
        "units": "SI (GB = 10^9 bytes, MB = 10^6 bytes)",
        "resumed": True,
        "n_ok": len(ok_entries),
        "n_failed": len(failed_entries),
        "totals": summarize_ok(ok_entries),
        "files": files,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def download(urls: List[str], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err: Optional[Exception] = None
    for url in urls:
        try:
            with requests.get(url, stream=True, timeout=(30, 600)) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as out:
                    for chunk in resp.iter_content(chunk_size=4 * 1024 * 1024):
                        if chunk:
                            out.write(chunk)
            if dest.stat().st_size > 0:
                return
        except Exception as e:
            last_err = e
            if dest.exists():
                dest.unlink()
    raise RuntimeError(f"Download failed: {last_err}")


def unzip(csv_gz: Path, csv_path: Path) -> int:
    with gzip.open(csv_gz, "rb") as src, open(csv_path, "wb") as dst:
        shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
    return csv_path.stat().st_size


def read_oas_header(csv_gz: Path) -> Dict:
    """Parse the first-line OAS JSON metadata from a csv.gz."""
    with gzip.open(csv_gz, "rt") as f:
        header = f.readline().strip()
    if header.startswith('"') and header.endswith('"'):
        header = header[1:-1]
    header = header.replace('""', '"')
    return json.loads(header)


def oas_header_to_parquet_metadata(header: Dict) -> Dict[bytes, bytes]:
    """Move every OAS header field into parquet file metadata (string values)."""
    return {
        str(key).encode(): str(value).encode()
        for key, value in header.items()
    }


def to_parquet_all_columns(csv_gz: Path, parquet_path: Path) -> int:
    """Keep every data column; put the full OAS header into parquet file metadata."""
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    file_md = oas_header_to_parquet_metadata(read_oas_header(csv_gz))
    writer = None
    n_rows = 0
    try:
        for chunk in pd.read_csv(
            csv_gz,
            skiprows=1,
            compression="gzip",
            chunksize=100_000,
            low_memory=False,
        ):
            n_rows += len(chunk)
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                schema = table.schema.with_metadata(file_md)
                writer = pq.ParquetWriter(parquet_path, schema, compression="zstd")
                table = table.replace_schema_metadata(schema.metadata)
            writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()

    if writer is None or n_rows == 0:
        if parquet_path.exists():
            parquet_path.unlink()
        raise RuntimeError(f"No data rows in {csv_gz.name}")
    return parquet_path.stat().st_size


def process_one(
    study_path: str,
    is_paired: bool,
    csv_filename: str,
    metadata: Dict,
    work_dir: Path,
    keep: bool = False,
) -> Tuple[int, int, int]:
    if is_paired:
        urls = [
            f"{OAS_BASE_URL}{study_path}/csv_paired/{csv_filename}",
            f"{OAS_BASE_URL}{study_path}/csv/{csv_filename}",
        ]
    else:
        urls = [f"{OAS_BASE_URL}{study_path}/csv/{csv_filename}"]

    stem = csv_filename.replace(".csv.gz", "")
    file_dir = work_dir / stem
    file_dir.mkdir(parents=True, exist_ok=True)

    csv_gz = file_dir / csv_filename
    csv_path = file_dir / f"{stem}.csv"
    parquet_path = file_dir / f"{stem}.parquet"

    try:
        download(urls, csv_gz)
        csv_gz_bytes = csv_gz.stat().st_size
        csv_bytes = unzip(csv_gz, csv_path)
        parquet_bytes = to_parquet_all_columns(csv_gz, parquet_path)
        return csv_gz_bytes, csv_bytes, parquet_bytes
    finally:
        if not keep:
            shutil.rmtree(file_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simple sequential csv.gz / csv / full-column parquet size totals (resumable)"
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=None,
        help="Path to oas_json_index.pkl (default: ./oas_json_index.pkl)",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path.cwd() / "tmp_simple_sizes",
        help="Temp directory for one file at a time (default: ./tmp_simple_sizes)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Only queue the first N remaining files (for testing)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.cwd() / "simple_file_size_totals.json",
        help="Progress + totals JSON (default: ./simple_file_size_totals.json)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep csv.gz / csv / parquet under --workdir (default: delete after each file)",
    )
    args = parser.parse_args()

    index_path = resolve_index(args.index)
    logger.info(f"Index: {index_path}")
    index = load_index(index_path)
    targets = collect_targets(index)

    progress = load_progress(args.out)
    already = sum(1 for _, _, name, _ in targets if is_done(progress.get(name, {})))
    todo = [
        t for t in targets if not is_done(progress.get(t[2], {}))
    ]
    if args.max_files is not None:
        todo = todo[: args.max_files]

    logger.info(f"Filters: {FILTERS}")
    logger.info(f"Matching files: {len(targets)}")
    logger.info(f"Already done:   {already}")
    logger.info(f"Remaining:      {len(todo)} (sequential)")
    logger.info(f"Keep files:     {args.keep}")

    work_dir = args.workdir
    work_dir.mkdir(parents=True, exist_ok=True)

    for i, (study_path, is_paired, csv_filename, metadata) in enumerate(todo, 1):
        try:
            gz_b, csv_b, pq_b = process_one(
                study_path,
                is_paired,
                csv_filename,
                metadata,
                work_dir,
                keep=args.keep,
            )
            progress[csv_filename] = {
                "ok": True,
                "csv_filename": csv_filename,
                "study_path": study_path,
                "chain": str(metadata.get("Chain", "")),
                "csv_gz_bytes": gz_b,
                "csv_bytes": csv_b,
                "parquet_bytes": pq_b,
            }
            logger.info(
                f"[{i}/{len(todo)}] {csv_filename}: "
                f"csv.gz={bytes_to_mb(gz_b):.1f} MB, "
                f"csv={bytes_to_mb(csv_b):.1f} MB, "
                f"parquet={bytes_to_mb(pq_b):.1f} MB"
            )
        except Exception as e:
            progress[csv_filename] = {
                "ok": False,
                "csv_filename": csv_filename,
                "study_path": study_path,
                "chain": str(metadata.get("Chain", "")),
                "error": str(e),
            }
            logger.error(f"[{i}/{len(todo)}] FAILED {csv_filename}: {e}")

        save_progress(args.out, progress)

    save_progress(args.out, progress)

    if not args.keep:
        shutil.rmtree(work_dir, ignore_errors=True)
    else:
        logger.info(f"Kept files under: {work_dir}")

    ok_entries = {k: v for k, v in progress.items() if is_done(v)}
    failed = sum(1 for v in progress.values() if not is_done(v))
    totals = summarize_ok(ok_entries)

    logger.info("")
    logger.info("=" * 60)
    logger.info("TOTALS (SI: GB = 10^9 bytes, MB = 10^6 bytes)")
    logger.info("=" * 60)
    logger.info(f"Files OK:     {len(ok_entries)}")
    logger.info(f"Files failed: {failed}")

    def log_group(label: str, block: dict) -> None:
        n = block["n_files"]
        logger.info(f"{label}")
        logger.info(
            f"  {'csv.gz':<12} {n:>8} files  "
            f"{block['csv_gz_gb']:>10.2f} GB  ({block['csv_gz_mb']:.1f} MB)"
        )
        logger.info(
            f"  {'csv':<12} {n:>8} files  "
            f"{block['csv_gb']:>10.2f} GB  ({block['csv_mb']:.1f} MB)"
        )
        logger.info(
            f"  {'parquet':<12} {n:>8} files  "
            f"{block['parquet_gb']:>10.2f} GB  ({block['parquet_mb']:.1f} MB)"
        )

    for key, title in (
        ("all", "All"),
        ("paired", "Paired"),
        ("heavy", "Heavy"),
        ("light", "Light"),
        ("unknown", "Unknown"),
    ):
        if key in totals:
            log_group(title, totals[key])

    logger.info(f"Progress: {args.out}")


if __name__ == "__main__":
    main()
