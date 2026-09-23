import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pathlib import Path
from components.search.styling import INFERRED_LIGHT_COLORSCALE

PLOTLY_DISPLAY_CONFIG = {
    "displayModeBar": False,
}

st.set_page_config(page_title="ABHunter Inferred Pairing")

st.markdown("# :material/modeling: Inferred Pairing")
st.markdown("---")

st.markdown(
    """
Since natively paired sequences represent only a small fraction of the dataset and
originate from a limited six-donor cohort, we developed a statistically inferred pairing
model to turn pairing observations into an estimated functional repertoire map for
the unpaired sequences.

Raw pairing frequencies (*P*<sub>obs</sub>) are influenced by the overall abundance of
individual gene segments. The Laplace-smoothed pairing correction ratio *R*<sub>i,j</sub>
measures relative deviation from random pairing rather than absolute frequency. 
Specific IGHV:IG(K/L)V and IGHJ:IG(K/L)J combinations show positive bias (*R*<sub>i,j</sub> > 1) 
or negative bias (*R*<sub>i,j</sub> < 1), even when individual genes are abundant.

A Pearson χ² test of independence confirms non-random deviations globally, but effect
sizes are small (pairing remains largely stochastic to maximize diversity, with
localized deterministic biases). These *R*<sub>i,j</sub> values provide the basis for
predicting likely heavy- or light-chain partners for given V and/or J genes in ABHunter.
""",
    unsafe_allow_html=True,
)


def extract_family_number(fam: str) -> int:
    digits = "".join(ch for ch in str(fam) if ch.isdigit())
    return int(digits) if digits else 0


def sort_vh_families(families):
    return sorted(
        families,
        key=lambda x: (not str(x).startswith("IGHV"), extract_family_number(str(x))),
    )


def sort_vl_families(families):
    def vl_sort_key(fam: str):
        fam_str = str(fam)
        if fam_str.startswith("IGKV"):
            return (0, extract_family_number(fam_str))
        if fam_str.startswith("IGLV"):
            return (1, extract_family_number(fam_str))
        return (2, fam_str)

    return sorted(families, key=vl_sort_key)


def sort_jh_families(families):
    return sorted(families, key=lambda x: extract_family_number(str(x)))


def sort_jl_families(families):
    def jl_sort_key(fam: str):
        fam_str = str(fam)
        if fam_str.startswith("IGKJ"):
            return (0, extract_family_number(fam_str))
        if fam_str.startswith("IGLJ"):
            return (1, extract_family_number(fam_str))
        return (2, fam_str)

    return sorted(families, key=jl_sort_key)


@st.cache_data
def load_r_tables():
    base = Path(__file__).resolve().parent.parent / "static" / "inferred"
    vh_path = base / "vh_vl_R_values.csv"
    jh_path = base / "jh_jl_R_values.csv"
    if not vh_path.exists() and not jh_path.exists():
        return None, None
    vh = pd.read_csv(vh_path) if vh_path.exists() else None
    jh = pd.read_csv(jh_path) if jh_path.exists() else None
    return vh, jh


def _plotly_colorscale(scale):
    return [[float(pos), color] for pos, color in scale]


NO_VALUE_EDGE_LIGHT = "#D4D4D4"
NO_VALUE_TICK_LIGHT = "#949494"
ACTIVE_TICK_LIGHT = "#404040"
OUTLINE_LIGHT = "black"

NO_VALUE_EDGE_DARK = "#D4D4D4"
NO_VALUE_TICK_DARK = "#C8C8C8"
ACTIVE_TICK_DARK = "#FFFFFF"
OUTLINE_DARK = "#FFFFFF"


def _is_dark_mode() -> bool:
    """Detect Streamlit dark theme; leave light-mode colors unchanged when light."""
    theme = getattr(st.context, "theme", None)
    theme_type = None
    if theme is not None:
        theme_type = theme.get("type") if hasattr(theme, "get") else getattr(theme, "type", None)
    if theme_type in ("dark", "light"):
        return theme_type == "dark"
    try:
        return st.get_option("theme.base") == "dark"
    except Exception:
        return False


def _theme_colors(dark: bool) -> dict:
    if dark:
        return {
            "outline": OUTLINE_DARK,
            "active_tick": ACTIVE_TICK_DARK,
            "no_value_tick": NO_VALUE_TICK_DARK,
            "no_value_edge": NO_VALUE_EDGE_DARK,
            "label": ACTIVE_TICK_DARK,
        }
    return {
        "outline": OUTLINE_LIGHT,
        "active_tick": ACTIVE_TICK_LIGHT,
        "no_value_tick": NO_VALUE_TICK_LIGHT,
        "no_value_edge": NO_VALUE_EDGE_LIGHT,
        "label": ACTIVE_TICK_LIGHT,
    }


# Families dropped from the active grid (no paired counts) — shown hatched like the publication figures
V_NO_VALUE_HEAVY = {"IGHV8"}
V_NO_VALUE_LIGHT = {"IGKV7", "IGLV11"}
J_NO_VALUE_LIGHT = {"IGLJ4", "IGLJ5"}


def _tick_html(labels, gray_labels: set, active_color: str, gray_color: str) -> list:
    """Gray-out axis labels for families with no data."""
    return [
        (
            f'<span style="color:{gray_color}">{lab}</span>'
            if lab in gray_labels
            else f'<span style="color:{active_color}">{lab}</span>'
        )
        for lab in labels
    ]


def _hatch_shapes(mask: np.ndarray, edge_color: str) -> list:
    """Diagonal hatch overlays for no-value cells (publication-style '///').

    Plotly layout shapes do not support fillpattern here, so we draw diagonal
    line segments inside each no-value cell.
    """
    shapes = []
    n_rows, n_cols = mask.shape
    lines_per_cell = 6
    for yi in range(n_rows):
        for xi in range(n_cols):
            if not mask[yi, xi]:
                continue
            x0, x1 = xi - 0.5, xi + 0.5
            y0, y1 = yi - 0.5, yi + 0.5
            shapes.append(
                dict(
                    type="rect",
                    xref="x",
                    yref="y",
                    x0=x0,
                    x1=x1,
                    y0=y0,
                    y1=y1,
                    line=dict(width=0.5, color=edge_color),
                    fillcolor="rgba(255,255,255,1)",
                    layer="above",
                )
            )
            # Parallel diagonals y = x + b (matplotlib hatch '///')
            b_min, b_max = (y0 - x1), (y1 - x0)
            for i in range(1, lines_per_cell + 1):
                b = b_min + i / (lines_per_cell + 1) * (b_max - b_min)
                pts = []
                for x, y in (
                    (x0, x0 + b),
                    (x1, x1 + b),
                    (y0 - b, y0),
                    (y1 - b, y1),
                ):
                    if x0 - 1e-9 <= x <= x1 + 1e-9 and y0 - 1e-9 <= y <= y1 + 1e-9:
                        pts.append((float(x), float(y)))
                uniq = []
                for p in pts:
                    if all(abs(p[0] - q[0]) > 1e-9 or abs(p[1] - q[1]) > 1e-9 for q in uniq):
                        uniq.append(p)
                if len(uniq) >= 2:
                    shapes.append(
                        dict(
                            type="line",
                            xref="x",
                            yref="y",
                            x0=uniq[0][0],
                            y0=uniq[0][1],
                            x1=uniq[1][0],
                            y1=uniq[1][1],
                            line=dict(width=1.2, color=edge_color),
                            layer="above",
                        )
                    )
    return shapes


def render_log2r_heatmap(
    df: pd.DataFrame,
    heavy_col: str,
    light_col: str,
    title: str,
    x_title: str,
    y_title: str,
    sort_heavy,
    sort_light,
    no_value_heavy: set | None = None,
    no_value_light: set | None = None,
) -> go.Figure:
    """Heatmap of log2(R) with '*' on significant cells and hatches for no-data families."""
    colors = _theme_colors(_is_dark_mode())
    no_value_heavy = set(no_value_heavy or ())
    no_value_light = set(no_value_light or ())

    pivot = df.pivot(index=heavy_col, columns=light_col, values="log2_R")
    status = df.pivot(index=heavy_col, columns=light_col, values="Status")

    heavy_order = sort_heavy(list(set(pivot.index) | no_value_heavy))
    light_order = sort_light(list(set(pivot.columns) | no_value_light))
    pivot = pivot.reindex(index=heavy_order, columns=light_order)
    status = status.reindex(index=heavy_order, columns=light_order)

    # Mark no-value families (entire row and/or column) — publication "No value" hatching
    no_value_mask = np.zeros(pivot.shape, dtype=bool)
    for yi, heavy in enumerate(heavy_order):
        for xi, light in enumerate(light_order):
            if heavy in no_value_heavy or light in no_value_light:
                no_value_mask[yi, xi] = True
                pivot.iat[yi, xi] = np.nan

    text = status.map(lambda s: "*" if str(s) in ("Enriched", "Depleted") else "")
    # Clear stars on no-value cells
    for yi in range(no_value_mask.shape[0]):
        for xi in range(no_value_mask.shape[1]):
            if no_value_mask[yi, xi]:
                text.iat[yi, xi] = ""

    finite = pivot.values[np.isfinite(pivot.values)]
    abs_max = float(np.nanmax(np.abs(finite))) if finite.size else 1.0
    abs_max = max(abs_max, 0.1)

    x_labels = [str(c) for c in pivot.columns]
    y_labels = [str(r) for r in pivot.index]

    hover_custom = np.where(
        no_value_mask,
        "No value",
        np.vectorize(lambda v: f"log₂(R): {v:.4f}" if np.isfinite(v) else "No value")(
            pivot.values
        ),
    )

    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.values,
            x=x_labels,
            y=y_labels,
            colorscale=_plotly_colorscale(INFERRED_LIGHT_COLORSCALE),
            zmid=0.0,
            zmin=-abs_max,
            zmax=abs_max,
            text=text.values,
            texttemplate="%{text}",
            textfont={"size": 36, "color": "black"},
            colorbar=dict(
                title=dict(text="log₂(R)", font=dict(color=colors["label"])),
                title_side="right",
                tickfont=dict(color=colors["label"]),
            ),
            hovertemplate=(
                f"{y_title}: %{{y}}<br>{x_title}: %{{x}}"
                "<br>%{customdata}<extra></extra>"
            ),
            customdata=hover_custom,
            showscale=True,
        )
    )
    fig.update_layout(
        title=dict(
            text=title,
            x=0.5,
            xanchor="center",
            xref="paper",
            font=dict(size=26, color=colors["label"]),
        ),
        xaxis=dict(
            title=dict(text=x_title, font=dict(size=20, color=colors["label"])),
            tickmode="array",
            tickvals=x_labels,
            ticktext=_tick_html(
                x_labels,
                no_value_light,
                colors["active_tick"],
                colors["no_value_tick"],
            ),
            tickfont=dict(size=20),
            tickangle=45,
            showline=True,
            linewidth=1,
            linecolor=colors["outline"],
            mirror=True,
        ),
        yaxis=dict(
            title=dict(text=y_title, font=dict(size=20, color=colors["label"])),
            tickmode="array",
            tickvals=y_labels,
            ticktext=_tick_html(
                y_labels,
                no_value_heavy,
                colors["active_tick"],
                colors["no_value_tick"],
            ),
            tickfont=dict(size=20),
            autorange="reversed",
            showline=True,
            linewidth=1,
            linecolor=colors["outline"],
            mirror=True,
        ),
        shapes=_hatch_shapes(no_value_mask, colors["no_value_edge"]),
        height=560,
        margin=dict(l=110, r=40, t=80, b=110),
    )
    return fig


vh_df, jh_df = load_r_tables()

st.markdown("---")
st.markdown("### Workflow")
st.markdown(
    """
1. **Raw count matrix** — count co-occurrences of gene families in paired data
   (IGHV:IG(K/L)V or IGHJ:IG(K/L)J).
2. **Active grid filter** — drop families with total raw count 0, keeping only
   active cells (V: 7×16 = 112; J: active IGHJ:IG(K/L)J grid).
3. **Split analysis:**
   - **Significance** (χ² post-hoc on **raw** active counts) → Status ∈ {Enriched, Depleted, NS (Not significant)}
   - **Enrichment model** — Laplace smoothing (*a* = 1) on active cells only → *R*<sub>i,j</sub> and log₂(*R*<sub>i,j</sub>)
""",
    unsafe_allow_html=True,
)

st.markdown("### Laplace-smoothed correction ratio *R*<sub>i,j</sub>", unsafe_allow_html=True)
st.markdown(
    """
On the active matrix with additive smoothing *a* = 1 (to reduce sparse-cell zeros):
""",
    unsafe_allow_html=True,
)
st.latex(r"n'_{ij} = n_{ij} + 1,\quad N' = \sum_{ij} n'_{ij},\quad P_{\mathrm{obs}}(i,j) = \frac{n'_{ij}}{N'}")
st.markdown("Marginals come from the same smoothed matrix:")
st.latex(
    r"P(H_i)=\sum_j P_{\mathrm{obs}}(i,j),\quad "
    r"P(L_j)=\sum_i P_{\mathrm{obs}}(i,j),\quad "
    r"P_{\mathrm{rand}}(i,j)=P(H_i)\,P(L_j)"
)
st.markdown(
    """
The correction ratio normalizes abundance effects by comparing observed pairing to
independence (*P*<sub>rand</sub>):
""",
    unsafe_allow_html=True,
)
st.latex(
    r"R_{ij}=\frac{P_{\mathrm{obs}}(i,j)}{P_{\mathrm{rand}}(i,j)},\quad "
    r"\log_2 R_{ij}=\log_2\!\left(\frac{P_{\mathrm{obs}}(i,j)}{P_{\mathrm{rand}}(i,j)}\right)"
)
st.markdown(
    """
**Interpretation**
- *R*<sub>i,j</sub> > 1 (log₂(*R*) > 0): positive pairing bias (enriched vs random)
- *R*<sub>i,j</sub> = 1 (log₂(*R*) = 0): matches random / independence
- *R*<sub>i,j</sub> < 1 (log₂(*R*) < 0): negative pairing bias (depleted vs random)
""",
    unsafe_allow_html=True,
)

st.markdown("### How significance (Enriched / Depleted) is calculated")
st.markdown(
    """
To assess whether deviations from independence reflect localized pairing biases
(beyond abundance-driven *P*<sub>obs</sub>), significance is evaluated on the raw 
active contingency table (no Laplace smoothing).

1. **χ² test of independence** on the raw active count matrix → expected counts under independence.
2. **Adjusted residuals** for each cell *(i, j)*:
""",
    unsafe_allow_html=True,
)
st.latex(
    r"r_{ij}^{\mathrm{adj}} = \frac{O_{ij}-E_{ij}}{\sqrt{E_{ij}\,(1-p_{i\cdot})\,(1-p_{\cdot j})}}"
)
st.markdown(
    """
3. **Two-sided *p*-values** from the standard normal distribution of |adjusted residual|.
4. **Bonferroni correction:** a cell is statistically significant if
"""
)
st.latex(r"p_{ij} < \frac{0.05}{n_{\mathrm{cells}}}")
st.markdown(
    """
5. **Biological fold-change filter** on raw counts, with
"""
)
st.latex(r"\mathrm{FC}_{ij} = O_{ij}/E_{ij}")
st.markdown(
    """
A cell is labeled:

- **Enriched** if significant **and** adjusted residual > 2 **and** FC ≥ 1.20
- **Depleted** if significant **and** adjusted residual < −2 **and** FC ≤ 0.80
- **NS** (Not significant) otherwise

In the heatmaps below:
- **Enriched** and **Depleted** cells are marked with `*`
- Hatched cells (**No value**) are families with no paired data.
"""
)

if vh_df is None and jh_df is None:
    st.error("Could not load enrichment tables.")
    st.stop()

if vh_df is not None:
    st.markdown("---")
    st.markdown("### IGHV:IG(K/L)V enrichment")

    n_enr = int((vh_df["Status"] == "Enriched").sum())
    n_dep = int((vh_df["Status"] == "Depleted").sum())
    n_ns = int((vh_df["Status"] == "NS").sum())
    st.markdown(
        f"**Active pairs:** {len(vh_df)} "
        f"(Enriched: {n_enr}, Depleted: {n_dep}, NS: {n_ns}). "
        "Color = log₂(R). `*` = significant; hatched = no value."
    )

    st.plotly_chart(
        render_log2r_heatmap(
            vh_df,
            heavy_col="vh_family",
            light_col="vl_family",
            title="log₂(R) for IGHV:IG(K/L)V",
            x_title="IG(K/L)V Family",
            y_title="IGHV Family",
            sort_heavy=sort_vh_families,
            sort_light=sort_vl_families,
            no_value_heavy=V_NO_VALUE_HEAVY,
            no_value_light=V_NO_VALUE_LIGHT,
        ),
        config=PLOTLY_DISPLAY_CONFIG,
        use_container_width=True,
    )

if jh_df is not None:
    st.markdown("---")
    st.markdown("### IGHJ:IG(K/L)J enrichment")

    n_enr = int((jh_df["Status"] == "Enriched").sum())
    n_dep = int((jh_df["Status"] == "Depleted").sum())
    n_ns = int((jh_df["Status"] == "NS").sum())
    st.markdown(
        f"**Active pairs:** {len(jh_df)} "
        f"(Enriched: {n_enr}, Depleted: {n_dep}, NS: {n_ns}). "
        "Color = log₂(R). `*` = significant; hatched = no value."
    )

    st.plotly_chart(
        render_log2r_heatmap(
            jh_df,
            heavy_col="jh_family",
            light_col="jl_family",
            title="log₂(R) for IGHJ:IG(K/L)J",
            x_title="IG(K/L)J Family",
            y_title="IGHJ Family",
            sort_heavy=sort_jh_families,
            sort_light=sort_jl_families,
            no_value_light=J_NO_VALUE_LIGHT,
        ),
        config=PLOTLY_DISPLAY_CONFIG,
        use_container_width=True,
    )
