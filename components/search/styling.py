"""Styling utilities for search components."""

import streamlit as st

HEAVY_COLOR = "#4C6085"
LIGHT_COLOR = "#CB4154"
PAIRED_COLOR = "#3F3839"
HEAVY_COLORSCALE = [
    (0.0, "#F8F8F8"),
    (0.5, "#D8DEE9"),
    (1.0, HEAVY_COLOR),
]
LIGHT_COLORSCALE = [
    (0.0, "#F8F8F8"),
    (0.5, "#F7D5DB"),
    (1.0, LIGHT_COLOR),
]

HEAVY_LINE = "rgba(76, 96, 133, 0.5)"
HEAVY_FILL = "rgba(76, 96, 133, 0.2)"
LIGHT_LINE = "rgba(203, 65, 84, 0.5)"
LIGHT_FILL = "rgba(203, 65, 84, 0.2)"


def get_chain_color(chain: str) -> str:
    """Return the accent hex for heavy, light, or paired."""
    key = (chain or "heavy").lower()
    if key == "light":
        return LIGHT_COLOR
    if key == "paired":
        return PAIRED_COLOR
    return HEAVY_COLOR


def icon_heading(icon: str, text: str, level: int, margin_top: float = 0):
    """
    Render a heading with an icon.
    Args:
        icon: The icon+color to use (heavy, light, paired).
        text: The text to display.
        level: The level of the heading.
        margin_top: The margin-top to use (default 0).
    """
    color = get_chain_color(icon)

    st.markdown(
        f"<h{level} style='color: {color}; margin-top: {margin_top}rem; margin-bottom: 0.5rem;'>"
        f"<img src='app/static/icons/{icon}.png' style='width:55px; height:55px; margin-right:8px; vertical-align:middle;' />"
        f"{text}</h{level}>",
        unsafe_allow_html=True,
    )
