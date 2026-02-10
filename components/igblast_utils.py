"""
Utilities to run IgBLAST (igblastn) and parse tabular output (outfmt 7).
Uses nucleotide sequences and nucleotide germline DBs (IG_dna). One run per chain
with -germline_db_V, -germline_db_D, -germline_db_J for integrated V(D)J assignment.
For light chain, -germline_db_D is required by igblastn even though light has no D gene;
we pass IGHD_clean. Light chain runs twice (kappa and lambda) and picks the best score.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import pandas as pd
from io import StringIO

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# IgBLAST root: use ABHUNTER_IGBLAST_PATH if set (e.g. export ABHUNTER_IGBLAST_PATH="/path/to/igblast"), else project igblast/
_igblast_path = os.getenv("ABHUNTER_IGBLAST_PATH")
IGBLAST_ROOT = Path(_igblast_path).resolve() if _igblast_path else (PROJECT_ROOT / "igblast")
IGBLAST_BIN = IGBLAST_ROOT / "bin"
IGBLAST_DB_BASE = "database/Homo_sapiens_clean/IG_dna"

DB_HEAVY_V = "IGHV_clean"
DB_HEAVY_D = "IGHD_clean"
DB_HEAVY_J = "IGHJ_clean"
DB_LIGHT_KAPPA_V = "IGKV_clean"
DB_LIGHT_LAMBDA_V = "IGLV_clean"
DB_LIGHT_KAPPA_J = "IGKJ_clean"
DB_LIGHT_LAMBDA_J = "IGLJ_clean"

VALID_NT = set("ACGT")
VALID_NT_EXTENDED = VALID_NT | {"N"}


def _get_igblast_env() -> dict:
    env = os.environ.copy()
    env["IGDATA"] = str(IGBLAST_BIN.resolve())
    return env


def is_igblast_available() -> bool:
    """Return True if the IgBLAST directory exists and bin/igblastn is present. Path can be set via ABHUNTER_IGBLAST_PATH."""
    if not IGBLAST_ROOT.is_dir():
        return False
    igblastn = IGBLAST_BIN / "igblastn"
    return igblastn.is_file() and os.access(igblastn, os.X_OK)


def normalize_nt_sequence(raw: str) -> str:
    """Strip whitespace and newlines; return single-line uppercase sequence."""
    return "".join(raw.upper().split())


def validate_nt_sequence(seq: str, allow_unknown: bool = True) -> tuple[bool, str]:
    """Check that string looks like a nucleotide sequence. Returns (is_valid, error_message)."""
    seq = normalize_nt_sequence(seq)
    if not seq:
        return False, "Sequence is empty."
    allowed = VALID_NT_EXTENDED if allow_unknown else VALID_NT
    invalid = [c for c in seq if c not in allowed]
    if invalid:
        return False, f"Invalid character(s): {', '.join(sorted(set(invalid)))}. Use A, C, G, T (and N if unknown)."
    if len(seq) < 60:
        return False, "Sequence is very short; V region is typically at least ~270 nt."
    return True, ""


# Standard genetic code (DNA) for translating CDR sequences
_CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}


def _translate_nt(nt: str) -> str:
    """Translate nucleotide sequence (upper case) to amino acids. Uses N for unknown."""
    nt = nt.upper().replace("U", "T")
    aa = []
    for i in range(0, len(nt) - 2, 3):
        codon = nt[i : i + 3]
        aa.append(_CODON_TABLE.get(codon, "X"))
    return "".join(aa)


def run_igblastn(
    query_fasta_path: str | Path,
    germline_db_V: str,
    germline_db_D: Optional[str] = None,
    germline_db_J: Optional[str] = None,
    organism: str = "human",
    num_alignments_v: int = 3,
    num_alignments_d: int = 3,
    num_alignments_j: int = 3,
    cwd: Optional[str | Path] = None,
    timeout: int = 60,
    outfmt: str = "7",
    auxiliary_data: Optional[str] = None,
) -> tuple[str, str, int]:
    """
    Run igblastn with V (and optionally D, J) germline DBs. Returns (stdout, stderr, returncode).
    cwd must be igblast root so relative DB paths (database/, optional_file/) work.
    Use auxiliary_data e.g. "optional_file/human_gl.aux" for CDR3/sub-region info; use outfmt "3" for alignment output with CDR boundaries.
    """
    if cwd is None:
        cwd = IGBLAST_ROOT
    cwd = Path(cwd).resolve()
    bin_igblastn = IGBLAST_BIN / "igblastn"
    cmd = [
        str(bin_igblastn),
        "-germline_db_V", germline_db_V,
        "-query", str(Path(query_fasta_path).resolve()),
        "-organism", organism,
        "-outfmt", outfmt,
        "-num_alignments_V", str(num_alignments_v),
    ]
    if germline_db_D is not None:
        cmd.extend(["-germline_db_D", germline_db_D, "-num_alignments_D", str(num_alignments_d)])
    if germline_db_J is not None:
        cmd.extend(["-germline_db_J", germline_db_J, "-num_alignments_J", str(num_alignments_j)])
    if auxiliary_data is not None:
        cmd.extend(["-auxiliary_data", auxiliary_data])
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=_get_igblast_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout, result.stderr, result.returncode


REARRANGEMENT_SUMMARY_PREFIX = "V-(D)-J rearrangement summary"


def _other_genes_same_score(df: Optional[pd.DataFrame], primary_gene: Optional[str]) -> list:
    """Return other genes (subject id) with the same best bit score as the top hit."""
    if df is None or df.empty or "bit score" not in df.columns:
        return []
    top_score = df.iloc[0]["bit score"]
    same = df[df["bit score"] == top_score]["subject id"].astype(str).tolist()
    return [s for s in same if s != primary_gene]


def parse_igblastn_outfmt7(stdout: str) -> tuple[dict, Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Parse igblastn -outfmt 7 output.
    Returns (summary_dict, v_hits_df, d_hits_df, j_hits_df).
    summary_dict has keys "V", "D", "J" (gene name string, or None), "chain_type", and optionally "V_identity", "D_identity", "J_identity" from first hit of each type.
    """
    summary = {"V": None, "D": None, "J": None, "chain_type": None}
    v_lines, d_lines, j_lines = [], [], []

    lines_list = stdout.split("\n")
    for i, line in enumerate(lines_list):
        if REARRANGEMENT_SUMMARY_PREFIX in line:
            for next_line in lines_list[i + 1:]:
                next_line = next_line.strip()
                if not next_line or next_line.startswith("#"):
                    continue
                parts = next_line.split("\t")
                if len(parts) >= 2 and (parts[0].startswith("IGH") or parts[0].startswith("IGK") or parts[0].startswith("IGL")):
                    summary["V"] = parts[0].strip() or None
                    p1 = (parts[1].strip().split(",")[0].strip() or "") if len(parts) > 1 else ""
                    p2 = (parts[2].strip().split(",")[0].strip() or "") if len(parts) > 2 else ""
                    # Light chain: no D gene; summary is V, J, chain_type so parts[1]=J, parts[2]=VL/VK
                    # Heavy chain: summary is V, D, J so parts[1]=D, parts[2]=J
                    if p1 and (p1.startswith("IGHJ") or p1.startswith("IGKJ") or p1.startswith("IGLJ")):
                        summary["D"] = None
                        summary["J"] = p1 or None
                        summary["chain_type"] = p2 if p2 and not p2.startswith("IGH") else None
                    else:
                        summary["D"] = p1 or None
                        summary["J"] = p2 or None
                        if len(parts) >= 4:
                            summary["chain_type"] = parts[3].strip() or None
                    break
            break

    # Parse hit table: "# N hits found" then lines "V\tquery\tsubject\t% identity\t..."
    header = "chain type\tquery id\tsubject id\t% identity\talignment length\tmismatches\tgap opens\tgaps\tq.start\tq.end\ts.start\ts.end\tevalue\tbit score"
    blocks = [x.strip() for x in stdout.split("#")]
    for block in blocks:
        if "hits found" not in block:
            continue
        lines = block.split("\n")
        data_start = None
        for j, ln in enumerate(lines):
            if "hits found" in ln:
                data_start = j + 1
                break
        if data_start is None:
            continue
        for ln in lines[data_start:]:
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split("\t")
            if len(parts) < 4:
                continue
            seg_type = parts[0].strip()
            if seg_type == "V":
                v_lines.append(ln)
            elif seg_type == "D":
                d_lines.append(ln)
            elif seg_type == "J":
                j_lines.append(ln)

    def _to_df(lines: list[str]) -> Optional[pd.DataFrame]:
        if not lines:
            return None
        data = StringIO(header + "\n" + "\n".join(lines))
        try:
            return pd.read_csv(data, sep="\t")
        except Exception:
            return None

    v_df = _to_df(v_lines)
    d_df = _to_df(d_lines)
    j_df = _to_df(j_lines)

    if v_df is not None and not v_df.empty:
        summary["V_identity"] = float(v_df.iloc[0]["% identity"])
    if d_df is not None and not d_df.empty:
        summary["D_identity"] = float(d_df.iloc[0]["% identity"])
    if j_df is not None and not j_df.empty:
        summary["J_identity"] = float(j_df.iloc[0]["% identity"])

    return summary, v_df, d_df, j_df


AUXILIARY_DATA_PATH = "optional_file/human_gl.aux"


def parse_igblastn_outfmt3_cdr(stdout: str, query_nt: str) -> dict:
    """
    Parse igblastn -outfmt 3 output (with -auxiliary_data) to extract CDR1, CDR2, CDR3.
    query_nt: full query nucleotide sequence (no spaces, uppercase).
    Returns {"CDR1": {nt, aa, start, end}, "CDR2": {...}, "CDR3": {...}}. Missing CDRs are omitted.
    Positions are 1-based inclusive (IMGT).
    """
    query_nt = normalize_nt_sequence(query_nt)
    cdrs: dict = {}

    # Alignment summary: "CDR1-IMGT	76	99	24	..." (from, to are 1-based)
    in_summary = False
    for line in stdout.split("\n"):
        line = line.strip()
        if "Alignment summary between query and top germline" in line:
            in_summary = True
            continue
        if in_summary:
            if not line or line.startswith("Alignments") or line.startswith("Total"):
                in_summary = False
                continue
            parts = line.split("\t")
            if len(parts) >= 3 and "CDR1-IMGT" in line:
                try:
                    start, end = int(parts[1]), int(parts[2])
                    nt = query_nt[start - 1 : end]
                    cdrs["CDR1"] = {"nt": nt, "aa": _translate_nt(nt), "start": start, "end": end}
                except (ValueError, IndexError):
                    pass
            elif len(parts) >= 3 and "CDR2-IMGT" in line:
                try:
                    start, end = int(parts[1]), int(parts[2])
                    nt = query_nt[start - 1 : end]
                    cdrs["CDR2"] = {"nt": nt, "aa": _translate_nt(nt), "start": start, "end": end}
                except (ValueError, IndexError):
                    pass

    # Sub-region sequence details: "CDR3	GCGGCC...	AALVIVAAGDDFDL	289	330"
    in_subregion = False
    for line in stdout.split("\n"):
        line = line.strip()
        if "Sub-region sequence details" in line:
            in_subregion = True
            continue
        if in_subregion:
            if not line:
                break
            parts = line.split("\t")
            if len(parts) >= 5 and parts[0].strip() == "CDR3":
                try:
                    nt = parts[1].strip()
                    aa = parts[2].strip()
                    start, end = int(parts[3]), int(parts[4])
                    cdrs["CDR3"] = {"nt": nt, "aa": aa, "start": start, "end": end}
                except (ValueError, IndexError):
                    pass
                break

    return cdrs


def run_heavy_chain_vdj(
    nt_sequence: str,
    organism: str = "human",
) -> tuple[dict, str]:
    """
    Run igblastn for heavy chain with V, D, J DBs in one run. Returns (result_dict, error_message).
    result_dict has "V", "D", "J" each {"gene": str, "identity": float|None, "df": Optional[DataFrame]}.
    """
    valid, err = validate_nt_sequence(nt_sequence)
    if not valid:
        return {"V": None, "D": None, "J": None}, err

    seq = normalize_nt_sequence(nt_sequence)
    db_v = f"{IGBLAST_DB_BASE}/{DB_HEAVY_V}"
    db_d = f"{IGBLAST_DB_BASE}/{DB_HEAVY_D}"
    db_j = f"{IGBLAST_DB_BASE}/{DB_HEAVY_J}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".fasta", delete=False) as f:
        f.write(">heavy\n")
        f.write(seq + "\n")
        tmp_path = f.name

    try:
        stdout, stderr, ret = run_igblastn(
            tmp_path, db_v, germline_db_D=db_d, germline_db_J=db_j,
            organism=organism, cwd=IGBLAST_ROOT,
        )
        if ret != 0:
            return {"V": None, "D": None, "J": None}, f"IgBLAST failed (exit {ret}). stderr: {stderr[:500] if stderr else 'none'}"
        summary, v_df, d_df, j_df = parse_igblastn_outfmt7(stdout)
        out = {
            "V": {"gene": summary.get("V"), "identity": summary.get("V_identity"), "df": v_df, "ties": _other_genes_same_score(v_df, summary.get("V"))},
            "D": {"gene": summary.get("D"), "identity": summary.get("D_identity"), "df": d_df, "ties": _other_genes_same_score(d_df, summary.get("D"))},
            "J": {"gene": summary.get("J"), "identity": summary.get("J_identity"), "df": j_df, "ties": _other_genes_same_score(j_df, summary.get("J"))},
        }
        # CDR1/2/3 from outfmt 3 + auxiliary_data
        stdout3, stderr3, ret3 = run_igblastn(
            tmp_path, db_v, germline_db_D=db_d, germline_db_J=db_j,
            organism=organism, cwd=IGBLAST_ROOT,
            outfmt="3", auxiliary_data=AUXILIARY_DATA_PATH,
        )
        if ret3 == 0:
            out["cdr"] = parse_igblastn_outfmt3_cdr(stdout3, seq)
        else:
            out["cdr"] = {}
        return out, ""
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def run_light_chain_vj(
    nt_sequence: str,
    organism: str = "human",
) -> tuple[dict, str]:
    """
    Run igblastn for light chain: run kappa (IGKV+IGKJ) and lambda (IGLV+IGLJ), pick better.
    IgBLAST requires -germline_db_D to be set even for light chain (no D gene); we pass IGHD_clean.
    Returns (result_dict, error_message). result_dict has "V", "J", "chain_type" (kappa|lambda).
    """
    valid, err = validate_nt_sequence(nt_sequence)
    if not valid:
        return {"V": None, "J": None, "chain_type": None}, err

    seq = normalize_nt_sequence(nt_sequence)
    db_kv = f"{IGBLAST_DB_BASE}/{DB_LIGHT_KAPPA_V}"
    db_kj = f"{IGBLAST_DB_BASE}/{DB_LIGHT_KAPPA_J}"
    db_lv = f"{IGBLAST_DB_BASE}/{DB_LIGHT_LAMBDA_V}"
    db_lj = f"{IGBLAST_DB_BASE}/{DB_LIGHT_LAMBDA_J}"
    # IgBLAST requires a D database even for light chain (no D gene in light); use IGHD_clean
    db_d = f"{IGBLAST_DB_BASE}/{DB_HEAVY_D}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".fasta", delete=False) as f:
        f.write(">light\n")
        f.write(seq + "\n")
        tmp_path = f.name

    try:
        results = []
        for (db_v, db_j, chain_type) in [(db_kv, db_kj, "kappa"), (db_lv, db_lj, "lambda")]:
            stdout, stderr, ret = run_igblastn(
                tmp_path, db_v, germline_db_D=db_d, germline_db_J=db_j,
                organism=organism, cwd=IGBLAST_ROOT,
            )
            if ret != 0:
                continue
            summary, v_df, _, j_df = parse_igblastn_outfmt7(stdout)
            v_gene = summary.get("V")
            j_gene = summary.get("J")
            v_id = summary.get("V_identity")
            j_id = summary.get("J_identity")
            if v_gene or j_gene:
                results.append((chain_type, v_gene, j_gene, v_id, j_id, v_df, j_df))

        if not results:
            return {"V": None, "J": None, "chain_type": None}, "No germline hit for kappa or lambda."

        # Pick by best V identity (or J if V tied)
        def score(r):
            vt = r[3] if r[3] is not None else -1
            jt = r[4] if r[4] is not None else -1
            return (vt, jt)
        results.sort(key=score, reverse=True)
        chain_type, v_gene, j_gene, v_id, j_id, v_df, j_df = results[0]
        db_v_win = db_kv if chain_type == "kappa" else db_lv
        db_j_win = db_kj if chain_type == "kappa" else db_lj
        out = {
            "V": {"gene": v_gene, "identity": v_id, "df": v_df, "ties": _other_genes_same_score(v_df, v_gene)},
            "J": {"gene": j_gene, "identity": j_id, "df": j_df, "ties": _other_genes_same_score(j_df, j_gene)},
            "chain_type": chain_type,
        }
        # CDR1/2/3 from outfmt 3 + auxiliary_data for winning chain (pass D db for compatibility)
        stdout3, stderr3, ret3 = run_igblastn(
            tmp_path, db_v_win, germline_db_D=db_d, germline_db_J=db_j_win,
            organism=organism, cwd=IGBLAST_ROOT,
            outfmt="3", auxiliary_data=AUXILIARY_DATA_PATH,
        )
        if ret3 == 0:
            out["cdr"] = parse_igblastn_outfmt3_cdr(stdout3, seq)
        else:
            out["cdr"] = {}
        return out, ""
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
