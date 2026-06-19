"""
We Are How U Mean — Fantasy Football Analytics
Main Streamlit entry point.
"""
import sys
from pathlib import Path

# Make sure ff_app is on the path when run as `streamlit run app.py` from ff_app/
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

st.set_page_config(
    page_title="We Are How U Mean",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏈 We Are How U Mean")
st.subheader("Fantasy Football Analytics Dashboard")

st.markdown("""
Navigate using the sidebar to explore:

| Page | What you'll find |
|---|---|
| **Dashboard** | This week's matchups, standings snapshot, league summary |
| **Standings** | H2H, vs-median, combined, alternate schedule |
| **Scoring** | Weekly trends, scoring distributions, best/worst weeks |
| **Luck Index** | Who's been lucky vs. skilled |
| **Lineup Efficiency** | Optimal vs actual lineups, bench waste |
| **Head to Head** | Any team vs any team, all-time records |
| **Playoff Projections** | Monte Carlo simulations, playoff odds |
| **Draft Review** | Full draft board, pick grades |

---
Use the **Season** selector in the sidebar on any page to switch between 2024 and 2025 seasons.
""")

st.info("Select a page from the sidebar to get started.")
