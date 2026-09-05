"""
We Are How U Mean — Fantasy Football Analytics
Main Streamlit entry point.

Navigation is declared here with st.navigation rather than left to Streamlit's
auto-discovery. Auto-discovery always lists the entry script itself as a page,
so the sidebar carried an "app" tab above Dashboard that existed only to
explain the other tabs. Declaring the pages drops that tab and lets Dashboard
be what the app opens on.

The page files live in views/ rather than pages/, and the name is load-bearing.
Streamlit sets uses_pages_directory from nothing more than whether a directory
called "pages" sits next to the entry script, and if one does it routes direct
URLs the old way - so opening /Draft_Review straight from a link brought back
the very nav this file exists to replace, while clicking through to the same
page in the app showed the right one. Renaming the directory is what actually
removes the old behaviour; st.navigation alone only covers the paths that
happen to go through it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

# Imported after sys.path is set above, so it resolves from the app root.
from auth import require_password

st.set_page_config(
    page_title="We Are How U Mean",
    page_icon="🏈",
    layout="wide",
    # "auto", not "expanded": Streamlit keeps the sidebar open on a desktop
    # and collapses it on a narrow screen. Forcing it open meant a phone landed
    # on a full screen of navigation covering the page, on every single load.
    initial_sidebar_state="auto",
)

# Runs before any page. Does nothing unless APP_PASSWORD is set, so whether
# the site is public is a Render setting rather than a code change.
require_password()

# url_path is set explicitly so existing links keep working. Left to itself,
# st.Page would name each route after its file and turn /Dashboard into
# /1_Dashboard. The default page is served at / and takes no url_path.
PAGES = [
    st.Page("views/1_Dashboard.py", title="Dashboard", icon="🏈", default=True),
    st.Page("views/2_Standings.py", title="Standings", icon="📊",
            url_path="Standings"),
    st.Page("views/3_Scoring.py", title="Scoring", icon="📈",
            url_path="Scoring"),
    st.Page("views/4_Lineup_Efficiency.py", title="Lineup Efficiency", icon="🎯",
            url_path="Lineup_Efficiency"),
    st.Page("views/5_Playoff_Projections.py", title="Playoff Projections", icon="🏆",
            url_path="Playoff_Projections"),
    st.Page("views/6_Playoffs.py", title="Playoffs", icon="🏆",
            url_path="Playoffs"),
    st.Page("views/7_Draft_Review.py", title="Draft Review", icon="📋",
            url_path="Draft_Review"),
    st.Page("views/8_Data_Validation.py", title="Data Validation", icon="🔧",
            url_path="Data_Validation"),
    st.Page("views/9_All_Time.py", title="All-Time Records", icon="📜",
            url_path="All_Time"),
]

st.navigation(PAGES).run()
