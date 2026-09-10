# ABHunter - Real-Time Exploration of the Billion-Scale Human Repertoire for Precursor Frequency Analysis and Rational Antibody Design

In this work, we developed ABHunter, a framework designed for the exploration and filtering of the 1.86-billion-sequence healthy-human subset of the [Observed Antibody Space (OAS)](https://opig.stats.ox.ac.uk/webapps/oas/) in a matter of seconds. Our tool is accessible through any standard web browser [abhunter.iwe-lab.de](abhunter.iwe-lab.de) and supports deeper, custom analysis through local installation that was previously impractical, making the datasets curated by Olsen et al. and Kovaltsuk et al. broadly accessible.

### For local execution w/o docker

#### Prerequisites
```bash
# Only once for installation:
# Clone the repository
git clone https://github.com/VIIC12/antibody_search.git --branch publication
cd antibody_search

# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements-server.txt
```

#### Try the app with the minimal example dataset (no OAS download)

A small real OAS subset (~100 KB, ~125 sequences) is shipped under `examples/minimal/` so you can explore Heavy, Light, and Paired search before downloading the full healthy-human OAS.

```bash
export ABHUNTER_DB_PATH=./examples/minimal
python -m streamlit run app.py
# Open the "Local URL" link in your browser
```

In the UI, select the `Demo` databases under Heavy / Light / Paired. The built-in Example Search buttons return hits on this subset.

To regenerate the example tree from a local full OAS conversion (maintainers only):

```bash
python scripts/create_example_data.py --source ./data
```

#### Download the full OAS (healthy humans)

```bash
# Download and convert OAS files to Parquet format (large; needs disk space)
python scripts/update_from_oas.py --healthy_humans --download-and-convert

# Point the app at the full dataset (default layout under ./data)
unset ABHUNTER_DB_PATH
# or: export ABHUNTER_DB_PATH=./data
```

#### Run the web interface
```bash
python -m streamlit run app.py
# Open the "Local URL" link in your browser
```

# Overview

## Architecture
```
antibody_search/               # Self-contained antibody_search directory
├── app.py                     # Streamlit web interface (main entry)
├── pages/
│   ├── search.py              # Search page
│   └── imprint.py             # Imprint page
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container configuration
│
├── src/
│   └── search_engine.py       # DuckDB query engine
│
├── components/
│   └── search/                # Search components
│       ├── ... *.py           # Search components
│
├── scripts/
│   ├── convert_to_parquet.py  # CSV.gz → Parquet converter
│   └── create_example_data.py # Rebuild examples/minimal from local OAS
│
├── examples/
│   └── minimal/               # Tiny real OAS subset for local try-out
│       ├── Heavy/Demo/
│       ├── Light/Demo/
│       └── Paired/Demo/
│
├── data/                      # Full OAS conversion (not in git; large)
│   ├── Heavy/                 # Partitioned by isotype (e.g. IGHM/)
│   ├── Light/
│   ├── Paired/
│   └── Inferred/              # Optional pairing overlays
│
├── tests/                     # Validation tests
│
└── .venv/                     # Virtual environment (gitignored)
```
## Customization
```bash
# custom database path (default: project data/)
export ABHUNTER_DB_PATH=./data
# try-out without full OAS:
# export ABHUNTER_DB_PATH=./examples/minimal

# custom IgBLAST directory (default: project igblast/)
export ABHUNTER_IGBLAST_PATH=./igblast
```

## License
ABHunter is a free open-source software licensed under the MIT License. The ABHunter server components are a free open-source software licensed under the GNU GPLv3 License.

## Citation
If you use this repository code or data in your work, please cite the relavant work as below:
```bibtex
@unpublished{Schlegel2026,
    title = {"Real-Time Exploration of the Billion-Scale Human Repertoire for Precursor Frequency Analysis and Rational Antibody Design},
    author = {Tom U. Schlegel and Jannis de Riz and Jakob R. Riccabona and Franz Dietzmeyer and and Julia Koehler and Jens Meiler and Clara T. Schoeder and Torben Schiffner},
    year = {2026},
   doi = {to appear},
   journal = {to appear},
   pages = {to appear},
   volume = {to appear},
   url = {to appear},
   year = {2026},
   publisher = {to appear},
   note    = {under submission}
}

@article{Olsen2022,
   title = {Observed Antibody Space: A diverse database of cleaned, annotated, and translated unpaired and paired antibody sequences},
   author = {Tobias H. Olsen and Fergus Boyles and Charlotte M. Deane},
   doi = {10.1002/pro.4205},
   journal = {Protein Science},
   pages = {141-146},
   volume = {31},
   url = {https://doi.org/10.1002/pro.4205},
   year = {2022},
   publisher = {John Wiley \& Sons, Ltd}
}

@article{Kovaltsuk2018,
   title = {Observed Antibody Space: A Resource for Data Mining Next-Generation Sequencing of Antibody Repertoires},
   author = {Aleksandr Kovaltsuk and Jinwoo Leem and Sebastian Kelm and James Snowden and Charlotte M Deane and Konrad Krawczyk},
   doi = {10.4049/jimmunol.1800708},
   journal = {The Journal of Immunology},
   pages = {2502-2509},
   volume = {201},
   url = {https://doi.org/10.4049/jimmunol.1800708},
   year = {2018},
    publisher = {Oxford Academic}
}
```

## Acknowledgments
We thank the OAS authors for curating and making their dataset available to the community. Additionally, we would like to thank Xin Yu for his [detailed instructions](https://github.com/xinyu-dev/igblast) on how to set up the stand-alone IgBLAST application igblastn.