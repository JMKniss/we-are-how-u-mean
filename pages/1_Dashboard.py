import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from data.espn_client import get_league, get_matchups_df, invalidate_cache
from analysis.standings import h2h_standings, luck_index
from config import SEASONS, DEFAULT_SEASON, season_config

st.set_page_config(page_title="Dashboard", page_icon="🏈", layout="wide")
st.title("🏈 Dashboard")

# --- Sidebar ---
season = st.sidebar.selectbox("Season", SEASONS, index=SEASONS.index(DEFAULT_SEASON))
if st.sidebar.button("🔄 Refresh Data"):
    invalidate_cache(season)
    st.cache_data.clear()
    st.rerun()

# --- Load data ---
@st.cache_data(ttl=300)
def load(season):
    league = get_league(season)
    matchups = get_matchups_df(season)
    return league, matchups

with st.spinner("Loading league data..."):
    league, matchups_df = load(season)

current_week = min(league.current_week, 17)
played_df = matchups_df[matchups_df["week"] <= current_week]

# --- Current week matchups ---
st.subheader(f"Week {current_week} Matchups")
week_df = matchups_df[matchups_df["week"] == current_week].drop_duplicates(subset=["team_id"])

if week_df.empty:
    st.info("No matchup data for the current week yet.")
else:
    # Pair up matchups
    seen = set()
    matchup_rows = []
    for _, row in week_df.iterrows():
        if row["team_id"] in seen or row["opp_id"] in seen:
            continue
        seen.add(row["team_id"])
        seen.add(row["opp_id"])
        opp_row = week_df[week_df["team_id"] == row["opp_id"]]
        opp_score = opp_row["score"].values[0] if not opp_row.empty else row["opp_score"]
        matchup_rows.append({
            "Home": row["team_name"],
            "Home Score": f"{row['score']:.2f}",
            "Away": row["opp_name"],
            "Away Score": f"{opp_score:.2f}",
            "Leader": row["team_name"] if row["score"] > opp_score else row["opp_name"],
        })
    st.dataframe(pd.DataFrame(matchup_rows), use_container_width=True, hide_index=True)

st.divider()

# --- Quick stats row ---
col1, col2, col3 = st.columns(3)
weeks_played = played_df["week"].nunique()
avg_score = played_df["score"].mean()
high_score = played_df.loc[played_df["score"].idxmax()]

col1.metric("Weeks Played", weeks_played)
col2.metric("League Avg Score", f"{avg_score:.1f}")
col3.metric("Season High", f"{high_score['score']:.2f}", delta=high_score["team_name"])

st.divider()

# --- Standings snapshot ---
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Current Standings")
    standings = h2h_standings(played_df)[["team_name", "wins", "losses", "points_for", "avg_score"]]
    standings.columns = ["Team", "W", "L", "PF", "Avg"]
    standings["PF"] = standings["PF"].round(1)
    standings["Avg"] = standings["Avg"].round(1)
    st.dataframe(standings, use_container_width=True)

with col_right:
    st.subheader("Luck Index")
    luck = luck_index(played_df)[["team_name", "actual_wins", "expected_wins", "luck_score"]]
    luck.columns = ["Team", "Actual W", "Expected W", "Luck Score"]
    luck["Expected W"] = luck["Expected W"].round(1)
    luck["Luck Score"] = luck["Luck Score"].round(2)
    st.dataframe(luck, use_container_width=True)

st.divider()

# --- Weekly scoring chart ---
st.subheader("Weekly Scoring — All Teams")
pivot = played_df.pivot_table(index="team_name", columns="week", values="score")

fig = go.Figure()
for team in pivot.index:
    fig.add_trace(go.Scatter(
        x=[f"W{int(w)}" for w in pivot.columns],
        y=pivot.loc[team].values,
        mode="lines+markers",
        name=team,
        hovertemplate="%{x}: %{y:.1f} pts<extra>" + team + "</extra>",
    ))

weekly_median = played_df.groupby("week")["score"].median()
fig.add_trace(go.Scatter(
    x=[f"W{int(w)}" for w in weekly_median.index],
    y=weekly_median.values,
    mode="lines",
    name="League Median",
    line=dict(dash="dash", color="gray", width=2),
))

fig.update_layout(
    height=450,
    xaxis_title="Week",
    yaxis_title="Points",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
)
st.plotly_chart(fig, use_container_width=True)
