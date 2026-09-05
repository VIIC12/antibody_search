"""Destructive unit tests for AntibodySearchEngine gene-family and pattern helpers.

Covers pure domain logic in:
- _extract_v_family / _extract_j_family (staticmethod)
- _parse_cdr_length_condition (instance)
- _build_gene_pattern (instance)

Uses Equivalence Partitioning, Boundary Value Analysis, and Error Guessing.
"""

import pytest
import pandas as pd
import tempfile
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from search_engine import AntibodySearchEngine


def _write_chain_data(data_dir: Path, chain: str, filename: str, mock_data: pd.DataFrame) -> None:
    """Write mock sequence data plus a matching metadata.parquet.

    Two production requirements this mirrors (src/search_engine.py
    AntibodySearchEngine._register_data / scripts/convert_to_parquet.py),
    both silent-empty-result traps if skipped:

    1. Every registered directory needs a metadata.parquet (a
       FileNotFoundError otherwise); self.total_sequences is the SUM of its
       total_sequences column, independent of the sequence data itself.
    2. The sequence file must live under a `Heavy/`, `Light/`, or `Paired/`
       directory, and metadata's file_path must equal "<Chain>/<filename>":
       the antibodies/metadata join extracts that segment from the parquet
       file's own path via regexp_replace, and _search_unpaired filters on
       `chain = '<chain_type>'` whenever a 'chain' column is present -- a
       missing subdirectory or mismatched chain value makes that join (and
       so every 'chain' value) NULL, which zeroes out every search result
       without raising.
    """
    chain_dir = data_dir / chain
    chain_dir.mkdir(parents=True, exist_ok=True)
    mock_data.to_parquet(chain_dir / filename, index=False)

    metadata = pd.DataFrame({
        'filename': [filename],
        'file_path': [f"{chain}/{filename}"],
        'subject': [mock_data['subject'].iloc[0]],
        'isotype': [mock_data['isotype'].iloc[0]],
        'chain': [chain],
        'rows': [len(mock_data)],
        'total_sequences': [len(mock_data)],
    })
    metadata.to_parquet(data_dir / "metadata.parquet", index=False)


# -------------------------------------------------------------------
# FIXTURES
# -------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    """Lightweight AntibodySearchEngine over trivial mock heavy-chain data.

    Instance methods under test (_parse_cdr_length_condition, _build_gene_pattern)
    read no instance state, but still require a constructed engine.
    """
    temp_dir = tempfile.mkdtemp()
    data_dir = Path(temp_dir) / "data" / "parquet"
    data_dir.mkdir(parents=True)

    mock_data = pd.DataFrame({
        'subject': ['S1'],
        'isotype': ['IgG'],
        'v_call': ['IGHV3-23*01'],
        'd_call': ['IGHD2-2*01'],
        'j_call': ['IGHJ4*01'],
        'cdr1_aa': ['ARSSS'],
        'cdr2_aa': ['ISSGG'],
        'cdr3_aa': ['CARGGY'],
        'cdr1_length': [5],
        'cdr2_length': [5],
        'cdr3_length': [6],
        'sequence_id': ['seq1'],
    })
    _write_chain_data(data_dir, "Heavy", "test_data.parquet", mock_data)

    eng = AntibodySearchEngine(data_dir=str(data_dir), verbose=False)
    yield eng
    shutil.rmtree(temp_dir)


# -------------------------------------------------------------------
# _extract_v_family / _extract_j_family
# -------------------------------------------------------------------

@pytest.mark.parametrize(
    "gene_name, expected",
    [
        ("IGHV3-30*01", "IGHV3"),
        ("IGHV3-30*02", "IGHV3"),
        ("IGHV3-30", "IGHV3"),
        ("IGHV1/OR15*01", "IGHV1"),
        ("IGKV1-39*01", "IGKV1"),
        ("IGLV2-14*01", "IGLV2"),
        ("ighv3-30*01", "IGHV3"),
        ("  IGHV3-30*01  ", "IGHV3"),
        ("IGHV3", "IGHV3"),
        (None, None),
        ("", None),
        ("TRBV1-1", None),
    ],
    ids=[
        "standard_allele",
        "allele_star02",
        "no_allele_suffix",
        "or_gene_suffix",
        "kappa_v",
        "lambda_v",
        "lowercase",
        "whitespace",
        "bare_family_no_dash",
        "none_input",
        "empty_string",
        "non_ig_trbv",
    ],
)
def test_extract_v_family_valid_and_edge_inputs_returns_expected(gene_name, expected):
    # Arrange
    # (Inputs via parametrization)

    # Act
    result = AntibodySearchEngine._extract_v_family(gene_name)

    # Assert
    assert result == expected


@pytest.mark.parametrize(
    "gene_name, expected",
    [
        ("IGHJ4*01", "IGHJ4"),
        ("IGHJ4*02", "IGHJ4"),
        ("IGHJ4", "IGHJ4"),
        ("IGHJ1/OR15*01", "IGHJ1"),
        ("IGKJ1*01", "IGKJ1"),
        ("IGLJ2*01", "IGLJ2"),
        ("ighj4*01", "IGHJ4"),
        ("  IGHJ4*01  ", "IGHJ4"),
        ("IGHJ4", "IGHJ4"),
        (None, None),
        ("", None),
        ("TRBJ1-1", None),
    ],
    ids=[
        "standard_allele",
        "allele_star02",
        "no_allele_suffix",
        "or_style_j_unlikely_but_handled",
        "kappa_j",
        "lambda_j",
        "lowercase",
        "whitespace",
        "bare_family_no_dash",
        "none_input",
        "empty_string",
        "non_ig_trbj",
    ],
)
def test_extract_j_family_valid_and_edge_inputs_returns_expected(gene_name, expected):
    # Arrange
    # (Inputs via parametrization)

    # Act
    result = AntibodySearchEngine._extract_j_family(gene_name)

    # Assert
    assert result == expected


# -------------------------------------------------------------------
# _parse_cdr_length_condition
# -------------------------------------------------------------------

@pytest.mark.parametrize(
    "length_str, expected",
    [
        ("5", "cdr1_length = 5"),
        ("2-5", "cdr1_length >= 2 AND cdr1_length <= 5"),
        (">2", "cdr1_length > 2"),
        (">=2", "cdr1_length >= 2"),
        ("<5", "cdr1_length < 5"),
        ("<=10", "cdr1_length <= 10"),
    ],
    ids=[
        "fixed_value",
        "range",
        "gt",
        "gte",
        "lt",
        "lte",
    ],
)
def test_parse_cdr_length_condition_valid_formats_returns_sql(
    engine, length_str, expected
):
    # Arrange
    column_name = "cdr1_length"

    # Act
    result = engine._parse_cdr_length_condition(column_name, length_str)

    # Assert
    assert result == expected


@pytest.mark.parametrize(
    "length_str",
    [
        None,
        "",
        "   ",
        "abc",
        "5-",
        "-5",
        "5..10",
        "> 2",
        "5-3",
    ],
    ids=[
        "none",
        "empty",
        "whitespace_only",
        "non_numeric",
        "trailing_dash",
        "leading_dash",
        "double_dot_range",
        "space_after_operator",
        "reversed_range_rejected",
    ],
)
def test_parse_cdr_length_condition_empty_or_invalid_returns_none(engine, length_str):
    # Arrange
    column_name = "cdr1_length"

    # Act
    result = engine._parse_cdr_length_condition(column_name, length_str)

    # Assert
    assert result is None


def test_parse_cdr_length_condition_non_string_int_coerced_to_string(engine):
    # Arrange
    column_name = "cdr1_length"

    # Act / Assert
    assert engine._parse_cdr_length_condition(column_name, 5) == "cdr1_length = 5"
    # float coerces to "5.0", which is not a valid length format
    assert engine._parse_cdr_length_condition(column_name, 5.0) is None


# -------------------------------------------------------------------
# _build_gene_pattern — heavy chain
# -------------------------------------------------------------------

@pytest.mark.parametrize(
    "column, gene, expected",
    [
        ("v_call", "3", "v_call LIKE 'IGHV3-%'"),
        ("v_call", "3-", "v_call LIKE 'IGHV3-%'"),
        ("d_call", "2", "d_call LIKE 'IGHD2-%'"),
        ("j_call", "4", "j_call LIKE 'IGHJ4%'"),
        ("v_call", "3-23", "v_call LIKE 'IGHV3-23*%'"),
        ("v_call", "3-23*01", "v_call LIKE 'IGHV3-23*01%'"),
        ("v_call", "IGHV3-23", "v_call LIKE 'IGHV3-23*%'"),
        ("v_call", "  3-23  ", "v_call LIKE 'IGHV3-23*%'"),
        ("v_call", "", "v_call LIKE 'IGHV%'"),
    ],
    ids=[
        "heavy_v_bare_digit_auto_dash",
        "heavy_v_explicit_dash",
        "heavy_d_bare_digit_auto_dash",
        "heavy_j_bare_digit_no_auto_dash",
        "heavy_v_gene_level",
        "heavy_v_allele_level",
        "heavy_v_redundant_prefix_stripped",
        "whitespace_stripped",
        "empty_gene_fallback",
    ],
)
def test_build_gene_pattern_heavy_inputs_returns_exact_sql(
    engine, column, gene, expected
):
    # Arrange
    # (Inputs via parametrization)

    # Act
    result = engine._build_gene_pattern(column, gene)

    # Assert
    assert result == expected


def test_build_gene_pattern_heavy_j_vs_v_auto_dash_asymmetry(engine):
    # Arrange
    v_gene = "3"
    j_gene = "4"

    # Act
    v_result = engine._build_gene_pattern("v_call", v_gene)
    j_result = engine._build_gene_pattern("j_call", j_gene)

    # Assert
    assert v_result == "v_call LIKE 'IGHV3-%'"
    assert j_result == "j_call LIKE 'IGHJ4%'"
    assert "IGHJ4-%" not in j_result


# -------------------------------------------------------------------
# _build_gene_pattern — light chain
# -------------------------------------------------------------------

@pytest.mark.parametrize(
    "column, gene, force_light_chain",
    [
        ("v_call_light", "2", False),
        ("v_call", "2", True),
    ],
    ids=["column_light_suffix", "force_light_chain_flag"],
)
def test_build_gene_pattern_light_both_chains_contains_iglv_and_igkv(
    engine, column, gene, force_light_chain
):
    # Arrange
    # (Inputs via parametrization)

    # Act
    result = engine._build_gene_pattern(column, gene, force_light_chain=force_light_chain)

    # Assert
    # Exact equality avoided: OR-clause operand order is an implementation detail.
    assert f"{column} LIKE 'IGLV2-%'" in result
    assert f"{column} LIKE 'IGKV2-%'" in result
    assert result.startswith("(") and result.endswith(")")


@pytest.mark.parametrize(
    "column, gene, force_light_chain, expected",
    [
        ("v_call_light", "L2", False, "v_call_light LIKE 'IGLV2-%'"),
        ("v_call", "L2", True, "v_call LIKE 'IGLV2-%'"),
        ("v_call_light", "IGLV2", False, "v_call_light LIKE 'IGLV2-%'"),
        ("v_call", "IGLV2", True, "v_call LIKE 'IGLV2-%'"),
    ],
    ids=["L2_via_suffix", "L2_via_force", "IGLV2_via_suffix", "IGLV2_via_force"],
)
def test_build_gene_pattern_light_lambda_only_returns_iglv(
    engine, column, gene, force_light_chain, expected
):
    # Arrange
    # (Inputs via parametrization)

    # Act
    result = engine._build_gene_pattern(column, gene, force_light_chain=force_light_chain)

    # Assert
    assert result == expected
    assert "IGKV" not in result


@pytest.mark.parametrize(
    "column, gene, force_light_chain, expected",
    [
        ("v_call_light", "K2", False, "v_call_light LIKE 'IGKV2-%'"),
        ("v_call", "K2", True, "v_call LIKE 'IGKV2-%'"),
        ("v_call_light", "IGKV2", False, "v_call_light LIKE 'IGKV2-%'"),
        ("v_call", "IGKV2", True, "v_call LIKE 'IGKV2-%'"),
    ],
    ids=["K2_via_suffix", "K2_via_force", "IGKV2_via_suffix", "IGKV2_via_force"],
)
def test_build_gene_pattern_light_kappa_only_returns_igkv(
    engine, column, gene, force_light_chain, expected
):
    # Arrange
    # (Inputs via parametrization)

    # Act
    result = engine._build_gene_pattern(column, gene, force_light_chain=force_light_chain)

    # Assert
    assert result == expected
    assert "IGLV" not in result


def test_build_gene_pattern_light_explicit_prefix_equals_lk_shorthand(engine):
    # Arrange
    # (Compare IGLV2/IGKV2 forms to L2/K2 shorthand)

    # Act
    lambda_shorthand = engine._build_gene_pattern("v_call_light", "L2")
    lambda_explicit = engine._build_gene_pattern("v_call_light", "IGLV2")
    kappa_shorthand = engine._build_gene_pattern("v_call_light", "K2")
    kappa_explicit = engine._build_gene_pattern("v_call_light", "IGKV2")

    # Assert
    assert lambda_shorthand == lambda_explicit
    assert kappa_shorthand == kappa_explicit


@pytest.mark.parametrize(
    "column, gene, force_light_chain, expected",
    [
        (
            "j_call_light",
            "J1",
            False,
            "(j_call_light LIKE 'IGLJ1%' OR j_call_light LIKE 'IGKJ1%')",
        ),
        (
            "j_call",
            "J1",
            True,
            "(j_call LIKE 'IGLJ1%' OR j_call LIKE 'IGKJ1%')",
        ),
        ("j_call_light", "LJ1", False, "j_call_light LIKE 'IGLJ1%'"),
        ("j_call_light", "KJ1", False, "j_call_light LIKE 'IGKJ1%'"),
        ("j_call_light", "IGLJ1", False, "j_call_light LIKE 'IGLJ1%'"),
        ("j_call_light", "IGKJ1", False, "j_call_light LIKE 'IGKJ1%'"),
    ],
    ids=[
        "j1_both_via_suffix",
        "j1_both_via_force",
        "lambda_j_shorthand",
        "kappa_j_shorthand",
        "lambda_j_explicit",
        "kappa_j_explicit",
    ],
)
def test_build_gene_pattern_light_j_no_auto_dash_returns_exact(
    engine, column, gene, force_light_chain, expected
):
    # Arrange
    # (Inputs via parametrization)

    # Act
    result = engine._build_gene_pattern(column, gene, force_light_chain=force_light_chain)

    # Assert
    assert result == expected
    assert "IGLJ1-%" not in result
    assert "IGKJ1-%" not in result


@pytest.mark.parametrize(
    "column, gene, force_light_chain, lambda_like, kappa_like",
    [
        (
            "d_call_light",
            "2",
            False,
            "d_call_light LIKE 'IGLD2-%'",
            "d_call_light LIKE 'IGKD2-%'",
        ),
        (
            "d_call",
            "2",
            True,
            "d_call LIKE 'IGLD2-%'",
            "d_call LIKE 'IGKD2-%'",
        ),
        (
            "d_call_light",
            "2-2",
            False,
            "d_call_light LIKE 'IGLD2-2*%'",
            "d_call_light LIKE 'IGKD2-2*%'",
        ),
    ],
    ids=["d_family_via_suffix", "d_family_via_force", "d_gene_level"],
)
def test_build_gene_pattern_light_both_chains_contains_igld_and_igkd(
    engine, column, gene, force_light_chain, lambda_like, kappa_like
):
    # Arrange
    # (Inputs via parametrization)

    # Act
    result = engine._build_gene_pattern(column, gene, force_light_chain=force_light_chain)

    # Assert
    # Exact equality avoided: OR-clause operand order is an implementation detail.
    assert lambda_like in result
    assert kappa_like in result
    assert result.startswith("(") and result.endswith(")")


@pytest.mark.parametrize(
    "column, gene, force_light_chain, expected",
    [
        ("d_call_light", "L2", False, "d_call_light LIKE 'IGLD2-%'"),
        ("d_call", "L2", True, "d_call LIKE 'IGLD2-%'"),
        ("d_call_light", "IGLD2", False, "d_call_light LIKE 'IGLD2-%'"),
        ("d_call", "IGLD2", True, "d_call LIKE 'IGLD2-%'"),
    ],
    ids=["L2_via_suffix", "L2_via_force", "IGLD2_via_suffix", "IGLD2_via_force"],
)
def test_build_gene_pattern_light_lambda_only_returns_igld(
    engine, column, gene, force_light_chain, expected
):
    # Arrange
    # (Inputs via parametrization)

    # Act
    result = engine._build_gene_pattern(column, gene, force_light_chain=force_light_chain)

    # Assert
    assert result == expected
    assert "IGKD" not in result


@pytest.mark.parametrize(
    "column, gene, force_light_chain, expected",
    [
        ("d_call_light", "K2", False, "d_call_light LIKE 'IGKD2-%'"),
        ("d_call", "K2", True, "d_call LIKE 'IGKD2-%'"),
        ("d_call_light", "IGKD2", False, "d_call_light LIKE 'IGKD2-%'"),
        ("d_call", "IGKD2", True, "d_call LIKE 'IGKD2-%'"),
    ],
    ids=["K2_via_suffix", "K2_via_force", "IGKD2_via_suffix", "IGKD2_via_force"],
)
def test_build_gene_pattern_light_kappa_only_returns_igkd(
    engine, column, gene, force_light_chain, expected
):
    # Arrange
    # (Inputs via parametrization)

    # Act
    result = engine._build_gene_pattern(column, gene, force_light_chain=force_light_chain)

    # Assert
    assert result == expected
    assert "IGLD" not in result
