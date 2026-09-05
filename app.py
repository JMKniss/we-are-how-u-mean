"""
We Are How U Mean — Fantasy Football Analytics
Main Streamlit entry point.

Navigation is declared here with st.navigation rather than left to Streamlit's
pages/ auto-discovery. Auto-discovery always lists the entry script itself as
a page, so the sidebar carried an "app" tab above Dashboard that existed only
to explain the other tabs. Declaring the pages drops that tab and lets
Dashboard be what the app opens on.

Pages still live in pages/ and still set their own page config; that file
layout is unchanged, only how they are listed.
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

# url_path is set explicitly so existing links keep working. Left to itself,
# st.Page would name each route after its file and turn /Dashboard into
# /1_Dashboard. The default page is served at / and takes no url_path.
PAGES = [
    st.Page("pages/1_Dashboard.py", title="Dashboard", icon="🏈", default=True),
    st.Page("pages/2_Standings.py", title="Standings", icon="📊",
            url_path="Standings"),
    st.Page("pages/3_Scoring.py", title="Scoring", icon="📈",
            url_path="Scoring"),
    st.Page("pages/4_Lineup_Efficiency.py", title="Lineup Efficiency", icon="🎯",
            url_path="Lineup_Efficiency"),
    st.Page("pages/5_Playoff_Projections.py", title="Playoff Projections", icon="🏆",
            url_path="Playoff_Projections"),
    st.Page("pages/6_Playoffs.py", title="Playoffs", icon="🏆",
            url_path="Playoffs"),
    st.Page("pages/7_Draft_Review.py", title="Draft Review", icon="📋",
            url_path="Draft_Review"),
    st.Page("pages/8_Data_Validation.py", title="Data Validation", icon="🔧",
            url_path="Data_Validation"),
    st.Page("pages/9_All_Time.py", title="All-Time Records", icon="📜",
            url_path="All_Time"),
]

st.navigation(PAGES).run()
