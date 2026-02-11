import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path

# Override page title (inherits other settings from app.py)
st.set_page_config(page_title="ABHunter - Statistics", layout="wide")

# Main content
st.markdown("# :material/bar_chart: Statistics")
st.markdown("---")

# Introduction
st.markdown("""
## V<sub>H</sub>/V<sub>L</sub> Pairing Inference Methodology

The pairing statistics that drive ABHunter are constructed in `plots/inferred_vh_vl.ipynb`. This page explains the statistical approach and visualizes the key results.

**Dataset Overview:**
- **Paired sequences:** 568,137 valid pairs from `data/Paired/All/`
- **Unpaired heavy chains:** ~1.58 billion sequences from `data/Heavy/`
- **Unpaired light chains:** ~278 million sequences from `data/Light/`
""", unsafe_allow_html=True)

# Helper functions for data processing
def extract_family_number(fam: str) -> int:
    """Extract numeric part from family name."""
    digits = ''.join(ch for ch in str(fam) if ch.isdigit())
    return int(digits) if digits else 0

def sort_vh_families(families):
    """Sort VH families: IGHV1-8 first, then others."""
    return sorted(families, key=lambda x: (not str(x).startswith('IGHV'), extract_family_number(str(x))))

def sort_vl_families(families):
    """Sort VL families: IGKV1-7 first, then IGLV1-11."""
    def vl_sort_key(fam: str):
        fam_str = str(fam)
        if fam_str.startswith('IGKV'):
            return (0, extract_family_number(fam_str))
        if fam_str.startswith('IGLV'):
            return (1, extract_family_number(fam_str))
        return (2, fam_str)
    return sorted(families, key=vl_sort_key)

# Load precomputed paired statistics
@st.cache_data
def load_paired_statistics():
    """Load precomputed paired VH:VL statistics from public folder."""
    base_path = Path("public/statistics/vh_vl")
    
    if not base_path.exists():
        return None, None, None, None, None
    
    try:
        vh_marginals = pd.read_parquet(base_path / "vh_family_marginals.pq")
        vl_marginals = pd.read_parquet(base_path / "vl_family_marginals.pq")
        vh_vl_joint = pd.read_parquet(base_path / "vh_vl_joint.pq")
        expected_joint = pd.read_parquet(base_path / "expected_joint.pq")
        comparison = pd.read_parquet(base_path / "pairing_correction_ratio.pq")
        
        return vh_marginals, vl_marginals, vh_vl_joint, expected_joint, comparison
    except Exception as e:
        st.error(f"Error loading precomputed statistics: {e}")
        return None, None, None, None, None

# Load precomputed unpaired statistics
@st.cache_data
def load_unpaired_statistics():
    """Load precomputed unpaired V gene family frequencies from public folder."""
    base_path = Path("public/statistics/vh_vl")
    
    if not base_path.exists():
        return None, None
    
    try:
        heavy_freq = pd.read_parquet(base_path / "heavy_unpaired_freq.pq")
        light_freq = pd.read_parquet(base_path / "light_unpaired_freq.pq")
        return heavy_freq, light_freq
    except Exception as e:
        st.error(f"Error loading unpaired statistics: {e}")
        return None, None

# Load adjusted frequencies
@st.cache_data
def load_adjusted_frequencies():
    """Load the final adjusted frequency table with h_to_l and l_to_h from public folder."""
    base_path = Path("public/statistics/vh_vl")
    
    if not base_path.exists():
        return None
    
    try:
        adj_freq = pd.read_parquet(base_path / "adjusted_frequencies_search.pq")
        # Return only the columns needed for visualization
        return adj_freq[['vh_family', 'vl_family', 'h_to_l', 'l_to_h']]
    except Exception as e:
        st.error(f"Error loading adjusted frequencies: {e}")
        return None

# Load data
vh_marginals, vl_marginals, vh_vl_joint, expected_joint, comparison = load_paired_statistics()
heavy_unpaired, light_unpaired = load_unpaired_statistics()
adj_freq_df = load_adjusted_frequencies()

if vh_marginals is not None:
    st.markdown("---")
    
    # Step 1: Paired Repertoire Scan
    st.markdown("### Step 1: Paired Repertoire Scan")
    st.markdown(r"""
    **Objective:** Extract empirical V<sub>H</sub>:V<sub>L</sub> co-occurrence patterns from paired antibody sequences.
    
    **Method:**
    - All parquet files under `data/Paired/All/` are scanned using DuckDB for fast aggregation
    - For each paired sequence, extract `v_call_heavy` and `v_call_light`
    - Count co-occurrences: how many times each V<sub>H</sub> gene pairs with each V<sub>L</sub> gene
    - **Quality control:** Discard suspect rows where family prefixes are swapped
    - **Result:** 568,137 valid paired sequences with clean V<sub>H</sub>:V<sub>L</sub> assignments
    """, unsafe_allow_html=True)
    
    # Step 2: Family-Level Marginals
    st.markdown("### Step 2: Family-Level Marginal Frequencies")
    st.markdown(r"""
    **Objective:** Compute marginal distributions P(V<sub>H</sub>) and P(V<sub>L</sub>) from the paired dataset.
    
    **Mathematical Formulation:**
    
    For heavy chain families:
    $$
    P(V_{H,i}) = \frac{\sum_j \text{count}(V_{H,i}, V_{L,j})}{N_{\text{paired}}}
    $$
    
    For light chain families:
    $$
    P(V_{L,j}) = \frac{\sum_i \text{count}(V_{H,i}, V_{L,j})}{N_{\text{paired}}}
    $$
    
    where $N_{\text{paired}} = 568,137$ is the total number of valid paired sequences.
    """, unsafe_allow_html=True)
    
    # Show marginal frequencies table
    if vh_marginals is not None and vl_marginals is not None:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### V<sub>H</sub> Family Frequencies", unsafe_allow_html=True)
            st.dataframe(
                vh_marginals[['vh_family', 'vh_family_count', 'vh_family_frequency']]
                .rename(columns={
                    'vh_family': 'Family',
                    'vh_family_count': 'Count',
                    'vh_family_frequency': 'Frequency'
                })
                .style.format({'Frequency': '{:.4f}'}),
                width='stretch',
                hide_index=True
            )
        
        with col2:
            st.markdown("#### V<sub>L</sub> Family Frequencies", unsafe_allow_html=True)
            st.dataframe(
                vl_marginals[['vl_family', 'vl_family_count', 'vl_family_frequency']]
                .rename(columns={
                    'vl_family': 'Family',
                    'vl_family_count': 'Count',
                    'vl_family_frequency': 'Frequency'
                })
                .style.format({'Frequency': '{:.4f}'}),
                width='stretch',
                hide_index=True
            )
    
    # Step 3: Independence Baseline
    st.markdown("### Step 3: Independence Baseline (Expected Frequencies)")
    st.markdown(r"""
    **Objective:** Calculate what the joint distribution would look like if V<sub>H</sub> and V<sub>L</sub> paired randomly.
    
    **Mathematical Formulation:**
    
    Under the independence assumption, the expected joint frequency is:
    $$
    P_{\text{exp}}(V_{H,i}, V_{L,j}) = P(V_{H,i}) \times P(V_{L,j})
    $$
    
    This creates a baseline expectation: if pairing were random, what frequency would we expect for each family pair?
    """, unsafe_allow_html=True)
    
    # Step 4: Observed Paired Frequencies
    st.markdown("### Step 4: Observed Paired Frequencies")
    st.markdown(r"""
    **Objective:** Calculate the actual observed joint frequencies from the paired dataset.
    
    **Mathematical Formulation:**
    
    For each family pair (V<sub>H,i</sub>, V<sub>L,j</sub>):
    $$
    P_{\text{obs}}(V_{H,i}, V_{L,j}) = \frac{\text{count}(V_{H,i}, V_{L,j})}{N_{\text{paired}}}
    $$
    
    Missing combinations are filled with zeros (33 family pairs were never observed).
    """, unsafe_allow_html=True)
    
    # Create observed frequency heatmap
    if vh_vl_joint is not None:
        observed_matrix = vh_vl_joint.pivot(index='vh_family', columns='vl_family', values='pair_frequency')
        vh_order = sort_vh_families(observed_matrix.index)
        vl_order = sort_vl_families(observed_matrix.columns)
        observed_matrix = observed_matrix.reindex(index=vh_order, columns=vl_order)
        observed_matrix_percent = observed_matrix * 100
        
        fig_observed = go.Figure(data=go.Heatmap(
            z=observed_matrix_percent.values,
            x=[str(col) for col in observed_matrix.columns],
            y=[str(row) for row in observed_matrix.index],
            colorscale=[
                [0, '#D9D8D8'],
                [0.01, '#d6e0ec'],
                [0.2, '#8fa1c1'],
                [0.4, '#4C6085'],
                [0.6, '#8c516d'],
                [0.8, '#cb4154'],
                [1, '#cb4154']
            ],
            colorbar=dict(
                title="Observed Frequency (%)",
                title_side="right",
                tickmode="array",
                tickvals=[0, 1, 5, 10, 15, 20],
                ticktext=["0%", "1%", "5%", "10%", "15%", "20%"]
            ),
            hovertemplate='V<sub>H</sub>: %{y}<br>V<sub>L</sub>: %{x}<br>Observed Frequency: %{z:.2f}%<extra></extra>',
            showscale=True
        ))
        
        fig_observed.update_layout(
            title=dict(
                text=r"Observed V<sub>H</sub> : V<sub>L</sub> Paired Frequencies (P<sub>obs</sub>)",
                x=0.5,
                font=dict(size=20)
            ),
            xaxis=dict(title="V<sub>L</sub> Family", tickangle=45),
            yaxis=dict(title="V<sub>H</sub> Family"),
            width=1000,
            height=700,
            margin=dict(l=100, r=50, t=100, b=100)
        )
        
        st.plotly_chart(fig_observed, config={'displayModeBar': True})
    
    # Step 5: Pairing Correction Ratio
    st.markdown("### Step 5: Pairing Correction Ratio")
    st.markdown(r"""
    **Objective:** Quantify how much each family pair deviates from random pairing expectations.
    
    **Mathematical Formulation:**
    
    For each family pair, calculate the correction ratio:
    $$
    R_{i,j} = \frac{P_{\text{obs}}(V_{H,i}, V_{L,j})}{P_{\text{exp}}(V_{H,i}, V_{L,j})}
    $$
    
    **Special cases:**
    - If $P_{\text{exp}} = 0$ or $P_{\text{obs}} = 0$, set $R_{i,j} = 1.0$
    
    **Interpretation:**
    - $R_{i,j} > 1$: Pairing is **enriched** relative to random (more common than expected)
    - $R_{i,j} = 1$: Pairing matches random expectation
    - $R_{i,j} < 1$: Pairing is **depleted** relative to random (less common than expected)
    """, unsafe_allow_html=True)
    
    # Create correction ratio and difference heatmaps
    if comparison is not None:
        ratio_matrix = comparison.pivot(index='vh_family', columns='vl_family', values='pairing_correction_ratio')
        diff_matrix = comparison.pivot(index='vh_family', columns='vl_family', values='pair_freq_minus_expected')
        
        vh_order = sort_vh_families(ratio_matrix.index)
        vl_order = sort_vl_families(ratio_matrix.columns)
        ratio_matrix = ratio_matrix.reindex(index=vh_order, columns=vl_order)
        diff_matrix = diff_matrix.reindex(index=vh_order, columns=vl_order)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### Pairing Correction Ratio")
            fig_ratio = go.Figure(data=go.Heatmap(
                z=ratio_matrix.values,
                x=[str(col) for col in ratio_matrix.columns],
                y=[str(row) for row in ratio_matrix.index],
                colorscale=[
                    [0, '#4C6085'],
                    [0.3, '#d6e0ec'],
                    [0.5, '#ffffff'],
                    [0.7, '#e3a6b2'],
                    [1, '#cb4154']
                ],
                zmid=1.0,
                zmin=0,
                zmax=3.5,
                colorbar=dict(
                    title="Ratio (R)",
                    title_side="right",
                    tickmode="array",
                    tickvals=[0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5],
                    ticktext=["0", "0.5", "1", "1.5", "2", "2.5", "3", "3.5"]
                ),
                hovertemplate='V<sub>H</sub>: %{y}<br>V<sub>L</sub>: %{x}<br>Correction Ratio: %{z:.3f}<extra></extra>',
                showscale=True
            ))
            
            fig_ratio.update_layout(
                title=dict(text=r"R<sub>i,j</sub> = P<sub>obs</sub>/P<sub>exp</sub>", x=0.5, font=dict(size=16)),
                xaxis=dict(title="V<sub>L</sub> Family", tickangle=45),
                yaxis=dict(title="V<sub>H</sub> Family"),
                width=500,
                height=600,
                margin=dict(l=80, r=20, t=60, b=80)
            )
            
            st.plotly_chart(fig_ratio, config={'displayModeBar': True})
        
        with col2:
            st.markdown("#### Observed - Expected Difference")
            diff_max = np.nanmax(np.abs(diff_matrix.values))
            fig_diff = go.Figure(data=go.Heatmap(
                z=diff_matrix.values,
                x=[str(col) for col in diff_matrix.columns],
                y=[str(row) for row in diff_matrix.index],
                colorscale=[
                    [0, '#4C6085'],
                    [0.3, '#879EBA'],
                    [0.5, '#ffffff'],
                    [0.7, '#CD8A97'],
                    [1, '#cb4154']
                ],
                zmid=0.0,
                zmin=-diff_max,
                zmax=diff_max,
                colorbar=dict(
                    title="Difference",
                    title_side="right"
                ),
                hovertemplate='V<sub>H</sub>: %{y}<br>V<sub>L</sub>: %{x}<br>Difference: %{z:.6f}<extra></extra>',
                showscale=True
            ))
            
            fig_diff.update_layout(
                title=dict(text=r"P<sub>obs</sub> - P<sub>exp</sub>", x=0.5, font=dict(size=16)),
                xaxis=dict(title="V<sub>L</sub> Family", tickangle=45),
                yaxis=dict(title="V<sub>H</sub> Family"),
                width=500,
                height=600,
                margin=dict(l=80, r=20, t=60, b=80)
            )
            
            st.plotly_chart(fig_diff, config={'displayModeBar': True})
    
    # Step 6: Unpaired Population Anchor
    st.markdown("### Step 6: Unpaired Population Anchor")
    st.markdown(r"""
    **Objective:** Leverage massive unpaired datasets to get robust baseline family frequencies.
    
    **Mathematical Formulation:**
    
    Compute marginal frequencies from unpaired data:
    $$
    F_{\text{unpaired},H}(V_{H,i}) = \frac{\text{count}(V_{H,i} \text{ in unpaired heavy})}{N_{\text{unpaired},H}}
    $$
    
    $$
    F_{\text{unpaired},L}(V_{L,j}) = \frac{\text{count}(V_{L,j} \text{ in unpaired light})}{N_{\text{unpaired},L}}
    $$
    
    Expected joint distribution under random pairing:
    $$
    F_{\text{unpaired,rand}}(V_{H,i}, V_{L,j}) = F_{\text{unpaired},H}(V_{H,i}) \times F_{\text{unpaired},L}(V_{L,j})
    $$
    
    where $N_{\text{unpaired},H} \approx 1.58 \times 10^9$ and $N_{\text{unpaired},L} \approx 2.78 \times 10^8$.
    """, unsafe_allow_html=True)
    
    # Show unpaired vs paired marginals comparison
    if vh_marginals is not None and heavy_unpaired is not None:
        vh_merged = vh_marginals.merge(
            heavy_unpaired.rename(columns={'v_family': 'vh_family', 'frequency': 'unpaired_frequency'}),
            on='vh_family',
            how='left'
        ).fillna({'unpaired_frequency': 0})
        
        fig_vh_comparison = go.Figure()
        
        # Sort VH families properly
        vh_order = sort_vh_families(vh_merged['vh_family'].tolist())
        vh_merged_sorted = vh_merged.set_index('vh_family').reindex(vh_order).reset_index()
        
        fig_vh_comparison.add_trace(go.Bar(
            x=vh_merged_sorted['vh_family'],
            y=vh_merged_sorted['vh_family_frequency'] * 100,
            name='Paired Dataset',
            marker_color='#ccd8e8'
        ))
        
        fig_vh_comparison.add_trace(go.Bar(
            x=vh_merged_sorted['vh_family'],
            y=vh_merged_sorted['unpaired_frequency'] * 100,
            name='Unpaired Dataset',
            marker_color='#cb4154'
        ))
        
        fig_vh_comparison.update_layout(
            title=dict(text="V<sub>H</sub> Family Frequency: Paired vs Unpaired", x=0.5, font=dict(size=18)),
            xaxis=dict(title="V<sub>H</sub> Family"),
            yaxis=dict(title="Frequency (%)"),
            barmode='group',
            height=400,
            margin=dict(l=60, r=20, t=80, b=60)
        )
        
        st.plotly_chart(fig_vh_comparison, config={'displayModeBar': True})
    
    if vl_marginals is not None and light_unpaired is not None:
        vl_merged = vl_marginals.merge(
            light_unpaired.rename(columns={'v_family': 'vl_family', 'frequency': 'unpaired_frequency'}),
            on='vl_family',
            how='left'
        ).fillna({'unpaired_frequency': 0})
        
        fig_vl_comparison = go.Figure()
        
        # Sort VL families properly
        vl_order = sort_vl_families(vl_merged['vl_family'].tolist())
        vl_merged_sorted = vl_merged.set_index('vl_family').reindex(vl_order).reset_index()
        
        fig_vl_comparison.add_trace(go.Bar(
            x=vl_merged_sorted['vl_family'],
            y=vl_merged_sorted['vl_family_frequency'] * 100,
            name='Paired Dataset',
            marker_color='#ccd8e8'
        ))
        
        fig_vl_comparison.add_trace(go.Bar(
            x=vl_merged_sorted['vl_family'],
            y=vl_merged_sorted['unpaired_frequency'] * 100,
            name='Unpaired Dataset',
            marker_color='#cb4154'
        ))
        
        fig_vl_comparison.update_layout(
            title=dict(text="V<sub>L</sub> Family Frequency: Paired vs Unpaired", x=0.5, font=dict(size=18)),
            xaxis=dict(title="V<sub>L</sub> Family", tickangle=45),
            yaxis=dict(title="Frequency (%)"),
            barmode='group',
            height=400,
            margin=dict(l=60, r=20, t=80, b=100)
        )
        
        st.plotly_chart(fig_vl_comparison, config={'displayModeBar': True})
    
    # Step 7: Adjusted Pairing Surface
    st.markdown("### Step 7: Adjusted Pairing Surface")
    st.markdown(r"""
    **Objective:** Combine unpaired baseline frequencies with paired correction ratios to estimate true pairing probabilities.
    
    **Mathematical Formulation:**
    
    Multiply the unpaired random expectation by the correction ratio:
    $$
    F_{\text{unpaired,est}}(V_{H,i}, V_{L,j}) = F_{\text{unpaired,rand}}(V_{H,i}, V_{L,j}) \times R_{i,j}
    $$
    
    This creates an **adjusted frequency** for every family pair, even those not observed in the paired dataset.
    """, unsafe_allow_html=True)
    
    # Step 8: Directional Normalization
    st.markdown("### Step 8: Directional Normalization")
    st.markdown(r"""
    **Objective:** Create conditional probability distributions for practical use in the search engine.
    
    **Mathematical Formulation:**
    
    **Heavy-to-Light (h_to_l):** For each V<sub>H</sub> family, normalize adjusted frequencies across all V<sub>L</sub> families
    $$
    \text{h\_to\_l}(V_{H,i}, V_{L,j}) = \frac{F_{\text{est}}(V_{H,i}, V_{L,j})}{\sum_k F_{\text{est}}(V_{H,i}, V_{L,k})} \times 100\%
    $$
    
    Answers: "Given V<sub>H,i</sub>, which V<sub>L</sub> is most likely?" Each row sums to 100%.
    
    **Light-to-Heavy (l_to_h):** For each V<sub>L</sub> family, normalize adjusted frequencies across all V<sub>H</sub> families
    $$
    \text{l\_to\_h}(V_{H,i}, V_{L,j}) = \frac{F_{\text{est}}(V_{H,i}, V_{L,j})}{\sum_k F_{\text{est}}(V_{H,k}, V_{L,j})} \times 100\%
    $$
    
    Answers: "Given V<sub>L,j</sub>, which V<sub>H</sub> is most likely?" Each column sums to 100%.
    """, unsafe_allow_html=True)
    
    # Visualize the final normalized distributions
    st.markdown("---")
    st.markdown("### Final Normalized Pairing Probabilities")
    st.markdown("""
    The following heatmaps show the final normalized probabilities used by ABHunter:
    """, unsafe_allow_html=True)
    
    if adj_freq_df is not None and not adj_freq_df.empty:
        h_to_l_matrix = adj_freq_df.pivot(index='vh_family', columns='vl_family', values='h_to_l')
        l_to_h_matrix = adj_freq_df.pivot(index='vh_family', columns='vl_family', values='l_to_h')
        
        vh_order = sort_vh_families(h_to_l_matrix.index)
        vl_order = sort_vl_families(h_to_l_matrix.columns)
        h_to_l_matrix = h_to_l_matrix.reindex(index=vh_order, columns=vl_order)
        l_to_h_matrix = l_to_h_matrix.reindex(index=vh_order, columns=vl_order)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### Heavy-to-Light (h_to_l)")
            st.markdown(r"""
            **P(V<sub>L</sub> | V<sub>H</sub>)**
            
            Each row sums to 100%, showing the conditional distribution of V<sub>L</sub> given V<sub>H</sub>.
            """, unsafe_allow_html=True)
            
            fig_h_to_l = go.Figure(data=go.Heatmap(
                z=h_to_l_matrix.values,
                x=[str(col) for col in h_to_l_matrix.columns],
                y=[str(row) for row in h_to_l_matrix.index],
                colorscale=[
                    [0, '#D9D8D8'],
                    [0.01, '#d6e0ec'],
                    [0.2, '#8fa1c1'],
                    [0.4, '#4C6085'],
                    [0.6, '#8c516d'],
                    [0.8, '#cb4154'],
                    [1, '#cb4154']
                ],
                colorbar=dict(title="Probability (%)", title_side="right"),
                hovertemplate='V<sub>H</sub>: %{y}<br>V<sub>L</sub>: %{x}<br>Probability: %{z:.2f}%<extra></extra>',
                showscale=True
            ))
            
            fig_h_to_l.update_layout(
                title=dict(text="P(V<sub>L</sub> | V<sub>H</sub>)", x=0.5, font=dict(size=16)),
                xaxis=dict(title="V<sub>L</sub> Family", tickangle=45),
                yaxis=dict(title="V<sub>H</sub> Family"),
                width=500,
                height=600,
                margin=dict(l=80, r=20, t=60, b=80)
            )
            
            st.plotly_chart(fig_h_to_l, config={'displayModeBar': True})
        
        with col2:
            st.markdown("#### Light-to-Heavy (l_to_h)")
            st.markdown(r"""
            **P(V<sub>H</sub> | V<sub>L</sub>)**
            
            Each column sums to 100%, showing the conditional distribution of V<sub>H</sub> given V<sub>L</sub>.
            """, unsafe_allow_html=True)
            
            fig_l_to_h = go.Figure(data=go.Heatmap(
                z=l_to_h_matrix.values,
                x=[str(col) for col in l_to_h_matrix.columns],
                y=[str(row) for row in l_to_h_matrix.index],
                colorscale=[
                    [0, '#D9D8D8'],
                    [0.01, '#d6e0ec'],
                    [0.2, '#8fa1c1'],
                    [0.4, '#4C6085'],
                    [0.6, '#8c516d'],
                    [0.8, '#cb4154'],
                    [1, '#cb4154']
                ],
                colorbar=dict(title="Probability (%)", title_side="right"),
                hovertemplate='V<sub>H</sub>: %{y}<br>V<sub>L</sub>: %{x}<br>Probability: %{z:.2f}%<extra></extra>',
                showscale=True
            ))
            
            fig_l_to_h.update_layout(
                title=dict(text="P(V<sub>H</sub> | V<sub>L</sub>)", x=0.5, font=dict(size=16)),
                xaxis=dict(title="V<sub>L</sub> Family", tickangle=45),
                yaxis=dict(title="V<sub>H</sub> Family"),
                width=500,
                height=600,
                margin=dict(l=80, r=20, t=60, b=80)
            )
            
            st.plotly_chart(fig_l_to_h, config={'displayModeBar': True})
    
    # Summary
    st.markdown("---")
    st.markdown("### Summary")
    st.markdown(r"""
    This statistical pipeline successfully combines:
    
    1. **Empirical paired signals** (568k sequences) - Captures real pairing preferences
    2. **Deep unpaired coverage** (1.86B sequences) - Provides robust baseline frequencies
    3. **Correction ratios** - Quantifies deviations from random pairing
    4. **Normalized probabilities** - Creates practical conditional distributions
    
    **Final Output:** The `adj_freq_table2.parquet` file contains 144 family pairs with:
    - `h_to_l`: Conditional probability P(V<sub>L</sub> | V<sub>H</sub>) in percentage
    - `l_to_h`: Conditional probability P(V<sub>H</sub> | V<sub>L</sub>) in percentage
    
    These probabilities power ABHunter's pairing inference, allowing the search engine to suggest likely V<sub>H</sub>/V<sub>L</sub> combinations even when only one chain is known.
    """, unsafe_allow_html=True)

else:
    st.error("Could not load precomputed statistics. Please ensure the files exist in `public/statistics/vh_vl/`.")
