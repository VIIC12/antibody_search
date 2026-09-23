"""Styling utilities for search components."""

import streamlit as st
from typing import Callable, List, Tuple

HEAVY_COLOR = "#4C6085"
HEAVY_COLOR_DARK_MODE = "#8B9DB8"  # lighter blue for headings/markers on dark backgrounds
LIGHT_COLOR = "#CB4154"
PAIRED_COLOR = "#FFFFFF"

# Dark-mode bar scales (pale → accent). Light mode uses darker low/mid stops — see getters below.
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
HEAVY_COLORSCALE_LIGHT_MODE = [
    (0.0, "#C5CDD8"),
    (0.5, "#9AA8BC"),
    (1.0, HEAVY_COLOR),
]
LIGHT_COLORSCALE_LIGHT_MODE = [
    (0.0, "#E0C8CC"),
    (0.5, "#E09AA5"),
    (1.0, LIGHT_COLOR),
]

# Inferred pairing log2(R): diverging around 0
# Heavy search → predicted light: red (>0) → white (0) → blue (<0)
INFERRED_LIGHT_COLORSCALE = [
    (0.0, HEAVY_COLOR),
    (0.5, "#FFFFFF"),
    (1.0, LIGHT_COLOR),
]
# Light search → predicted heavy: blue (>0) → white (0) → red (<0)
INFERRED_HEAVY_COLORSCALE = [
    (0.0, LIGHT_COLOR),
    (0.5, "#FFFFFF"),
    (1.0, HEAVY_COLOR),
]

HEAVY_LINE = "rgba(76, 96, 133, 0.5)"
HEAVY_FILL = "rgba(76, 96, 133, 0.2)"
HEAVY_LINE_DARK_MODE = "rgba(139, 157, 184, 0.5)"
HEAVY_FILL_DARK_MODE = "rgba(139, 157, 184, 0.2)"
LIGHT_LINE = "rgba(203, 65, 84, 0.5)"
LIGHT_FILL = "rgba(203, 65, 84, 0.2)"


def is_dark_mode() -> bool:
    """Detect Streamlit dark theme."""
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


def get_heavy_colorscale() -> List[Tuple[float, str]]:
    """Heavy-chain frequency colorscale for the active theme."""
    return HEAVY_COLORSCALE if is_dark_mode() else HEAVY_COLORSCALE_LIGHT_MODE


def get_light_colorscale() -> List[Tuple[float, str]]:
    """Light-chain frequency colorscale for the active theme."""
    return LIGHT_COLORSCALE if is_dark_mode() else LIGHT_COLORSCALE_LIGHT_MODE


def get_chain_colorscale(chain: str) -> List[Tuple[float, str]]:
    """Frequency colorscale for heavy or light chain under the active theme."""
    if (chain or "heavy").lower() == "light":
        return get_light_colorscale()
    return get_heavy_colorscale()


def get_chain_color(chain: str) -> str:
    """Return the accent hex for heavy, light, or paired (theme-aware for heavy)."""
    key = (chain or "heavy").lower()
    if key == "light":
        return LIGHT_COLOR
    if key == "paired":
        return PAIRED_COLOR
    return HEAVY_COLOR_DARK_MODE if is_dark_mode() else HEAVY_COLOR


def get_chain_line_fill(chain: str) -> Tuple[str, str]:
    """Return (line, fill) rgba colors for box/donor plots."""
    key = (chain or "heavy").lower()
    if key == "light":
        return LIGHT_LINE, LIGHT_FILL
    if is_dark_mode():
        return HEAVY_LINE_DARK_MODE, HEAVY_FILL_DARK_MODE
    return HEAVY_LINE, HEAVY_FILL


def icon_heading(icon: str, text: str, level: int, margin_top: float = 0):
    """
    Render a heading with an icon.
    Args:
        icon: The icon+color to use (heavy, light, paired).
        text: The text to display.
        level: The level of the heading.
        margin_top: The margin-top to use (default 0).
    """
    # Paired uses Streamlit's default heading color so it follows light/dark theme.
    if (icon or "").lower() == "paired":
        color_style = ""
    else:
        color_style = f"color: {get_chain_color(icon)}; "

    st.markdown(
        f"<h{level} style='{color_style}margin-top: {margin_top}rem; margin-bottom: 0.5rem;'>"
        f"<img src='app/static/icons/{icon}.png' style='width:55px; height:55px; margin-right:8px; vertical-align:middle;' />"
        f"{text}</h{level}>",
        unsafe_allow_html=True,
    )


def render_preparing_button(label: str = "Preparing...") -> None:
    """Disabled button with an in-button CSS spinner (shared across all download buttons)."""
    st.markdown(
        f"""
        <div class="download-button-container">
            <button disabled style="
                width: 100%;
                padding: 0.5rem 1rem;
                background-color: rgb(49, 51, 63);
                color: rgb(250, 250, 250);
                border: 1px solid rgb(49, 51, 63);
                border-radius: 0.25rem;
                cursor: not-allowed;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                font-size: 0.875rem;
            ">
                <div class="spinner-dark"></div>
                <span>{label}</span>
            </button>
        </div>
        """,
        unsafe_allow_html=True,
    )


def create_preparing_progress(initial_label: str = "Preparing...") -> Callable[[str], None]:
    """
    Create an updatable preparing-button slot.

    Returns a callback ``set_label(text)`` that rewrites the spinner button
    label in-place during a blocking prepare step.
    """
    slot = st.empty()

    def set_label(label: str) -> None:
        with slot.container():
            render_preparing_button(label)

    set_label(initial_label)
    return set_label


def ensure_spinner_css() -> None:
    """Inject shared CSS used by in-button 'Preparing...' spinners."""
    st.markdown(
        """
<style>
@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}

.spinner-dark {
    border: 2px solid rgba(255, 255, 255, 0.2);
    border-top: 2px solid #ffffff;
    border-radius: 50%;
    width: 16px;
    height: 16px;
    animation: spin 1s linear infinite;
    display: inline-block;
}
</style>
""",
        unsafe_allow_html=True,
    )
