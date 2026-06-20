"""
We Are How U Mean — Fantasy Football Analytics
Main Streamlit entry point.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

st.set_page_config(
    page_title="We Are How U Mean",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏈 We Are How U Mean")
st.subheader("Fantasy Football Analytics — 2016 to present")

st.markdown("""
Navigate using the sidebar to explore:

| Page | What you'll find |
|---|---|
| **Dashboard** | Current week matchups, standings snapshot, weekly scoring trends |
| **Standings** | H2H, vs-median, combined, strength of schedule, luck index, alternate schedule |
| **Scoring** | Weekly trends, score distributions, best/worst scores, head-to-head records |
| **Lineup Efficiency** | Optimal vs actual lineups, bench waste, top players, projection accuracy |
| **Playoff Projections** | Monte Carlo playoff odds, magic numbers |
| **Playoffs** | Bracket results with per-week and cumulative round scores |
| **Draft Review** | Full draft board, team draft summaries, best value picks and busts |
| **Data Validation** | Verify our calculated scores match ESPN's published totals |

---
Use the **Season** selector in the sidebar on any page to switch between seasons (2016–2025).
""")

st.info("Select a page from the sidebar to get started.")
