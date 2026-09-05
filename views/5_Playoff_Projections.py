import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from data.espn_client import get_matchups_df, get_manager_map
from analysis.standings import h2h_standings, combined_standings
from analysis.projections import simulate_playoffs
from config import SEASONS, DEFAULT_SEASON, season_config
from display_utils import season_selector, require_data, sidebar_display_prefs, prep_display, chart_label
from branding import page_icon

st.set_page_config(page_title="Playoff Projections", page_icon=page_icon(), layout="wide")
st.title("🏆 Playoff Projections")

season = season_selector(SEASONS, DEFAULT_SEASON)
show_mgr, show_team = sidebar_display_prefs()

@st.cache_data(ttl=300)
def load(season):
    return get_matchups_df(season), get_manager_map(season)

with st.spinner("Loading..."):
    matchups_df, manager_map = load(season)

require_data(matchups_df, season, "matchup data")

cfg = season_config(season)
reg_season_weeks = cfg["reg_season_end"]
reg_df = matchups_df[matchups_df["week"] <= reg_season_weeks]
weeks_played = reg_df["week"].nunique()
weeks_remaining = max(0, reg_season_weeks - weeks_played)

col1, col2, col3 = st.columns(3)
col1.metric("Regular Season Weeks", reg_season_weeks)
col2.metric("Weeks Played", weeks_played)
col3.metric("Weeks Remaining", weeks_remaining)

st.divider()

# team_name → team_id lookup for tables without team_id
tid_by_name = matchups_df[["team_id", "team_name"]].drop_duplicates().set_index("team_name")["team_id"]

tab1, tab2, tab3 = st.tabs(["Playoff Odds", "Score Distribution", "Magic Numbers"])

with tab1:
    st.subheader("Monte Carlo Playoff Simulation")
    st.caption("10,000 simulations of remaining regular season games based on each team's scoring distribution.")

    n_sims = st.sidebar.slider("Simulations", 1000, 50000, 10000, 1000)
    playoff_spots = st.sidebar.slider("Playoff spots", 2, 6, 4)

    if weeks_remaining == 0:
        st.info("Regular season is complete. Showing final playoff picture.")

    with st.spinner("Simulating..."):
        sim_df = simulate_playoffs(
            reg_df, reg_season_weeks=cfg["reg_season_end"],
            playoff_spots=playoff_spots, n_simulations=n_sims
        )

    display = prep_display(sim_df, manager_map, show_mgr, show_team,
                           cols=["team_name", "current_wins", "current_losses", "playoff_pct"],
                           headers=["Team", "Current W", "Current L", "Playoff Odds %"])
    st.dataframe(display, use_container_width=True, hide_index=True)

    sim_df["label"] = chart_label(sim_df, manager_map, show_mgr, show_team)
    colors = ["#2ecc71" if p >= 50 else "#e74c3c" if p < 20 else "#f39c12"
              for p in sim_df["playoff_pct"]]
    fig = go.Figure(go.Bar(
        x=sim_df["label"],
        y=sim_df["playoff_pct"],
        marker_color=colors,
        text=[f"{p}%" for p in sim_df["playoff_pct"]],
        textposition="outside",
    ))
    fig.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="50%")
    fig.update_layout(title="Playoff Probability by Team", xaxis_tickangle=-30,
                      yaxis_title="Playoff Probability %", yaxis_range=[0, 105])
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Scoring Distribution by Team")
    st.caption("Based on scores from games played so far. Used by the simulator.")

    team_params = []
    for team in reg_df["team_name"].unique():
        scores = reg_df[reg_df["team_name"] == team]["score"].values
        tid = tid_by_name.get(team)
        mgr = manager_map.get(tid, "?") if tid is not None else "?"
        if show_mgr and show_team:
            lbl = f"{mgr} — {team}"
        elif show_mgr:
            lbl = mgr
        else:
            lbl = team
        team_params.append({
            "Team": lbl,
            "Mean": round(scores.mean(), 2),
            "Std Dev": round(scores.std(), 2),
            "Min": round(scores.min(), 2),
            "Max": round(scores.max(), 2),
            "Games": len(scores),
        })
    params_df = pd.DataFrame(team_params).sort_values("Mean", ascending=False)
    st.dataframe(params_df, use_container_width=True, hide_index=True)

    fig = px.scatter(params_df, x="Mean", y="Std Dev", text="Team", size="Games",
                     title="Mean Score vs Consistency (lower Std Dev = more consistent)",
                     labels={"Mean": "Average Score", "Std Dev": "Std Deviation (consistency)"})
    fig.update_traces(textposition="top center")
    st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("Magic Numbers")
    st.caption("Wins needed to clinch a playoff spot (approximate).")

    if weeks_remaining == 0:
        st.info("Regular season complete.")
    else:
        if season >= 2025:
            standings = combined_standings(reg_df)
            wins_col = "total_wins"
            losses_col = "total_losses"
            # Each remaining week offers 2 possible combined wins (H2H + median)
            wins_per_week = 2
        else:
            standings = h2h_standings(reg_df)
            wins_col = "wins"
            losses_col = "losses"
            wins_per_week = 1

        cutoff_wins = standings.iloc[playoff_spots][wins_col] if len(standings) > playoff_spots else 0
        standings["magic_number"] = (cutoff_wins + 1 - standings[wins_col]).clip(lower=0)
        standings["games_left"] = weeks_remaining * wins_per_week

        magic_disp = prep_display(standings, manager_map, show_mgr, show_team,
                                  cols=["team_name", wins_col, losses_col, "magic_number", "games_left"],
                                  headers=["Team", "W", "L", "Magic Number", "Wins Left"])
        magic_disp["Clinched"] = standings["magic_number"].values == 0
        st.dataframe(magic_disp, use_container_width=True, hide_index=True)

        standings["max_possible_wins"] = standings[wins_col] + weeks_remaining * wins_per_week
        standings["eliminated"] = standings["max_possible_wins"] < cutoff_wins + 1
        elim = standings[standings["eliminated"]]["team_name"].tolist()
        if elim:
            st.error(f"Eliminated from playoffs: {', '.join(elim)}")
        clinched = standings[standings["magic_number"] == 0]["team_name"].tolist()
        if clinched:
            st.success(f"Playoff spot clinched: {', '.join(clinched)}")
