"""
IgBLAST test page: input heavy and/or light chain **nucleotide** sequence(s),
run igblastn with V, D, J germline DBs, and display V(D)J gene assignments.
"""
import streamlit as st

from components.igblast_utils import (
    is_igblast_available,
    run_heavy_chain_vdj,
    run_light_chain_vj,
)
from components.search.styling import get_chain_color

st.set_page_config(page_title="ABHunter - IgBLAST Gene ID", page_icon="🧬")

st.title(":blue[:material/genetics: IgBLAST Gene Identification]")
st.markdown(
    "Enter heavy and/or light chain **nucleotide** sequence(s) (V region or full chain). "
    "IgBLAST will run with V, D, J germline databases and return **V, D, J** (heavy) or **V, J** (light) genes."
)

col_heavy, col_light = st.columns(2)

with col_heavy:
    st.subheader("Heavy chain (VH)")
    heavy_seq = st.text_area(
        "Nucleotide sequence",
        key="heavy_seq",
        height=120,
        placeholder="e.g. GAGGTGCAGCTGGTGGAATCCGGAGGCGGGGTCGTGCAGCCTGGAGG...",
        label_visibility="collapsed",
    )

with col_light:
    st.subheader("Light chain (VL)")
    light_seq = st.text_area(
        "Nucleotide sequence",
        key="light_seq",
        height=120,
        placeholder="e.g. CAGATTGTGCTGACCCAGTCTCCATCTTCCCTG...",
        label_visibility="collapsed",
    )

run_heavy = bool(heavy_seq and heavy_seq.strip())
run_light = bool(light_seq and light_seq.strip())

if "igblast_heavy" not in st.session_state:
    st.session_state.igblast_heavy = None
if "igblast_light" not in st.session_state:
    st.session_state.igblast_light = None

if not run_heavy and not run_light:
    st.info("Enter at least one sequence (heavy and/or light) to run IgBLAST.")

if st.button("Run IgBLAST", type="primary"):
    if run_heavy:
        with st.spinner("Running IgBLAST for heavy chain (V, D, J)..."):
            seq_h = heavy_seq.strip()
            res_h, err_h = run_heavy_chain_vdj(seq_h)
            st.session_state.igblast_heavy = (res_h, err_h)
            st.session_state.igblast_input_heavy = seq_h
    else:
        st.session_state.igblast_heavy = None
        st.session_state.igblast_input_heavy = None

    if run_light:
        with st.spinner("Running IgBLAST for light chain (V, J; kappa vs lambda)..."):
            seq_l = light_seq.strip()
            res_l, err_l = run_light_chain_vj(seq_l)
            st.session_state.igblast_light = (res_l, err_l)
            st.session_state.igblast_input_light = seq_l
    else:
        st.session_state.igblast_light = None
        st.session_state.igblast_input_light = None

    st.rerun()

# Show last results
results_heavy = st.session_state.igblast_heavy
results_light = st.session_state.igblast_light

def _esc(s: str) -> str:
    """Escape * for Markdown."""
    return s.replace("*", "\\*")


def _gene_hit_label(row) -> str:
    """Format one hit row as 'gene (identity%, bit_score)' for checkbox label."""
    gene = str(row.get("subject id", ""))
    ident = row.get("% identity")
    bit_score = row.get("bit score")
    if ident is not None and bit_score is not None:
        try:
            return f"{gene} ({float(ident):.2f}%, {float(bit_score):.0f})"
        except (TypeError, ValueError):
            pass
    if ident is not None:
        try:
            return f"{gene} ({float(ident):.2f}%)"
        except (TypeError, ValueError):
            pass
    return gene or "—"


def _render_gene_hits_with_checkboxes(g: dict | None, chain_key: str, gene_type: str, max_hits: int = 3) -> None:
    """Render up to max_hits germline hits as checkboxes (label = gene (identity%, bit_score)), all checked by default."""
    if g is None or g.get("df") is None or g["df"].empty:
        st.markdown("—")
        return
    df = g["df"].head(max_hits)
    for i, (_, row) in enumerate(df.iterrows()):
        label = _gene_hit_label(row)
        key = f"igblast_cb_{chain_key}_{gene_type}_{i}"
        st.checkbox(label=label, value=True, key=key)


def _render_cdr_in_column(cdr: dict, name: str, chain_key: str, cdr_key: str) -> None:
    """Render one CDR in column: checkboxes next to Motif and Length (both checked by default)."""
    if not cdr:
        st.markdown("—")
        return
    info = cdr.get(name)
    if not info:
        st.markdown("—")
        return
    aa = (info.get("aa") or "").strip()
    if not aa:
        st.markdown("—")
        return
    aa_len = len(aa)
    st.checkbox(
        label=f"Motif: {aa}",
        value=True,
        key=f"igblast_cb_{chain_key}_{cdr_key}_motif",
    )
    st.checkbox(
        label=f"Length: {aa_len} aa",
        value=True,
        key=f"igblast_cb_{chain_key}_{cdr_key}_length",
    )


def _render_cdr_info_expander(cdr: dict) -> None:
    """Render expander 'CDR info' with full CDR details (Motif, Length, NT, positions) for CDR1/2/3."""
    if not cdr or not any(cdr.get(name) for name in ("CDR1", "CDR2", "CDR3")):
        return
    with st.expander("**CDR info**", expanded=False):
        for name in ("CDR1", "CDR2", "CDR3"):
            info = cdr.get(name)
            if not info:
                continue
            aa = (info.get("aa") or "").strip()
            nt = (info.get("nt") or "").strip()
            start = info.get("start")
            end = info.get("end")
            pos = f" [{start}–{end}]" if start is not None and end is not None else ""
            st.markdown(f"**{name}**")
            st.markdown(f"Motif: {_esc(aa) if aa else '—'}  \nLength: {len(aa) if aa else 0} aa")
            if nt:
                st.caption(f"NT: `{nt}`{pos}")
            st.markdown("")


def _render_genes_and_cdr_three_columns(
    v_gene: dict | None,
    d_gene: dict | None,
    j_gene: dict | None,
    cdr: dict,
    has_d: bool,
    chain: str,
    chain_key: str,
) -> None:
    """Render V, D, J in one row and CDR1, CDR2, CDR3 in the next row as 3 columns (search-mask style).
    chain: 'H' or 'L' for subscript; chain_key: 'heavy' or 'light' for checkbox keys.
    """
    sub = f"<sub>{chain}</sub>"
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"**V{sub}**", unsafe_allow_html=True)
        _render_gene_hits_with_checkboxes(v_gene, chain_key, "v")
    with col2:
        if has_d:
            st.markdown(f"**D{sub}**", unsafe_allow_html=True)
            _render_gene_hits_with_checkboxes(d_gene, chain_key, "d")
        else:
            st.markdown("—")
            st.markdown("—")
    with col3:
        st.markdown(f"**J{sub}**", unsafe_allow_html=True)
        _render_gene_hits_with_checkboxes(j_gene, chain_key, "j")
    st.markdown("")  # spacing
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**CDR1**")
        _render_cdr_in_column(cdr, "CDR1", chain_key, "cdr1")
    with c2:
        st.markdown("**CDR2**")
        _render_cdr_in_column(cdr, "CDR2", chain_key, "cdr2")
    with c3:
        st.markdown("**CDR3**")
        _render_cdr_in_column(cdr, "CDR3", chain_key, "cdr3")


def _gene_for_search(gene_str: str | None, chain: str) -> str:
    """Convert IgBLAST gene name to search form format (strip IGHV/IGHD/IGHJ/IGLV/IGLJ/IGKV/IGKJ prefix)."""
    if not gene_str or not gene_str.strip():
        return ""
    s = gene_str.strip()
    for prefix in ("IGHV", "IGHD", "IGHJ", "IGLV", "IGLJ", "IGKV", "IGKJ"):
        if s.upper().startswith(prefix):
            return s[len(prefix):].strip() or s
    return s


def _genes_for_search(g: dict | None, chain: str) -> str:
    """Primary gene plus all same-score ties, comma-separated, for database search fields."""
    if g is None or g.get("gene") is None:
        return ""
    primary = _gene_for_search(g["gene"], chain)
    ties = g.get("ties") or []
    parts = [primary] + [_gene_for_search(t, chain) for t in ties]
    seen = set()
    out = []
    for x in parts:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return ",".join(out)


def _checked_genes_for_search(g: dict | None, chain: str, chain_key: str, gene_type: str, max_hits: int = 3) -> str:
    """Comma-separated list of genes that have their checkbox checked (by index)."""
    if g is None or g.get("df") is None or g["df"].empty:
        return ""
    df = g["df"].head(max_hits)
    parts = []
    seen = set()
    for i, (_, row) in enumerate(df.iterrows()):
        if not st.session_state.get(f"igblast_cb_{chain_key}_{gene_type}_{i}", True):
            continue
        gene_full = str(row.get("subject id", ""))
        gene = _gene_for_search(gene_full, chain)
        if gene and gene not in seen:
            seen.add(gene)
            parts.append(gene)
    return ",".join(parts)


def _checked_cdr_len(cdr: dict, name: str, chain_key: str, cdr_key: str) -> str | None:
    """Return CDR length string if the length checkbox is checked, else None."""
    if not st.session_state.get(f"igblast_cb_{chain_key}_{cdr_key}_length", True):
        return None
    return _cdr_len(cdr, name)


def _checked_cdr_motif(cdr: dict, name: str, chain_key: str, cdr_key: str) -> str:
    """Return CDR motif if the motif checkbox is checked, else ''."""
    if not st.session_state.get(f"igblast_cb_{chain_key}_{cdr_key}_motif", True):
        return ""
    return _cdr_motif(cdr, name)


def _cdr_len(cdr: dict, name: str) -> str | None:
    """Return CDR length as string for form (amino acid length), or None."""
    if not cdr:
        return None
    info = cdr.get(name)
    if not info:
        return None
    aa = info.get("aa") or ""
    if not aa:
        return None
    return str(len(aa))


def _cdr_motif(cdr: dict, name: str) -> str:
    """Return CDR motif for search form: AA sequence with * before and after, or empty string."""
    if not cdr:
        return ""
    info = cdr.get(name)
    if not info:
        return ""
    aa = (info.get("aa") or "").strip()
    if not aa:
        return ""
    return f"*{aa}*"


def _build_igblast_prefill(mode: str, res_h: dict | None, res_l: dict | None) -> dict:
    """Build search_prefill_from_igblast from checked boxes only. mode: unpaired_heavy | unpaired_light | paired | dual_unpaired."""
    heavy = None
    if res_h and (res_h.get("V", {}).get("gene") or res_h.get("D", {}).get("gene") or res_h.get("J", {}).get("gene")):
        v = res_h.get("V") or {}
        d = res_h.get("D") or {}
        j = res_h.get("J") or {}
        cdr = res_h.get("cdr") or {}
        heavy = {
            "v": _checked_genes_for_search(v, "heavy", "heavy", "v"),
            "d": _checked_genes_for_search(d, "heavy", "heavy", "d"),
            "j": _checked_genes_for_search(j, "heavy", "heavy", "j"),
            "cdr1_length": _checked_cdr_len(cdr, "CDR1", "heavy", "cdr1"),
            "cdr2_length": _checked_cdr_len(cdr, "CDR2", "heavy", "cdr2"),
            "cdr3_length": _checked_cdr_len(cdr, "CDR3", "heavy", "cdr3"),
            "cdr1_motif": _checked_cdr_motif(cdr, "CDR1", "heavy", "cdr1"),
            "cdr2_motif": _checked_cdr_motif(cdr, "CDR2", "heavy", "cdr2"),
            "cdr3_motif": _checked_cdr_motif(cdr, "CDR3", "heavy", "cdr3"),
        }
    light = None
    if res_l and (res_l.get("V", {}).get("gene") or res_l.get("J", {}).get("gene")):
        v = res_l.get("V") or {}
        j = res_l.get("J") or {}
        cdr = res_l.get("cdr") or {}
        light = {
            "v": _checked_genes_for_search(v, "light", "light", "v"),
            "j": _checked_genes_for_search(j, "light", "light", "j"),
            "cdr1_length": _checked_cdr_len(cdr, "CDR1", "light", "cdr1"),
            "cdr2_length": _checked_cdr_len(cdr, "CDR2", "light", "cdr2"),
            "cdr3_length": _checked_cdr_len(cdr, "CDR3", "light", "cdr3"),
            "cdr1_motif": _checked_cdr_motif(cdr, "CDR1", "light", "cdr1"),
            "cdr2_motif": _checked_cdr_motif(cdr, "CDR2", "light", "cdr2"),
            "cdr3_motif": _checked_cdr_motif(cdr, "CDR3", "light", "cdr3"),
        }
    return {"mode": mode, "heavy": heavy, "light": light}


if results_heavy is not None or results_light is not None:
    st.divider()
    st.header("Results")

    has_heavy = (
        results_heavy is not None
        and not results_heavy[1]
        and results_heavy[0]
        and (results_heavy[0].get("V", {}).get("gene") or results_heavy[0].get("D", {}).get("gene") or results_heavy[0].get("J", {}).get("gene"))
    )
    has_light = (
        results_light is not None
        and not results_light[1]
        and results_light[0]
        and (results_light[0].get("V", {}).get("gene") or results_light[0].get("J", {}).get("gene"))
    )

    if has_heavy or has_light:
        st.markdown("#### Use results for Database search")
        prefill_btns = st.columns([1, 1, 1])
        with prefill_btns[0]:
            if has_heavy and not has_light:
                if st.button("Use in Database search (unpaired heavy)", type="secondary", use_container_width=True):
                    st.session_state["search_prefill_from_igblast"] = _build_igblast_prefill(
                        "unpaired_heavy", results_heavy[0], None
                    )
                    st.switch_page("pages/search.py")
            elif has_light and not has_heavy:
                if st.button("Use in Database search (unpaired light)", type="secondary", use_container_width=True):
                    st.session_state["search_prefill_from_igblast"] = _build_igblast_prefill(
                        "unpaired_light", None, results_light[0]
                    )
                    st.switch_page("pages/search.py")
            elif has_heavy and has_light:
                if st.button("Use in Database search (paired)", type="secondary", use_container_width=True):
                    st.session_state["search_prefill_from_igblast"] = _build_igblast_prefill(
                        "paired", results_heavy[0], results_light[0]
                    )
                    st.switch_page("pages/search.py")
        with prefill_btns[1]:
            if has_heavy and has_light:
                if st.button("Use in Database search (dual unpaired)", type="secondary", use_container_width=True):
                    st.session_state["search_prefill_from_igblast"] = _build_igblast_prefill(
                        "dual_unpaired", results_heavy[0], results_light[0]
                    )
                    st.switch_page("pages/search.py")
        st.info("You may have to adjust gen names for the database search.")

    # Heavy chain results (full width)
    if results_heavy is not None:
        res_h, err_h = results_heavy
        if err_h:
            st.error(f"**Heavy chain:** {err_h}")
        else:
            heavy_color = get_chain_color("heavy")
            st.markdown(
                f"<h4 style='color: {heavy_color}; margin-top: 0; margin-bottom: 0.5rem;'>Heavy Chain (VDJ)</h4>",
                unsafe_allow_html=True,
            )
            _render_genes_and_cdr_three_columns(
                res_h.get("V"),
                res_h.get("D"),
                res_h.get("J"),
                res_h.get("cdr") or {},
                has_d=True,
                chain="H",
                chain_key="heavy",
            )
            input_heavy = st.session_state.get("igblast_input_heavy") or ""
            if input_heavy:
                with st.expander("**Input sequence**", expanded=False):
                    st.text(input_heavy)
            for key, label in [("V", "V gene"), ("D", "D gene"), ("J", "J gene")]:
                g = res_h.get(key)
                if g and g.get("df") is not None and not g["df"].empty:
                    with st.expander(f"Top germline hits — {label}"):
                        st.dataframe(g["df"], width="stretch", hide_index=True)
            _render_cdr_info_expander(res_h.get("cdr") or {})

    # Light chain results (full width, below heavy)
    if results_light is not None:
        res_l, err_l = results_light
        if err_l:
            st.error(f"**Light chain:** {err_l}")
        else:
            light_color = get_chain_color("light")
            st.markdown(
                f"<h4 style='color: {light_color}; margin-top: 0; margin-bottom: 0.5rem;'>Light Chain (VJ)</h4>",
                unsafe_allow_html=True,
            )
            _render_genes_and_cdr_three_columns(
                res_l.get("V"),
                None,
                res_l.get("J"),
                res_l.get("cdr") or {},
                has_d=False,
                chain="L",
                chain_key="light",
            )
            input_light = st.session_state.get("igblast_input_light") or ""
            if input_light:
                with st.expander("**Input sequence**", expanded=False):
                    st.text(input_light)
            for key, label in [("V", "V gene"), ("J", "J gene")]:
                g = res_l.get(key)
                if g and g.get("df") is not None and not g["df"].empty:
                    with st.expander(f"Top germline hits — {label}"):
                        st.dataframe(g["df"], width="stretch", hide_index=True)
            _render_cdr_info_expander(res_l.get("cdr") or {})
