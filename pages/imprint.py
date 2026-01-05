import streamlit as st
from app import render_sidebar

# Override page title (inherits other settings from app.py)
st.set_page_config(page_title="ABHunter - Imprint")

# Main content
st.markdown("# :blue[📄 Imprint]")
st.markdown("---")

st.markdown("""
### Legal Information

**Responsible for Content:**  
Institute for Drug Discovery, Faculty of Medicine, Leipzig University  
Liebigstraße 19  
04103 Leipzig, Germany

**Contact:**  
Email: [abhunter@medizin.uni-leipzig.de](mailto:abhunter@medizin.uni-leipzig.de)  
Phone: On Request



### Disclaimer

The information provided on this application is for general informational purposes only. While we strive to keep the information up to date and correct, we make no representations or warranties of any kind, express or implied, about the completeness, accuracy, reliability, suitability, or availability of the information.

### Data Sources

This application uses data from the Observed Antibody Space (OAS) database. Please refer to the sidebar for proper citations when using this tool in your research.

### Privacy

This application does not collect or store personal information. All searches are performed locally and are not logged or transmitted to external servers.
""")