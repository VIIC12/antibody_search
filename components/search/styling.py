"""Styling utilities for search components."""

from typing import Optional

import streamlit as st


HEAVY_COLOR = "#89AAE7FF"
LIGHT_COLOR = "#CB4154"


def get_chain_color(chain: str) -> str:
    """Return the hexadecimal color for the given chain type."""
    return HEAVY_COLOR if chain.lower() == "heavy" else LIGHT_COLOR


def render_chain_heading(
    text: str,
    chain: str,
    *,
    level: int = 4,
    icon: Optional[str] = None,
    margin_top: str = "0.5rem",
    margin_bottom: str = "0.5rem",
    use_chain_color: bool = True,
) -> None:
    """Render a Streamlit heading with consistent chain coloring."""

    color = get_chain_color(chain) if use_chain_color else "inherit"
    icon_prefix = f"{icon} " if icon else ""
    st.markdown(
        f"<h{level} style='color: {color}; margin-top: {margin_top}; margin-bottom: {margin_bottom};'>"
        f"{icon_prefix}{text}</h{level}>",
        unsafe_allow_html=True,
    )

