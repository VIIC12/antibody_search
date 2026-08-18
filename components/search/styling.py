"""Styling utilities for search components."""

import streamlit as st

HEAVY_COLOR = "#4C6085"
LIGHT_COLOR = "#CB4154"
PAIRED_COLOR = "#FFFFFF"
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
