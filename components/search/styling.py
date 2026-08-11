"""Styling utilities for search components."""

import base64
from pathlib import Path
from typing import Optional

import streamlit as st

# Fixed spacing between logo and heading text (px) so it's consistent in narrow and wide layouts
ICON_MARGIN_RIGHT_PX = 8
ICON_SIZE_PX = 55

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

HEAVY_COLOR = "#89AAE7FF"
LIGHT_COLOR = "#3F3839"


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
    # Map specific emoji icons to PNG logos (stored under public/images/icons)
    icon_image_path = None
    if icon == "🧬":
        icon_image_path = "public/images/icons/heavy.png"
    elif icon == "🔬":
        icon_image_path = "public/images/icons/light.png"
    elif icon == "🔗":
        icon_image_path = "public/images/icons/paired.png"

    if icon_image_path:
        # Single HTML block with fixed icon size and gap so spacing is consistent in any layout
        icon_path = PROJECT_ROOT / icon_image_path
        if icon_path.is_file():
            icon_bytes = icon_path.read_bytes()
            b64 = base64.b64encode(icon_bytes).decode("utf-8")
            data_uri = f"data:image/png;base64,{b64}"
            img_style = (
                f"width:{ICON_SIZE_PX}px; height:{ICON_SIZE_PX}px; "
                f"margin-right:{ICON_MARGIN_RIGHT_PX}px; vertical-align:middle;"
            )
            st.markdown(
                f"<h{level} style='color: {color}; margin-top: {margin_top}; margin-bottom: {margin_bottom};'>"
                f"<img src='{data_uri}' style='{img_style}' />{text}</h{level}>",
                unsafe_allow_html=True,
            )
        else:
            # Fallback if file missing: render without icon
            st.markdown(
                f"<h{level} style='color: {color}; margin-top: {margin_top}; margin-bottom: {margin_bottom};'>"
                f"{text}</h{level}>",
                unsafe_allow_html=True,
            )
    else:
        # Fallback to original emoji/text-based heading
        icon_prefix = f"{icon} " if icon else ""
        st.markdown(
            f"<h{level} style='color: {color}; margin-top: {margin_top}; margin-bottom: {margin_bottom};'>"
            f"{icon_prefix}{text}</h{level}>",
            unsafe_allow_html=True,
        )

