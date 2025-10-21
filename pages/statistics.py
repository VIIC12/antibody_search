import streamlit as st
from app import render_sidebar

# Override page title (inherits other settings from app.py)
st.set_page_config(page_title="ABHunter - Statistics")

# Sidebar content
with st.sidebar:
    render_sidebar()

# Main content
st.markdown("# :blue[📄 Statistics]")
st.markdown("---")

st.markdown("""
### Statistics  
PLACEHOLDER

#TODO Pictures @public/images
""")
