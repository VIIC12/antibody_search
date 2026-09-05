"""
Search form components for antibody database search.

This module provides reusable form components for Heavy and Light chain searches,
eliminating code duplication and improving maintainability.
"""

import re
import streamlit as st
from typing import Dict, Any, List, Tuple, Optional

from components.search.styling import icon_heading

# Allowed gene family / number ranges (human)
# Heavy: IGHV1-8, IGHD1-7, IGHJ1-6
# Light V: IGLV1-11 (Lambda), IGKV1-7 (Kappa)
# Light J: IGLJ1-7 (Lambda), IGKJ1-5 (Kappa)
HEAVY_V_RANGE = (1, 8)
HEAVY_D_RANGE = (1, 7)
HEAVY_J_RANGE = (1, 6)
LIGHT_V_LAMBDA_RANGE = (1, 11)   # IGLV1-11
LIGHT_V_KAPPA_RANGE = (1, 7)     # IGKV1-7
LIGHT_J_LAMBDA_RANGE = (1, 7)    # IGLJ1-7
LIGHT_J_KAPPA_RANGE = (1, 5)     # IGKJ1-5

# Genes not present in OAS dataset (valid in general but rejected for this search)
HEAVY_V_OAS_DISALLOWED = {8}                           # IGHV8
LIGHT_V_LAMBDA_OAS_DISALLOWED_UNPAIRED = {11}           # IGLV11
LIGHT_V_LAMBDA_OAS_DISALLOWED_PAIRED = {1, 11}          # IGLV1, IGLV11
LIGHT_J_LAMBDA_OAS_DISALLOWED = {4, 5}                  # IGLJ4, IGLJ5

# Help text and placeholder, examples and error text
# Heavy (VDJ)
GEN_VD_PLACEHOLDER = "e.g., 1 or 1-* or 3-5 or 1-3,4,5"
GEN_VD_HELP_TEXT = "Single: 3 or 3-23 | Multiple: 3,4-* or 3-20,3-22"
GEN_J_PLACEHOLDER = "e.g., 4 or 4,5"
GEN_J_HELP_TEXT = "Single: 4 | Multiple: 4,5"
GEN_ERROR_TEXT = "Invalid character(s)! Allowed are: 0123456789 - , and *"

# Light (VJ)
GEN_LKV_PLACEHOLDER = "e.g., 1 or L1-2,K2"
GEN_LKV_HELP_TEXT = "Single: L4 | Multiple: 4,K5 | Define Lambda or Kappa with L or K prefix. | IGLV 1-11 (Lambda), IGKV 1-7 (Kappa)"
GEN_LKJ_PLACEHOLDER = "e.g., 2 or L2,K4"
GEN_LKJ_HELP_TEXT = "Single: L4 | Multiple: 4,K5 | Define Lambda or Kappa with L or K prefix. | IGLJ 1-7 (Lambda), IGKJ 1-5 (Kappa)"
GEN_LKVJ_ERROR_TEXT = "Invalid character(s)! Allowed are: 0123456789 - , * L and K"

# CDR length
CDR_LENGTH_PLACEHOLDER = "e.g., 2 or 2-5 or >2 or <=2"
CDR_LENGTH_HELP_TEXT = "Fixed: 2 | Range: 2-5 | Comparison: >2, <5, >=2, <=10"

# Motif
MOTIF_PLACEHOLDER = "e.g., *TT or YY.D.*G or YY.{2-6}G or [GYW]TT or .{6}*[FI]W.{2}*"
MOTIF_HELP_TEXT = ". for one character, \* for 0-many, {n} for exactly n chars, {n-m} for n to m chars, .{n}* for at least n chars, [ACD] for explicit alternatives (e.g., [GYW] matches G, Y, or W). Valid amino acids: ACDEFGHIKLMNPQRSTVWY"
MOTIF_ERROR_TEXT = "Invalid character(s)! Allowed are ACDEFGHIKLMNPQRSTVWY and placeholders, see help text for details."
SIMILARITY_HELP_NO_MOTIF = "Restrict mismatched positions to chemically similar amino acids (requires motif input)."
SIMILARITY_HELP_TEXT = (
    "When on, mismatched positions may only be chemically similar amino acids: "
    "A/I/L/V (Aliphatic), D/E (Acidic), F/W/Y (Aromatic), K/R (Basic), N/Q (Amide), S/T (Hydroxyl). "
    "Unique residues C, G, H, M, P have no substitutes. Requires Mismatches > 0."
)
MISMATCH_HELP_TEXT = (
    "How many defined motif positions may differ. "
    "Without Similarity Search those positions can be any amino acid; "
    "with Similarity Search they must be chemically similar. "
    "Wildcards (. and *) are not counted."
)


def _count_defined_motif_positions(motif: str) -> int:
    """Count amino-acid / [class] positions that can take a mismatch."""
    if not motif:
        return 0
    count = 0
    i = 0
    while i < len(motif):
        char = motif[i]
        if char == '[':
            end = motif.find(']', i + 1)
            if end != -1:
                count += 1
                i = end + 1
                continue
        elif char in '*.':
            if i + 1 < len(motif) and motif[i + 1] == '{':
                end = motif.find('}', i + 1)
                i = end + 1 if end != -1 else i + 1
                continue
            i += 1
            continue
        elif char == '{':
            end = motif.find('}', i + 1)
            i = end + 1 if end != -1 else i + 1
            continue
        elif char.upper() in 'ACDEFGHIKLMNPQRSTVWY':
            count += 1
        i += 1
    return count


def _render_motif_match_controls(
    motif: str,
    similarity_key: str,
    mismatches_key: str,
    disabled: bool
) -> Tuple[bool, int]:
    """Render Similarity Search toggle and always-available Mismatches input."""
    col_toggle, col_mismatch = st.columns([2, 1])
    with col_toggle:
        if not motif and st.session_state.get(similarity_key, False):
            st.session_state[similarity_key] = False
        # No `value=` here either -- same Session State API conflict as the
        # Mismatches input below: this key can already be set in
        # st.session_state (line above, an example search, or a mask reset)
        # before this widget is created. st.toggle already defaults to False
        # with no `value=` passed, so dropping it changes nothing when no
        # prior session_state entry exists.
        similarity = st.toggle(
            "Similarity Search",
            disabled=disabled or not bool(motif),
            help=SIMILARITY_HELP_NO_MOTIF if not motif else SIMILARITY_HELP_TEXT,
            key=similarity_key
        )
    with col_mismatch:
        mismatches = 0
        if motif:
            max_mismatches = _count_defined_motif_positions(motif)
            if max_mismatches > 0:
                current = st.session_state.get(mismatches_key, 0)
                try:
                    current = int(current or 0)
                except (TypeError, ValueError):
                    current = 0
                if current > max_mismatches:
                    st.session_state[mismatches_key] = max_mismatches
                # No `value=` here: the widget's key may already carry a value
                # in st.session_state (set above on clamp, or by an example
                # search / mask reset before this widget is created). Passing
                # `value=` alongside a pre-set session_state key makes
                # Streamlit warn that the default conflicts with the Session
                # State API, even when the two agree. Without `value=`,
                # Streamlit falls back to session_state if present, else to
                # `min_value` (0 here) -- same default, no warning.
                mismatches = st.number_input(
                    "Mismatches",
                    min_value=0,
                    max_value=max_mismatches,
                    step=1,
                    help=f"{MISMATCH_HELP_TEXT} Max: {max_mismatches}.",
                    key=mismatches_key,
                    disabled=disabled
                )
    return similarity, int(mismatches or 0)

def _parse_gene_tokens(gene_str: str) -> List[int]:
    """Parse comma/pipe separated gene tokens and return the first number from each (family or gene number)."""
    if not gene_str or not gene_str.strip():
        return []
    numbers = []
    for token in re.split(r'[,\|\s]+', gene_str.strip()):
        token = token.strip()
        if not token:
            continue
        m = re.match(r'^[LlKk]?(\d+)', token)
        if m:
            numbers.append(int(m.group(1)))
    return numbers


def _parse_light_gene_tokens(gene_str: str) -> List[Tuple[Optional[str], int]]:
    """Parse light chain gene string into (prefix, number) per token. prefix is 'L', 'K', or None."""
    if not gene_str or not gene_str.strip():
        return []
    result = []
    for token in re.split(r'[,\|\s]+', gene_str.strip()):
        token = token.strip()
        if not token:
            continue
        m = re.match(r'^([LlKk])?(\d+)', token)
        if m:
            prefix = m.group(1)
            if prefix:
                prefix = prefix.upper()
            result.append((prefix, int(m.group(2))))
    return result


def validate_gene_range(gene_str: str, gene_type: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that all gene numbers in the input fall within the allowed range for that gene type.
    For light_v / light_j, L (Lambda) and K (Kappa) prefixes are checked separately:
    - light_v: L or no prefix -> IGLV 1-11, K -> IGKV 1-7
    - light_j: L or no prefix -> IGLJ 1-7, K -> IGKJ 1-5
    gene_type: 'ighv' | 'ighd' | 'ighj' | 'light_v' | 'light_j'
    Returns (is_valid, error_message).
    """
    if not gene_str or not gene_str.strip():
        return True, None
    if gene_type in ('light_v', 'light_j'):
        tokens = _parse_light_gene_tokens(gene_str)
        if not tokens:
            return True, None
        invalid: List[str] = []
        if gene_type == 'light_v':
            for prefix, n in tokens:
                if prefix == 'K':
                    lo, hi = LIGHT_V_KAPPA_RANGE
                    if n < lo or n > hi:
                        invalid.append(f"K{n} (IGKV allows 1-7 only)")
                else:
                    lo, hi = LIGHT_V_LAMBDA_RANGE
                    if n < lo or n > hi:
                        label = f"L{n}" if prefix else str(n)
                        invalid.append(f"{label} (IGLV allows 1-11 only)")
            if invalid:
                return False, "IGLV 1-11 (Lambda), IGKV 1-7 (Kappa). Invalid: " + "; ".join(invalid)
        else:  # light_j
            for prefix, n in tokens:
                if prefix == 'K':
                    lo, hi = LIGHT_J_KAPPA_RANGE
                    if n < lo or n > hi:
                        invalid.append(f"K{n} (IGKJ allows 1-5 only)")
                else:
                    lo, hi = LIGHT_J_LAMBDA_RANGE
                    if n < lo or n > hi:
                        label = f"L{n}" if prefix else str(n)
                        invalid.append(f"{label} (IGLJ allows 1-7 only)")
            if invalid:
                return False, "IGLJ 1-7 (Lambda), IGKJ 1-5 (Kappa). Invalid: " + "; ".join(invalid)
        return True, None
    # Heavy chain
    numbers = _parse_gene_tokens(gene_str)
    if not numbers:
        return True, None
    if gene_type == 'ighv':
        lo, hi = HEAVY_V_RANGE
        name = "IGHV"
    elif gene_type == 'ighd':
        lo, hi = HEAVY_D_RANGE
        name = "IGHD"
    elif gene_type == 'ighj':
        lo, hi = HEAVY_J_RANGE
        name = "IGHJ"
    else:
        return True, None
    out_of_range = [n for n in numbers if n < lo or n > hi]
    if out_of_range:
        return False, f"{name} allows {lo}-{hi}. Invalid: {', '.join(str(n) for n in sorted(set(out_of_range)))}"
    return True, None


def validate_gene_range_oas(
    gene_str: str, gene_type: str, is_paired: bool
) -> Tuple[bool, Optional[str]]:
    """
    Validate that no gene is in the OAS-disallowed list (genes not present in the OAS dataset).
    gene_type: 'ighv' | 'light_v' | 'light_j'
    is_paired: True for paired search (stricter light V: L1, L11 disallowed).
    Returns (is_valid, error_message).
    """
    if not gene_str or not gene_str.strip():
        return True, None
    if gene_type == 'ighv':
        numbers = _parse_gene_tokens(gene_str)
        disallowed = [n for n in numbers if n in HEAVY_V_OAS_DISALLOWED]
        if disallowed:
            return False, "IGHV8 is not present in the OAS dataset."
        return True, None
    if gene_type == 'light_v':
        tokens = _parse_light_gene_tokens(gene_str)
        disallowed_set = LIGHT_V_LAMBDA_OAS_DISALLOWED_PAIRED if is_paired else LIGHT_V_LAMBDA_OAS_DISALLOWED_UNPAIRED
        invalid = []
        for prefix, n in tokens:
            if prefix != 'K' and n in disallowed_set:  # Lambda or no prefix
                label = f"L{n}" if prefix else str(n)
                invalid.append(label)
        if invalid:
            msg = "IGLV1, IGLV11" if is_paired else "IGLV11"
            dataset_note = "paired dataset" if is_paired else "OAS dataset"
            return False, f"{msg} not present in the {dataset_note}. Invalid: {', '.join(invalid)}"
        return True, None
    if gene_type == 'light_j':
        tokens = _parse_light_gene_tokens(gene_str)
        invalid = []
        for prefix, n in tokens:
            # Only reject explicit Lambda: L4, L5 (K4, K5 are valid IGKJ)
            if prefix == 'L' and n in LIGHT_J_LAMBDA_OAS_DISALLOWED:
                invalid.append(f"L{n}")
        if invalid:
            return False, "IGLJ4, IGLJ5 are not present in the OAS dataset. Invalid: " + ", ".join(invalid)
        return True, None
    return True, None


def validate_gene_input(gene_str: str, field_name: str = "") -> bool:
    """
    Validate gene input - only allow numbers, dashes, commas, pipes, and asterisks.
    For light chain fields, also allow L and K prefixes (for Lambda/Kappa).
    
    Returns True if valid, False otherwise.
    """
    if not gene_str:
        return True
    
    # Check if this is a light chain field
    is_light_chain = 'light' in field_name.lower() or 'igl' in field_name.lower()
    
    if is_light_chain:
        # Allow: digits, dash, comma, pipe, asterisk, whitespace, L, K (for Lambda/Kappa prefixes)
        pattern = re.compile(r'^[0-9\-,|\*\sLlKk]+$')
    else:
        # Only allow: digits, dash, comma, pipe, asterisk, whitespace
        pattern = re.compile(r'^[0-9\-,|\*\s]+$')
    
    return pattern.match(gene_str) is not None


def validate_cdr_length_input(length_str: str) -> Tuple[bool, Optional[str]]:
    """
    Validate CDR length input - allow fixed values, ranges, and comparisons.
    
    Supported formats:
    - Fixed value: "2" or "10"
    - Range: "2-5" or "10-20"
    - Greater than: ">2" or ">=2"
    - Less than: "<5" or "<=5"
    - Combined: ">=2" and "<10" (handled separately)
    
    Args:
        length_str: Input string to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    import re
    if not length_str or not length_str.strip():
        return True, None
    
    length_str = length_str.strip()
    
    # Pattern for fixed value: just digits
    if re.match(r'^\d+$', length_str):
        return True, None
    
    # Pattern for range: digits-digits
    if re.match(r'^\d+-\d+$', length_str):
        parts = length_str.split('-')
        if len(parts) == 2:
            try:
                min_val = int(parts[0])
                max_val = int(parts[1])
                if min_val > max_val:
                    return False, "Range minimum must be less than or equal to maximum"
                return True, None
            except ValueError:
                return False, "Range values must be integers"
        return False, "Invalid range format"
    
    # Pattern for comparisons: >, >=, <, <= followed by digits
    if re.match(r'^[><]=?\d+$', length_str):
        return True, None
    
    return False, "Invalid format. Use: number (e.g., '2'), range (e.g., '2-5'), or comparison (e.g., '>2', '<5', '>=2', '<=10')"


def parse_cdr_length_condition(column_name: str, length_str: str) -> Optional[str]:
    """
    Parse CDR length string into SQL WHERE clause condition.
    
    Args:
        column_name: Name of the CDR length column (e.g., 'cdr1_length')
        length_str: Input string (e.g., "2", "2-5", ">2", "<5", ">=2", "<=10")
        
    Returns:
        SQL condition string or None if input is empty/invalid
    """
    import re
    if not length_str or not length_str.strip():
        return None
    
    length_str = length_str.strip()
    
    # Fixed value: "2" -> "cdr1_length = 2"
    if re.match(r'^\d+$', length_str):
        return f"{column_name} = {int(length_str)}"
    
    # Range: "2-5" -> "cdr1_length >= 2 AND cdr1_length <= 5"
    if re.match(r'^\d+-\d+$', length_str):
        parts = length_str.split('-')
        min_val = int(parts[0])
        max_val = int(parts[1])
        return f"{column_name} >= {min_val} AND {column_name} <= {max_val}"
    
    # Greater than: ">2" -> "cdr1_length > 2"
    if re.match(r'^>\d+$', length_str):
        val = int(length_str[1:])
        return f"{column_name} > {val}"
    
    # Greater than or equal: ">=2" -> "cdr1_length >= 2"
    if re.match(r'^>=\d+$', length_str):
        val = int(length_str[2:])
        return f"{column_name} >= {val}"
    
    # Less than: "<5" -> "cdr1_length < 5"
    if re.match(r'^<\d+$', length_str):
        val = int(length_str[1:])
        return f"{column_name} < {val}"
    
    # Less than or equal: "<=10" -> "cdr1_length <= 10"
    if re.match(r'^<=\d+$', length_str):
        val = int(length_str[2:])
        return f"{column_name} <= {val}"
    
    # If we get here, the input was invalid (should have been caught by validation)
    return None


def validate_motif_input(motif_str: str) -> bool:
    """
    Validate CDR motif input - allow valid amino acids, dots, asterisks, curly braces for ranges,
    and square brackets for explicit alternative amino acids.
    
    Returns True if valid, False otherwise.
    """
    import re
    if not motif_str:
        return True
    
    # Allow: 20 standard amino acids, dot (.), asterisk (*), curly braces {n} or {n-m},
    # and square brackets [ABC] for explicit alternatives
    # Valid amino acids: A C D E F G H I K L M N P Q R S T V W Y
    # Curly braces: {n} for exactly n chars, or {n-m} for n to m chars range (dash is required for ranges)
    # Square brackets: [ABC] where A, B, C are amino acids
    # Note: The dash (-) character is allowed in curly braces for range syntax: {n-m}
    pattern = re.compile(r'^[ACDEFGHIKLMNPQRSTVWY\.\*\s\{\}\-\[\]0-9]+$', re.IGNORECASE)
    
    if not pattern.match(motif_str):
        return False
    
    # Validate curly brace syntax: {n} or {n-m} where n,m are digits
    # Check for balanced braces and valid range syntax
    brace_pattern = re.compile(r'\{(\d+)(?:-(\d+))?\}')
    for match in brace_pattern.finditer(motif_str):
        start_pos = match.start()
        end_pos = match.end()
        # Check that braces are preceded by . or *
        if start_pos > 0:
            prev_char = motif_str[start_pos - 1]
            if prev_char not in ['.', '*']:
                return False
    
    # Validate square bracket syntax: [ABC] where A, B, C are amino acids
    # Check for balanced brackets and valid amino acids inside
    bracket_pattern = re.compile(r'\[([^\]]+)\]')
    bracket_matches = list(bracket_pattern.finditer(motif_str))
    # Check that all [ and ] are properly matched
    open_brackets = motif_str.count('[')
    close_brackets = motif_str.count(']')
    if open_brackets != close_brackets:
        return False
    for match in bracket_matches:
        content = match.group(1)
        # Content should only contain valid amino acids
        if not re.match(r'^[ACDEFGHIKLMNPQRSTVWY]+$', content, re.IGNORECASE):
            return False
    
    return True

def create_heavy_chain_form(prefix: str = "", disabled: bool = False) -> Tuple[Dict[str, Any], List[str], bool]:
    """
    Create form fields for Heavy chain search.
    
    Args:
        prefix: Prefix for field keys (e.g., "heavy_" for paired forms, "" for unpaired)
        disabled: Whether to disable all form fields
        
    Returns:
        Tuple of (params_dict, validation_errors_list, valid_bool)
    """
    validation_errors = []
    
    icon_heading("heavy", "Heavy Chain", level=4, margin_top=0.5)
    
    # Gene fields
    col1, col2, col3 = st.columns(3)
    
    v_key = f"{prefix}v_input" if prefix else "ighv_input"
    d_key = f"{prefix}d_input" if prefix else "ighd_input"
    j_key = f"{prefix}j_input" if prefix else "ighj_input"
    
    with col1:
        v_valid = True
        v = st.text_input(
            "IGHV Gene",
            placeholder=GEN_VD_PLACEHOLDER,
            help=GEN_VD_HELP_TEXT,
            key=v_key,
            disabled=disabled
        )
        if v and not validate_gene_input(v):
            st.error(GEN_ERROR_TEXT, icon=":material/error:")
            v_valid = False
            validation_errors.append(f"{'Heavy ' if prefix else ''}IGHV Gene")
        elif v:
            range_ok, range_err = validate_gene_range(v, "ighv")
            if not range_ok and range_err:
                st.error(f"{range_err}", icon=":material/error:")
                v_valid = False
                validation_errors.append(f"{'Heavy ' if prefix else ''}IGHV Gene")
    
    with col2:
        d_valid = True
        d = st.text_input(
            "IGHD Gene",
            placeholder=GEN_VD_PLACEHOLDER,
            help=GEN_VD_HELP_TEXT,
            key=d_key,
            disabled=disabled
        )
        if d and not validate_gene_input(d):
            st.error(GEN_ERROR_TEXT, icon=":material/error:")
            d_valid = False
            validation_errors.append(f"{'Heavy ' if prefix else ''}IGHD Gene")
        elif d:
            range_ok, range_err = validate_gene_range(d, "ighd")
            if not range_ok and range_err:
                st.error(f"{range_err}", icon=":material/error:")
                d_valid = False
                validation_errors.append(f"{'Heavy ' if prefix else ''}IGHD Gene")
    
    with col3:
        j_valid = True
        j = st.text_input(
            "IGHJ Gene",
            placeholder=GEN_J_PLACEHOLDER,
            help=GEN_J_HELP_TEXT,
            key=j_key,
            disabled=disabled
        )
        if j and not validate_gene_input(j):
            st.error(GEN_ERROR_TEXT, icon=":material/error:")
            j_valid = False
            validation_errors.append(f"{'Heavy ' if prefix else ''}IGHJ Gene")
        elif j:
            range_ok, range_err = validate_gene_range(j, "ighj")
            if not range_ok and range_err:
                st.error(f"{range_err}", icon=":material/error:")
                j_valid = False
                validation_errors.append(f"{'Heavy ' if prefix else ''}IGHJ Gene")
    
    # CDR Length fields
    st.markdown("<h5 style='margin-top: 0.75rem; margin-bottom: 0.25rem;'>CDR Lengths (amino acids)</h5>", unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    
    cdr1_length_key = f"{prefix}cdr1_length_input" if prefix else "cdr1_length_input"
    cdr2_length_key = f"{prefix}cdr2_length_input" if prefix else "cdr2_length_input"
    cdr3_length_key = f"{prefix}cdr3_length_input" if prefix else "cdr3_length_input"
    
    with col1:
        cdr1_length_valid = True
        cdr1_length = st.text_input(
            "CDRH1 Length",
            placeholder=CDR_LENGTH_PLACEHOLDER,
            help=CDR_LENGTH_HELP_TEXT,
            key=cdr1_length_key,
            disabled=disabled
        )
        if cdr1_length:
            is_valid, error_msg = validate_cdr_length_input(cdr1_length)
            if not is_valid:
                st.error(f"{error_msg}", icon=":material/error:")
                cdr1_length_valid = False
                validation_errors.append(f"{'Heavy ' if prefix else ''}CDRH1 Length")
            else:
                cdr1_length = cdr1_length.strip()
        else:
            cdr1_length = None
    
    with col2:
        cdr2_length_valid = True
        cdr2_length = st.text_input(
            "CDRH2 Length",
            placeholder=CDR_LENGTH_PLACEHOLDER,
            help=CDR_LENGTH_HELP_TEXT,
            key=cdr2_length_key,
            disabled=disabled
        )
        if cdr2_length:
            is_valid, error_msg = validate_cdr_length_input(cdr2_length)
            if not is_valid:
                st.error(f"{error_msg}", icon=":material/error:")
                cdr2_length_valid = False
                validation_errors.append(f"{'Heavy ' if prefix else ''}CDRH2 Length")
            else:
                cdr2_length = cdr2_length.strip()
        else:
            cdr2_length = None
    
    with col3:
        cdr3_length_valid = True
        cdr3_length = st.text_input(
            "CDRH3 Length",
            placeholder=CDR_LENGTH_PLACEHOLDER,
            help=CDR_LENGTH_HELP_TEXT,
            key=cdr3_length_key,
            disabled=disabled
        )
        if cdr3_length:
            is_valid, error_msg = validate_cdr_length_input(cdr3_length)
            if not is_valid:
                st.error(f"{error_msg}", icon=":material/error:")
                cdr3_length_valid = False
                validation_errors.append(f"{'Heavy ' if prefix else ''}CDRH3 Length")
            else:
                cdr3_length = cdr3_length.strip()
        else:
            cdr3_length = None
    
    # CDR Motif fields
    st.markdown("<h5 style='margin-top: 0.75rem; margin-bottom: 0.25rem;'>CDR Sequence Motifs</h5>", unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    # CDR1 Motif
    cdr1_motif_key = f"{prefix}cdr1_motif_input" if prefix else "cdr1_motif_input"
    cdr1_similarity_key = f"{prefix}cdr1_similarity_toggle" if prefix else "cdr1_similarity_toggle"
    cdr1_mismatches_key = f"{prefix}cdr1_mismatches_input" if prefix else "cdr1_mismatches_input"
    
    with col1:
        cdr1_motif_valid = True
        cdr1_motif = st.text_input(
            "CDRH1 Sequence Motif",
            placeholder=MOTIF_PLACEHOLDER,
            help=MOTIF_HELP_TEXT,
            key=cdr1_motif_key,
            disabled=disabled
        )
        if cdr1_motif and not validate_motif_input(cdr1_motif):
            st.error(MOTIF_ERROR_TEXT, icon=":material/error:")
            cdr1_motif_valid = False
            validation_errors.append(f"{'Heavy ' if prefix else ''}CDRH1 Motif")
        
        cdr1_similarity, cdr1_mismatches = _render_motif_match_controls(
            cdr1_motif, cdr1_similarity_key, cdr1_mismatches_key, disabled
        )
    
    # CDR2 Motif
    cdr2_motif_key = f"{prefix}cdr2_motif_input" if prefix else "cdr2_motif_input"
    cdr2_similarity_key = f"{prefix}cdr2_similarity_toggle" if prefix else "cdr2_similarity_toggle"
    cdr2_mismatches_key = f"{prefix}cdr2_mismatches_input" if prefix else "cdr2_mismatches_input"
    
    with col2:
        cdr2_motif_valid = True
        cdr2_motif = st.text_input(
            "CDRH2 Sequence Motif",
            placeholder=MOTIF_PLACEHOLDER,
            help=MOTIF_HELP_TEXT,
            key=cdr2_motif_key,
            disabled=disabled
        )
        if cdr2_motif and not validate_motif_input(cdr2_motif):
            st.error(MOTIF_ERROR_TEXT, icon=":material/error:")
            cdr2_motif_valid = False
            validation_errors.append(f"{'Heavy ' if prefix else ''}CDRH2 Motif")
        
        cdr2_similarity, cdr2_mismatches = _render_motif_match_controls(
            cdr2_motif, cdr2_similarity_key, cdr2_mismatches_key, disabled
        )
    
    # CDR3 Motif
    cdr3_motif_key = f"{prefix}cdr3_motif_input" if prefix else "cdr3_motif_input"
    cdr3_similarity_key = f"{prefix}cdr3_similarity_toggle" if prefix else "cdr3_similarity_toggle"
    cdr3_mismatches_key = f"{prefix}cdr3_mismatches_input" if prefix else "cdr3_mismatches_input"
    
    with col3:
        cdr3_motif_valid = True
        cdr3_motif = st.text_input(
            "CDRH3 Sequence Motif",
            placeholder=MOTIF_PLACEHOLDER,
            help=MOTIF_HELP_TEXT,
            key=cdr3_motif_key,
            disabled=disabled
        )
        if cdr3_motif and not validate_motif_input(cdr3_motif):
            st.error(MOTIF_ERROR_TEXT, icon=":material/error:")
            cdr3_motif_valid = False
            validation_errors.append(f"{'Heavy ' if prefix else ''}CDRH3 Motif")
        
        cdr3_similarity, cdr3_mismatches = _render_motif_match_controls(
            cdr3_motif, cdr3_similarity_key, cdr3_mismatches_key, disabled
        )

    with col4:
        st.empty()
    
    # Build parameters dict
    params = {
        f"{prefix}v" if prefix else "ighv": v,
        f"{prefix}d" if prefix else "ighd": d,
        f"{prefix}j" if prefix else "ighj": j,
        f"{prefix}cdr1_length" if prefix else "cdr1_length": cdr1_length,
        f"{prefix}cdr2_length" if prefix else "cdr2_length": cdr2_length,
        f"{prefix}cdr3_length" if prefix else "cdr3_length": cdr3_length,
        f"{prefix}cdr1_motif" if prefix else "cdr1_motif": cdr1_motif,
        f"{prefix}cdr2_motif" if prefix else "cdr2_motif": cdr2_motif,
        f"{prefix}cdr3_motif" if prefix else "cdr3_motif": cdr3_motif,
        f"{prefix}cdr1_similarity" if prefix else "cdr1_similarity": cdr1_similarity,
        f"{prefix}cdr2_similarity" if prefix else "cdr2_similarity": cdr2_similarity,
        f"{prefix}cdr3_similarity" if prefix else "cdr3_similarity": cdr3_similarity,
        f"{prefix}cdr1_mismatches" if prefix else "cdr1_mismatches": cdr1_mismatches,
        f"{prefix}cdr2_mismatches" if prefix else "cdr2_mismatches": cdr2_mismatches,
        f"{prefix}cdr3_mismatches" if prefix else "cdr3_mismatches": cdr3_mismatches,
    }
    
    valid = all([v_valid, d_valid, j_valid, cdr1_length_valid, cdr2_length_valid, cdr3_length_valid, cdr1_motif_valid, cdr2_motif_valid, cdr3_motif_valid])
    
    return params, validation_errors, valid


def create_light_chain_form(prefix: str = "light_", disabled: bool = False) -> Tuple[Dict[str, Any], List[str], bool]:
    """
    Create form fields for Light chain search.
    
    Args:
        prefix: Prefix for field keys (default: "light_")
        disabled: Whether to disable all form fields
        
    Returns:
        Tuple of (params_dict, validation_errors_list, valid_bool)
    """
    validation_errors = []
    
    icon_heading("light", "Light Chain", level=4, margin_top=0.5)
    
    # Gene fields (Light chains don't have D genes).
    # Use 3 columns like heavy (V/D/J) so V/J match heavy field width; leave the 3rd empty.
    col1, col2, col3 = st.columns(3)
    
    with col1:
        light_v_valid = True
        light_v = st.text_input(
            "IGLV/KV Gene",
            placeholder=GEN_LKV_PLACEHOLDER,
            help=GEN_LKV_HELP_TEXT,
            key=f"{prefix}v_input",
            disabled=disabled
        )
        if light_v and not validate_gene_input(light_v, "Light IGLV/KV Gene"):
            st.error(GEN_LKVJ_ERROR_TEXT, icon=":material/error:")
            light_v_valid = False
            validation_errors.append("Light IGLV/KV Gene")
        elif light_v:
            range_ok, range_err = validate_gene_range(light_v, "light_v")
            if not range_ok and range_err:
                st.error(f"{range_err}", icon=":material/error:")
                light_v_valid = False
                validation_errors.append("Light IGLV/KV Gene")
    
    with col2:
        light_j_valid = True
        light_j = st.text_input(
            "IGLJ/KJ Gene",
            placeholder=GEN_LKJ_PLACEHOLDER,
            help=GEN_LKJ_HELP_TEXT,
            key=f"{prefix}j_input",
            disabled=disabled
        )
        if light_j and not validate_gene_input(light_j, "Light IGLJ Gene"):
            st.error(GEN_LKVJ_ERROR_TEXT, icon=":material/error:")
            light_j_valid = False
            validation_errors.append("Light IGLJ Gene")
        elif light_j:
            range_ok, range_err = validate_gene_range(light_j, "light_j")
            if not range_ok and range_err:
                st.error(f"{range_err}", icon=":material/error:")
                light_j_valid = False
                validation_errors.append("Light IGLJ Gene")

    with col3:
        st.empty()
    
    # CDR Length fields
    st.markdown("<h5 style='margin-top: 0.75rem; margin-bottom: 0.25rem;'>CDR Lengths (amino acids)</h5>", unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        light_cdr1_length_valid = True
        light_cdr1_length = st.text_input(
            "CDRL1 Length",
            placeholder=CDR_LENGTH_PLACEHOLDER,
            help=CDR_LENGTH_HELP_TEXT,
            key=f"{prefix}cdr1_length_input",
            disabled=disabled
        )
        if light_cdr1_length:
            is_valid, error_msg = validate_cdr_length_input(light_cdr1_length)
            if not is_valid:
                st.error(f"{error_msg}", icon=":material/error:")
                light_cdr1_length_valid = False
                validation_errors.append("Light CDRL1 Length")
            else:
                light_cdr1_length = light_cdr1_length.strip()
        else:
            light_cdr1_length = None
    
    with col2:
        light_cdr2_length_valid = True
        light_cdr2_length = st.text_input(
            "CDRL2 Length",
            placeholder=CDR_LENGTH_PLACEHOLDER,
            help=CDR_LENGTH_HELP_TEXT,
            key=f"{prefix}cdr2_length_input",
            disabled=disabled
        )
        if light_cdr2_length:
            is_valid, error_msg = validate_cdr_length_input(light_cdr2_length)
            if not is_valid:
                st.error(f"{error_msg}", icon=":material/error:")
                light_cdr2_length_valid = False
                validation_errors.append("Light CDRL2 Length")
            else:
                light_cdr2_length = light_cdr2_length.strip()
        else:
            light_cdr2_length = None
    
    with col3:
        light_cdr3_length_valid = True
        light_cdr3_length = st.text_input(
            "CDRL3 Length",
            placeholder=CDR_LENGTH_PLACEHOLDER,
            help=CDR_LENGTH_HELP_TEXT,
            key=f"{prefix}cdr3_length_input",
            disabled=disabled
        )
        if light_cdr3_length:
            is_valid, error_msg = validate_cdr_length_input(light_cdr3_length)
            if not is_valid:
                st.error(f"{error_msg}", icon=":material/error:")
                light_cdr3_length_valid = False
                validation_errors.append("Light CDRL3 Length")
            else:
                light_cdr3_length = light_cdr3_length.strip()
        else:
            light_cdr3_length = None

    with col4:
        st.empty()
    
    # CDR Motif fields
    st.markdown("<h5 style='margin-top: 0.75rem; margin-bottom: 0.25rem;'>CDR Sequence Motifs</h5>", unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    # CDR1 Motif
    with col1:
        light_cdr1_motif_valid = True
        light_cdr1_motif = st.text_input(
            "CDRL1 Sequence Motif",
            placeholder=MOTIF_PLACEHOLDER,
            help=MOTIF_HELP_TEXT,
            key=f"{prefix}cdr1_motif_input",
            disabled=disabled
        )
        if light_cdr1_motif and not validate_motif_input(light_cdr1_motif):
            st.error(MOTIF_ERROR_TEXT, icon=":material/error:")
            light_cdr1_motif_valid = False
            validation_errors.append("Light CDRL1 Motif")
        
        light_cdr1_similarity, light_cdr1_mismatches = _render_motif_match_controls(
            light_cdr1_motif,
            f"{prefix}cdr1_similarity_toggle",
            f"{prefix}cdr1_mismatches_input",
            disabled
        )
    
    # CDR2 Motif
    with col2:
        light_cdr2_motif_valid = True
        light_cdr2_motif = st.text_input(
            "CDRL2 Sequence Motif",
            placeholder=MOTIF_PLACEHOLDER,
            help=MOTIF_HELP_TEXT,
            key=f"{prefix}cdr2_motif_input",
            disabled=disabled
        )
        if light_cdr2_motif and not validate_motif_input(light_cdr2_motif):
            st.error(MOTIF_ERROR_TEXT, icon=":material/error:")
            light_cdr2_motif_valid = False
            validation_errors.append("Light CDRL2 Motif")
        
        light_cdr2_similarity, light_cdr2_mismatches = _render_motif_match_controls(
            light_cdr2_motif,
            f"{prefix}cdr2_similarity_toggle",
            f"{prefix}cdr2_mismatches_input",
            disabled
        )
    
    # CDR3 Motif
    with col3:
        light_cdr3_motif_valid = True
        light_cdr3_motif = st.text_input(
            "CDRL3 Sequence Motif",
            placeholder=MOTIF_PLACEHOLDER,
            help=MOTIF_HELP_TEXT,
            key=f"{prefix}cdr3_motif_input",
            disabled=disabled
        )
        if light_cdr3_motif and not validate_motif_input(light_cdr3_motif):
            st.error(MOTIF_ERROR_TEXT, icon=":material/error:")
            light_cdr3_motif_valid = False
            validation_errors.append("Light CDRL3 Motif")
        
        light_cdr3_similarity, light_cdr3_mismatches = _render_motif_match_controls(
            light_cdr3_motif,
            f"{prefix}cdr3_similarity_toggle",
            f"{prefix}cdr3_mismatches_input",
            disabled
        )

    with col4:
        st.empty()
    
    # Build parameters dict
    params = {
        f"{prefix}v": light_v,
        f"{prefix}j": light_j,
        f"{prefix}cdr1_length": light_cdr1_length,
        f"{prefix}cdr2_length": light_cdr2_length,
        f"{prefix}cdr3_length": light_cdr3_length,
        f"{prefix}cdr1_motif": light_cdr1_motif,
        f"{prefix}cdr2_motif": light_cdr2_motif,
        f"{prefix}cdr3_motif": light_cdr3_motif,
        f"{prefix}cdr1_similarity": light_cdr1_similarity,
        f"{prefix}cdr2_similarity": light_cdr2_similarity,
        f"{prefix}cdr3_similarity": light_cdr3_similarity,
        f"{prefix}cdr1_mismatches": light_cdr1_mismatches,
        f"{prefix}cdr2_mismatches": light_cdr2_mismatches,
        f"{prefix}cdr3_mismatches": light_cdr3_mismatches,
    }
    
    valid = all([light_v_valid, light_j_valid, light_cdr1_length_valid, light_cdr2_length_valid, light_cdr3_length_valid, light_cdr1_motif_valid, light_cdr2_motif_valid, light_cdr3_motif_valid])
    
    return params, validation_errors, valid


CLEAR_SEARCH_MASK_FLAG = "_clear_search_mask"
APPLY_EXAMPLE_SEARCH_FLAG = "_apply_example_search"

EXAMPLE_SEARCH_CRITERIA: Dict[str, Any] = {
    "unpaired_heavy": {
        "v": "",
        "d": "3-3",
        "j": "",
        "cdr1_length": "",
        "cdr2_length": "",
        "cdr3_length": ">=29",
        "cdr1_motif": "",
        "cdr2_motif": "",
        "cdr3_motif": ".{15}*[FI]W[ST].{8}*",
        "cdr1_similarity": False,
        "cdr2_similarity": False,
        "cdr3_similarity": False,
        "cdr1_mismatches": 0,
        "cdr2_mismatches": 0,
        "cdr3_mismatches": 0,
    },
    "unpaired_light": {
        "v": "K3",
        "j": "K2",
        "cdr1_length": "",
        "cdr2_length": "",
        "cdr3_length": "9",
        "cdr1_motif": "",
        "cdr2_motif": "",
        "cdr3_motif": "QQY*",
        "cdr1_similarity": False,
        "cdr2_similarity": False,
        "cdr3_similarity": False,
        "cdr1_mismatches": 0,
        "cdr2_mismatches": 0,
        "cdr3_mismatches": 0,
    },
    "paired": {
        "heavy": {
            "v": "1-69",
            "d": "",
            "j": "6",
            "cdr1_length": "",
            "cdr2_length": "",
            "cdr3_length": "18-22",
            "cdr1_motif": "",
            "cdr2_motif": "",
            "cdr3_motif": "",
            "cdr1_similarity": False,
            "cdr2_similarity": False,
            "cdr3_similarity": False,
            "cdr1_mismatches": 0,
            "cdr2_mismatches": 0,
            "cdr3_mismatches": 0,
        },
        "light": {
            "v": "K3",
            "j": "K4",
            "cdr1_length": "",
            "cdr2_length": "",
            "cdr3_length": "9",
            "cdr1_motif": "",
            "cdr2_motif": "",
            "cdr3_motif": "",
            "cdr1_similarity": False,
            "cdr2_similarity": False,
            "cdr3_similarity": False,
            "cdr1_mismatches": 0,
            "cdr2_mismatches": 0,
            "cdr3_mismatches": 0,
        },
    },
}


def _heavy_mask_keys(prefix: str) -> Dict[str, Any]:
    """Widget keys + reset values for a heavy-chain search mask."""
    if prefix:
        v_key, d_key, j_key = f"{prefix}v_input", f"{prefix}d_input", f"{prefix}j_input"
        length_prefix = motif_prefix = sim_prefix = mm_prefix = prefix
    else:
        v_key, d_key, j_key = "ighv_input", "ighd_input", "ighj_input"
        length_prefix = motif_prefix = sim_prefix = mm_prefix = ""

    keys: Dict[str, Any] = {
        v_key: "",
        d_key: "",
        j_key: "",
        f"{length_prefix}cdr1_length_input": "",
        f"{length_prefix}cdr2_length_input": "",
        f"{length_prefix}cdr3_length_input": "",
        f"{motif_prefix}cdr1_motif_input": "",
        f"{motif_prefix}cdr2_motif_input": "",
        f"{motif_prefix}cdr3_motif_input": "",
        f"{sim_prefix}cdr1_similarity_toggle": False,
        f"{sim_prefix}cdr2_similarity_toggle": False,
        f"{sim_prefix}cdr3_similarity_toggle": False,
        f"{mm_prefix}cdr1_mismatches_input": 0,
        f"{mm_prefix}cdr2_mismatches_input": 0,
        f"{mm_prefix}cdr3_mismatches_input": 0,
    }
    return keys


def _light_mask_keys(prefix: str = "light_") -> Dict[str, Any]:
    """Widget keys + reset values for a light-chain search mask."""
    return {
        f"{prefix}v_input": "",
        f"{prefix}j_input": "",
        f"{prefix}cdr1_length_input": "",
        f"{prefix}cdr2_length_input": "",
        f"{prefix}cdr3_length_input": "",
        f"{prefix}cdr1_motif_input": "",
        f"{prefix}cdr2_motif_input": "",
        f"{prefix}cdr3_motif_input": "",
        f"{prefix}cdr1_similarity_toggle": False,
        f"{prefix}cdr2_similarity_toggle": False,
        f"{prefix}cdr3_similarity_toggle": False,
        f"{prefix}cdr1_mismatches_input": 0,
        f"{prefix}cdr2_mismatches_input": 0,
        f"{prefix}cdr3_mismatches_input": 0,
    }


def clear_search_mask_session_state() -> None:
    """
    Reset all Database Search criteria widgets in session state.

    Must run before the form widgets are instantiated (Streamlit requirement).
    Does not change database selection.
    """
    resets: Dict[str, Any] = {}
    # Unpaired heavy (no prefix) + paired heavy
    for prefix in ("", "heavy_"):
        resets.update(_heavy_mask_keys(prefix))
    # Unpaired/paired light
    for prefix in ("light_",):
        resets.update(_light_mask_keys(prefix))

    for key, value in resets.items():
        st.session_state[key] = value

    st.session_state.pop("search_validation_error", None)
    st.session_state.pop("search_prefill_message", None)


def _apply_heavy_example_to_session(prefix: str, example: Dict[str, Any]) -> None:
    """Write heavy-chain example fields onto the matching widget keys."""
    if prefix:
        st.session_state[f"{prefix}v_input"] = example.get("v", "") or ""
        st.session_state[f"{prefix}d_input"] = example.get("d", "") or ""
        st.session_state[f"{prefix}j_input"] = example.get("j", "") or ""
        field_prefix = prefix
    else:
        st.session_state["ighv_input"] = example.get("v", "") or ""
        st.session_state["ighd_input"] = example.get("d", "") or ""
        st.session_state["ighj_input"] = example.get("j", "") or ""
        field_prefix = ""

    for cdr in ("cdr1", "cdr2", "cdr3"):
        st.session_state[f"{field_prefix}{cdr}_length_input"] = example.get(f"{cdr}_length", "") or ""
        st.session_state[f"{field_prefix}{cdr}_motif_input"] = example.get(f"{cdr}_motif", "") or ""
        st.session_state[f"{field_prefix}{cdr}_similarity_toggle"] = bool(
            example.get(f"{cdr}_similarity", False)
        )
        st.session_state[f"{field_prefix}{cdr}_mismatches_input"] = int(
            example.get(f"{cdr}_mismatches", 0) or 0
        )


def _apply_light_example_to_session(prefix: str, example: Dict[str, Any]) -> None:
    """Write light-chain example fields onto the matching widget keys."""
    st.session_state[f"{prefix}v_input"] = example.get("v", "") or ""
    st.session_state[f"{prefix}j_input"] = example.get("j", "") or ""
    for cdr in ("cdr1", "cdr2", "cdr3"):
        st.session_state[f"{prefix}{cdr}_length_input"] = example.get(f"{cdr}_length", "") or ""
        st.session_state[f"{prefix}{cdr}_motif_input"] = example.get(f"{cdr}_motif", "") or ""
        st.session_state[f"{prefix}{cdr}_similarity_toggle"] = bool(
            example.get(f"{cdr}_similarity", False)
        )
        st.session_state[f"{prefix}{cdr}_mismatches_input"] = int(
            example.get(f"{cdr}_mismatches", 0) or 0
        )


def apply_example_search_mask(search_mode: str) -> None:
    """
    Fill the search mask with the example for the current Heavy / Light / Paired mode.

    Must run before the form widgets are instantiated. Does not change database selection.
    """
    clear_search_mask_session_state()

    if search_mode == "paired":
        paired = EXAMPLE_SEARCH_CRITERIA.get("paired") or {}
        _apply_heavy_example_to_session("heavy_", paired.get("heavy") or {})
        _apply_light_example_to_session("light_", paired.get("light") or {})
    elif search_mode == "unpaired_light":
        _apply_light_example_to_session(
            "light_", EXAMPLE_SEARCH_CRITERIA.get("unpaired_light") or {}
        )
    else:
        _apply_heavy_example_to_session(
            "", EXAMPLE_SEARCH_CRITERIA.get("unpaired_heavy") or {}
        )

