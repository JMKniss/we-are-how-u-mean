import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from data.espn_client import get_matchups_df, get_manager_map, invalidate_cache
from analysis.standings import (
    h2h_standings, median_standings, combined_standings,
    strength_of_schedule, luck_index, alternate_schedule_standings
)
from config import SEASONS, DEFAULT_SEASON, season_config
from display_utils import sidebar_display_prefs, prep_display, chart_label

st.set_page_config(page_title="Standings", page_icon="📊", layout="wide")
st.title("📊 Standings")

if "selected_season" not in st.session_state:
    st.session_state["selected_season"] = DEFAULT_SEASON
season = st.sidebar.selectbox(
    "Season", SEASONS,
    index=SEASONS.index(st.session_state["selected_season"])
)
st.session_state["selected_season"] = season
if st.sidebar.button("🔄 Refresh Data"):
    invalidate_cache(season)
    st.cache_data.clear()
    st.rerun()
show_mgr, show_team = sidebar_display_prefs()

@st.cache_data(ttl=300)
def load(season):
    return get_matchups_df(season), get_manager_map(season)

with st.spinner("Loading..."):
    matchups_df, manager_map = load(season)

cfg = season_config(season)
matchups_df = matchups_df[matchups_df["week"] <= cfg["reg_season_end"]].copy()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "H2H", "vs Median", "Combined", "Strength of Schedule", "Luck Index", "Alternate Schedule"
])

with tab1:
    st.subheader("Head-to-Head Standings")
    df = h2h_standings(matchups_df)
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "wins", "losses", "ties", "points_for", "points_against", "avg_score", "win_pct"],
                           headers=["Team", "W", "L", "T", "PF", "PA", "Avg Score", "Win%"])
    display["PF"] = display["PF"].round(1)
    display["PA"] = display["PA"].round(1)
    display["Avg Score"] = display["Avg Score"].round(1)
    display["Win%"] = display["Win%"].round(3)
    st.dataframe(display, use_container_width=True, hide_index=True)

    df["label"] = chart_label(df, manager_map, show_mgr, show_team)
    fig = px.bar(df, x="label", y=["wins", "losses"], barmode="group",
                 labels={"value": "Games", "label": "", "variable": ""},
                 title="Wins vs Losses", color_discrete_map={"wins": "#2ecc71", "losses": "#e74c3c"})
    fig.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Vs-Median Standings")
    st.caption("Each week, beating the league median score counts as an additional win.")
    df = median_standings(matchups_df)
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "median_wins", "median_losses"],
                           headers=["Team", "Median Wins", "Median Losses"])
    st.dataframe(display, use_container_width=True, hide_index=True)

    df["label"] = chart_label(df, manager_map, show_mgr, show_team)
    fig = px.bar(df, x="label", y="median_wins",
                 title="Median Wins per Team",
                 labels={"label": "", "median_wins": "Wins vs Median"},
                 color="median_wins", color_continuous_scale="Greens")
    fig.update_layout(xaxis_tickangle=-30, coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("Combined Standings (H2H + vs Median)")
    st.caption("Two games per week: one H2H matchup win/loss, one vs-median win/loss.")
    df = combined_standings(matchups_df)
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "wins", "median_wins", "total_wins", "total_losses", "total_win_pct", "points_for"],
                           headers=["Team", "H2H W", "Median W", "Total W", "Total L", "Win%", "PF"])
    display["Win%"] = display["Win%"].round(3)
    display["PF"] = display["PF"].round(1)
    st.dataframe(display, use_container_width=True, hide_index=True)

with tab4:
    st.subheader("Strength of Schedule")
    st.caption("Average score of opponents faced. Higher = harder schedule.")
    df = strength_of_schedule(matchups_df)
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "avg_opp_score", "total_opp_score", "games"],
                           headers=["Team", "Avg Opp Score", "Total Opp Score", "Games Played"])
    display["Avg Opp Score"] = display["Avg Opp Score"].round(2)
    display["Total Opp Score"] = display["Total Opp Score"].round(1)
    st.dataframe(display, use_container_width=True, hide_index=True)

    df["label"] = chart_label(df, manager_map, show_mgr, show_team)
    fig = px.bar(df, x="label", y="avg_opp_score",
                 title="Average Opponent Score Faced",
                 labels={"label": "", "avg_opp_score": "Avg Opp Score"},
                 color="avg_opp_score", color_continuous_scale="RdYlGn_r")
    fig.update_layout(xaxis_tickangle=-30, coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

with tab5:
    st.subheader("Luck Index")
    st.caption("Luck = Actual Wins − Expected Wins (based on weekly score percentile). Positive = lucky, negative = unlucky.")
    df = luck_index(matchups_df)
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "actual_wins", "expected_wins", "luck_score", "points_for"],
                           headers=["Team", "Actual W", "Expected W", "Luck Score", "PF"])
    display["Expected W"] = display["Expected W"].round(1)
    display["Luck Score"] = display["Luck Score"].round(2)
    display["PF"] = display["PF"].round(1)
    st.dataframe(display, use_container_width=True, hide_index=True)

    df["label"] = chart_label(df, manager_map, show_mgr, show_team)
    fig = px.bar(df.sort_values("luck_score"), x="luck_score", y="label",
                 orientation="h",
                 title="Luck Score by Team",
                 labels={"luck_score": "Luck Score", "label": ""},
                 color="luck_score", color_continuous_scale="RdYlGn")
    fig.add_vline(x=0, line_dash="dash", line_color="gray")
    fig.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

with tab6:
    st.subheader("Alternate Schedule Standings")
    st.caption("If each team played every other team every week — who would have the most wins?")
    with st.spinner("Computing alternate schedule (may take a moment)..."):
        df = alternate_schedule_standings(matchups_df)
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "alt_wins", "alt_games", "alt_win_pct"],
                           headers=["Team", "Alt Wins", "Games", "Win%"])
    display["Win%"] = display["Win%"].round(3)
    st.dataframe(display, use_container_width=True, hide_index=True)

    df["label"] = chart_label(df, manager_map, show_mgr, show_team)
    h2h = h2h_standings(matchups_df).set_index("team_name")["wins"]
    df["actual_wins"] = df["team_name"].map(h2h)
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Actual Wins", x=df["label"], y=df["actual_wins"], marker_color="#3498db"))
    n_teams = matchups_df["team_id"].nunique()
    weeks_played = matchups_df["week"].nunique()
    scale = weeks_played / (n_teams - 1) if n_teams > 1 else 1
    fig.add_trace(go.Bar(name="Alt Wins (scaled)", x=df["label"],
                         y=(df["alt_wins"] * scale).round(1), marker_color="#e67e22"))
    fig.update_layout(barmode="group", xaxis_tickangle=-30,
                      title="Actual vs Alternate Schedule Wins (alt wins scaled to same game count)")
    st.plotly_chart(fig, use_container_width=True)
