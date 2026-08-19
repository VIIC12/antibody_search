#!/usr/bin/env python
from pathlib import Path
import sys

# Load .env from project root so ABHUNTER_DOWNLOAD_DIR, ABHUNTER_TMP_DIR, ABHUNTER_DB_PATH, etc. are set when running locally
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

import streamlit as st
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Set specific modules to DEBUG level for troubleshooting
logging.getLogger("src.search_engine").setLevel(logging.DEBUG)
logging.getLogger("search_engine").setLevel(logging.DEBUG)  # In case it's imported without src. prefix
logging.getLogger("components.search.download_utils").setLevel(logging.DEBUG)
logging.getLogger("components.search.search_execution").setLevel(logging.DEBUG)

sys.path.insert(0, str(Path(__file__).parent / "src"))

def render_sidebar():
    """Render sidebar content (About and License sections)."""
    st.logo(
        image="./static/logo.gif",
        size="large",
        link=None,
        icon_image=None,
    )

    st.markdown("""
    ## **ABHunter** - Real time OAS antibody database search
    
    ### :material/tooltip: About
    ABHunter enables you to search the [Observed Antibody Space (OAS)](https://opig.stats.ox.ac.uk/webapps/oas/) database in seconds and analyze how frequently specific V/D/J genes, CDR lengths, and motifs appear in human, non-vaccinated, healthy patients. For unpaired heavy or light chain data, ABHunter provides inferred V/J gene pairing information and statistical frequencies based on paired antibody data from the database.

    ---
    ### :material/lab_profile: License & Credits
    **If you use this software, please cite:** Schlegel et al. (2026). *Under submission.*
    
    **Data Source Citations:**
    - [OAS Database](https://opig.stats.ox.ac.uk/webapps/oas/)
        - Olsen, T.H., Boyles, F., and Deane C.M. (2021). *Protein Science*. [Link](https://doi.org/10.1002/pro.4205)
        - Kovaltsuk, A., Leem, J. et al (2018). *J. Immunol*. [Link](https://doi.org/10.4049/jimmunol.1800708)

    This software is licensed under the GNU GPLv3 License.
    
    [ABHunter GitHub Repository](https://github.com/VIIC12/antibody_search#)
    """)
    
    # Stick inside the sidebar near the bottom, without overflowing when the sidebar is resized
    st.markdown(
        f"""
        ---
        <div style='bottom: 0px; opacity: 0.85; font-size: 0.9rem;'>
            Made in Leipzig, Germany <br/> Institute for Drug Discovery, Leipzig University
        </div>
        """,
        unsafe_allow_html=True
    )
    return
    
def main():
    """Main entrypoint - handles navigation between pages."""
    
    # Global page configuration - applies to all pages by default
    st.set_page_config(
        page_title="ABHunter - Antibody Database Search",
        page_icon=':material/vaccines:',
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            'Get Help': 'https://github.com/VIIC12/antibody_search',
            'Report a bug': 'https://github.com/VIIC12/antibody_search/issues',
            'About': "**ABHunter** is a high-performance antibody database search tool that lets you search the Observed Antibody Space (OAS) database in seconds and analyze how frequently specific V/D/J genes, CDR lengths, and motifs appear in human, non-vaccinated, healthy patients. For unpaired heavy or light chain data, ABHunter provides inferred V/J gene pairing information and statistical frequencies based on paired antibody data from the database. Please refer to the sidebar for proper citations when using this tool in your research. Thank you for using ABHunter!"
        }
    )

    st.markdown(
        """
        <style>
        div.block-container {
            padding-top: 4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        render_sidebar()

    search = st.Page("pages/search.py", title="Database Search", icon=":material/search:", default=True)
    igblast = st.Page("pages/igblast.py", title="IgBLAST", icon=":material/genetics:")
    statistics = st.Page("pages/statistics.py", title="Statistics", icon=":material/bar_chart:")
    imprint = st.Page("pages/imprint.py", title="Imprint", icon=":material/info:")

    entry_page = st.navigation(
        [search, igblast, statistics, imprint],
        position="top",
    )

    # Run the selected page
    entry_page.run()

if __name__ == "__main__":
    main()

