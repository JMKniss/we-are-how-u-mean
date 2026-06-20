import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from data.espn_client import get_league, get_matchups_df, get_manager_map, invalidate_cache
from analysis.standings import h2h_standings, luck_index
from config import SEASONS, DEFAULT_SEASON, season_config
from display_utils import sidebar_display_prefs, prep_display, chart_label

st.set_page_config(page_title="Dashboard", page_icon="🏈", layout="wide")
st.title("🏈 Dashboard")

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
    league = get_league(season)
    matchups = get_matchups_df(season)
    mgr_map = get_manager_map(season)
    return league, matchups, mgr_map

with st.spinner("Loading league data..."):
    league, matchups_df, manager_map = load(season)

cfg = season_config(season)
current_week = min(league.current_week, cfg["total_weeks"])
played_df = matchups_df[matchups_df["week"] <= current_week]
reg_df = played_df[played_df["week"] <= cfg["reg_season_end"]]

# ── Current week matchups ─────────────────────────────────────────────────────
st.subheader(f"Week {current_week} Matchups")
week_df = matchups_df[matchups_df["week"] == current_week].drop_duplicates(subset=["team_id"])

if week_df.empty:
    st.info("No matchup data for the current week yet.")
else:
    seen = set()
    matchup_rows = []
    for _, row in week_df.iterrows():
        if row["team_id"] in seen or row["opp_id"] in seen:
            continue
        seen.add(row["team_id"])
        seen.add(row["opp_id"])
        opp_row = week_df[week_df["team_id"] == row["opp_id"]]
        opp_score = opp_row["score"].values[0] if not opp_row.empty else row["opp_score"]

        home_mgr = manager_map.get(row["team_id"], "?")
        away_mgr = manager_map.get(row["opp_id"], "?")

        def name(mgr, team):
            if show_mgr and show_team:
                return f"{mgr} — {team}"
            return mgr if show_mgr else team

        winner_id = row["team_id"] if row["score"] > opp_score else row["opp_id"]
        winner_mgr = manager_map.get(winner_id, "?")
        winner_team = row["team_name"] if winner_id == row["team_id"] else row["opp_name"]

        matchup_rows.append({
            "Home": name(home_mgr, row["team_name"]),
            "Home Score": f"{row['score']:.2f}",
            "Away": name(away_mgr, row["opp_name"]),
            "Away Score": f"{opp_score:.2f}",
            "Leader": name(winner_mgr, winner_team),
        })
    st.dataframe(pd.DataFrame(matchup_rows), use_container_width=True, hide_index=True)

st.divider()

# ── Quick stats ───────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
weeks_played = reg_df["week"].nunique()
avg_score = reg_df["score"].mean() if not reg_df.empty else 0
high_score = reg_df.loc[reg_df["score"].idxmax()] if not reg_df.empty else None

col1.metric("Reg Season Weeks Played", weeks_played)
col2.metric("Reg Season Avg Score", f"{avg_score:.1f}")
if high_score is not None:
    high_mgr = manager_map.get(high_score["team_id"], "?")
    high_label = f"{high_mgr} — {high_score['team_name']}" if show_mgr and show_team else (high_mgr if show_mgr else high_score["team_name"])
    col3.metric("Reg Season High", f"{high_score['score']:.2f}", delta=high_label)
else:
    col3.metric("Reg Season High", "—")

st.divider()

# ── Standings snapshot ────────────────────────────────────────────────────────
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Regular Season Standings")
    df = h2h_standings(reg_df)
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "wins", "losses", "points_for", "avg_score"],
                           headers=["Team", "W", "L", "PF", "Avg"])
    display["PF"] = display["PF"].round(1)
    display["Avg"] = display["Avg"].round(1)
    st.dataframe(display, use_container_width=True, hide_index=True)

with col_right:
    st.subheader("Luck Index")
    df = luck_index(reg_df)
    display = prep_display(df, manager_map, show_mgr, show_team,
                           cols=["team_name", "actual_wins", "expected_wins", "luck_score"],
                           headers=["Team", "Actual W", "Expected W", "Luck Score"])
    display["Expected W"] = display["Expected W"].round(1)
    display["Luck Score"] = display["Luck Score"].round(2)
    st.dataframe(display, use_container_width=True, hide_index=True)

st.divider()

# ── Weekly scoring chart ──────────────────────────────────────────────────────
st.subheader("Weekly Scoring — All Teams")

# Build label per team for the legend
team_labels = {}
for tid, mgr in manager_map.items():
    rows = played_df[played_df["team_id"] == tid]
    if rows.empty:
        continue
    tname = rows["team_name"].iloc[0]
    if show_mgr and show_team:
        team_labels[tname] = f"{mgr} — {tname}"
    elif show_mgr:
        team_labels[tname] = mgr
    else:
        team_labels[tname] = tname

pivot = played_df.pivot_table(index="team_name", columns="week", values="score")

fig = go.Figure()
for team in pivot.index:
    label = team_labels.get(team, team)
    fig.add_trace(go.Scatter(
        x=[f"W{int(w)}" for w in pivot.columns],
        y=pivot.loc[team].values,
        mode="lines+markers",
        name=label,
        hovertemplate="%{x}: %{y:.1f} pts<extra>" + label + "</extra>",
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
