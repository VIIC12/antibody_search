"""Styling utilities for search components."""

import streamlit as st

HEAVY_COLOR = "#89AAE7FF"
PAIRED_COLOR = "#3F3839"
LIGHT_COLOR = "#CB243D"

HEAVY_PLOT_COLOR = "#4C6085"
LIGHT_PLOT_COLOR = "#9B3232"


def get_chain_color(chain: str) -> str:
    """Return the hexadecimal color for the given chain type."""
    return HEAVY_COLOR if chain.lower() == "heavy" else LIGHT_COLOR

def icon_heading(icon: str, text: str, level: int, margin_top: float = 0):
    """
    Render a heading with an icon.
    Args:
        icon: The icon to use (heavy, light, paired).
        text: The text to display.
        level: The level of the heading.
        margin_top: The margin-top to use (default 0).
    """

    if icon == "heavy":
        color = HEAVY_COLOR
    elif icon == "light":
        color = LIGHT_COLOR
    elif icon == "paired":
        color = PAIRED_COLOR

    st.markdown(
        f"<h{level} style='color: {color}; margin-top: {margin_top}rem; margin-bottom: 0.5rem;'>"
        f"<img src='app/static/icons/{icon}.png' style='width:55px; height:55px; margin-right:8px; vertical-align:middle;' />"
        f"{text}</h{level}>",
        unsafe_allow_html=True,
    )