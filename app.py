#!/usr/bin/env python
import streamlit as st
import logging
logger = logging.getLogger(__name__)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def render_sidebar():
    """Render sidebar content (About and License sections)."""
    st.markdown("""
    ### About
    Search the [Observed Antibody Space (OAS)](https://opig.stats.ox.ac.uk/webapps/oas/) 
    database for specific antibody sequences.

    ### How to Use
    Select the the desired database from the dropdown menu, enter the search criteria, and click the "🔍 Search Database" button. The results will be displayed in the main area and can be downloaded as zipped parquet files.

    ### Resources
    - [GitHub Repository](#)
    - [Documentation API](#)
    """)
    
    
    st.markdown("""
    ---
    ### 📄 License & Credits
    **If you use this software, please cite:** Schlegel, de Riz, Riccabona et al. (2025). *XYZ*. [Link](#)
    
    **Data Source Citations:**
    - [OAS Database](https://opig.stats.ox.ac.uk/webapps/oas/)
        - Olsen, T.H., Boyles, F., and Deane C.M. (2021). *Protein Science*. [Link](#)
        - Kovaltsuk, A., Leem, J. et al (2018). *J. Immunol*. [Link](#)

    **ABHunter** - High-performance OAS antibody database search - GNU GPLv3 License
    """)
    return

def main():
    """Main entrypoint - handles navigation between pages."""
    
    # Global page configuration - applies to all pages by default
    st.set_page_config(
        page_title="ABHunter - Antibody Database Search",  # Default title
        page_icon=':dna:',
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            'Get Help': 'https://github.com/VIIC12/antibody_search',
            'Report a bug': 'https://github.com/VIIC12/antibody_search/issues',
            'About': "ABHunter - High-performance OAS antibody database search"
        }
    )
    
    search = st.Page("pages/search.py", title="Database Search", icon=":material/search:", default=True)
    imprint = st.Page("pages/imprint.py", title="Imprint", icon=":material/info:")

    entry_page = st.navigation([search, imprint], position="top")

    # Run the selected page
    entry_page.run()

if __name__ == "__main__":
    main()

