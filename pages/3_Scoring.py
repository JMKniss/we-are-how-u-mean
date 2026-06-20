import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from data.espn_client import get_matchups_df, get_manager_map, invalidate_cache
from config import SEASONS, DEFAULT_SEASON
from display_utils import sidebar_display_prefs, prep_display, chart_label

st.set_page_config(page_title="Scoring", page_icon="📈", layout="wide")
st.title("📈 Scoring Analysis")

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
    df, manager_map = load(season)

# team_name → display label helper
tid_by_name = df[["team_id", "team_name"]].drop_duplicates().set_index("team_name")["team_id"]
def label_for(tname: str) -> str:
    tid = tid_by_name.get(tname)
    mgr = manager_map.get(tid, "?") if tid is not None else "?"
    if show_mgr and show_team:
        return f"{mgr} — {tname}"
    return mgr if show_mgr else tname

teams = sorted(df["team_name"].unique())

tab1, tab2, tab3, tab4 = st.tabs(["Weekly Trends", "Score Distributions", "Best & Worst", "Head-to-Head Scores"])

with tab1:
    st.subheader("Weekly Scoring Trends")
    selected = st.multiselect("Filter teams", teams, default=teams)
    filtered = df[df["team_name"].isin(selected)]

    fig = go.Figure()
    for team in selected:
        tdf = filtered[filtered["team_name"] == team].sort_values("week")
        lbl = label_for(team)
        fig.add_trace(go.Scatter(
            x=tdf["week"], y=tdf["score"], mode="lines+markers",
            name=lbl, hovertemplate="Week %{x}: %{y:.2f} pts<extra>" + lbl + "</extra>",
        ))
    weekly_med = df.groupby("week")["score"].median()
    fig.add_trace(go.Scatter(
        x=weekly_med.index, y=weekly_med.values, mode="lines",
        name="League Median", line=dict(dash="dash", color="gray", width=2),
    ))
    weekly_avg = df.groupby("week")["score"].mean()
    fig.add_trace(go.Scatter(
        x=weekly_avg.index, y=weekly_avg.values, mode="lines",
        name="League Average", line=dict(dash="dot", color="lightgray", width=2),
    ))
    fig.update_layout(height=480, xaxis_title="Week", yaxis_title="Points",
                      hovermode="x unified", xaxis=dict(dtick=1))
    st.plotly_chart(fig, use_container_width=True)

    weekly_stats = df.groupby("week")["score"].agg(["min", "max", "mean", "median"]).reset_index()
    fig2 = go.Figure([
        go.Scatter(x=weekly_stats["week"], y=weekly_stats["max"], mode="lines",
                   line=dict(color="rgba(0,150,0,0.3)"), name="High", fill=None),
        go.Scatter(x=weekly_stats["week"], y=weekly_stats["min"], mode="lines",
                   line=dict(color="rgba(150,0,0,0.3)"), name="Low",
                   fill="tonexty", fillcolor="rgba(200,200,200,0.2)"),
        go.Scatter(x=weekly_stats["week"], y=weekly_stats["mean"], mode="lines",
                   line=dict(color="blue", width=2), name="Avg"),
    ])
    fig2.update_layout(title="Weekly Score Range (band = low to high)", height=300,
                       xaxis_title="Week", yaxis_title="Points", xaxis=dict(dtick=1))
    st.plotly_chart(fig2, use_container_width=True)

with tab2:
    st.subheader("Score Distributions")
    col1, col2 = st.columns(2)

    with col1:
        df_box = df.copy()
        df_box["label"] = chart_label(df_box, manager_map, show_mgr, show_team)
        fig = px.box(df_box, x="label", y="score", color="label",
                     title="Score Distribution by Team",
                     labels={"label": "Team", "score": "Points"})
        fig.update_layout(xaxis_tickangle=-30, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = px.histogram(df, x="score", nbins=30, title="Overall Score Distribution",
                           labels={"score": "Points", "count": "Frequency"})
        mu, sigma = df["score"].mean(), df["score"].std()
        x_range = np.linspace(df["score"].min(), df["score"].max(), 100)
        from scipy.stats import norm
        y_norm = norm.pdf(x_range, mu, sigma) * len(df) * (df["score"].max() - df["score"].min()) / 30
        fig.add_trace(go.Scatter(x=x_range, y=y_norm, mode="lines", name="Normal fit",
                                 line=dict(color="red", width=2)))
        st.plotly_chart(fig, use_container_width=True)

    # Per-team stats table — group by team_id too so prep_display works
    team_stats = df.groupby(["team_id", "team_name"])["score"].agg(
        Mean="mean", Median="median", Std="std", Min="min", Max="max", Weeks="count"
    ).round(2).reset_index()
    display = prep_display(team_stats, manager_map, show_mgr, show_team,
                           cols=["team_name", "Mean", "Median", "Std", "Min", "Max", "Weeks"],
                           headers=["Team", "Mean", "Median", "Std Dev", "Min", "Max", "Weeks"])
    st.dataframe(display, use_container_width=True, hide_index=True)

with tab3:
    st.subheader("Season Records")

    from config import season_config
    cfg = season_config(season)

    # Tag each row so users know whether a score came from a regular season or playoff week
    def week_label(row):
        if row["week"] > cfg["reg_season_end"]:
            return f"Wk {row['week']} (playoffs)"
        return f"Wk {row['week']}"

    df_tagged = df.copy()
    df_tagged["week_label"] = df_tagged.apply(week_label, axis=1)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Top 10 Individual Scores**")
        top_scores = df_tagged.nlargest(10, "score")[["team_id", "week_label", "team_name", "score", "opp_name", "opp_score", "outcome"]].copy()
        top_scores[["score", "opp_score"]] = top_scores[["score", "opp_score"]].round(2)
        disp = prep_display(top_scores, manager_map, show_mgr, show_team,
                            cols=["team_name", "week_label", "score", "opp_name", "opp_score", "outcome"],
                            headers=["Team", "Week", "Score", "Opponent", "Opp Score", "Result"])
        st.dataframe(disp, use_container_width=True, hide_index=True)

    with col2:
        st.markdown("**10 Lowest Individual Scores**")
        low_scores = df_tagged.nsmallest(10, "score")[["team_id", "week_label", "team_name", "score", "opp_name", "opp_score", "outcome"]].copy()
        low_scores[["score", "opp_score"]] = low_scores[["score", "opp_score"]].round(2)
        disp = prep_display(low_scores, manager_map, show_mgr, show_team,
                            cols=["team_name", "week_label", "score", "opp_name", "opp_score", "outcome"],
                            headers=["Team", "Week", "Score", "Opponent", "Opp Score", "Result"])
        st.dataframe(disp, use_container_width=True, hide_index=True)

    st.markdown("**Highest-Scoring Matchups**")
    matchup_totals = df_tagged.merge(
        df_tagged[["week", "team_id", "score"]].rename(columns={"team_id": "opp_id", "score": "opp_score_check"}),
        on=["week", "opp_id"], how="left"
    )
    matchup_totals["matchup_total"] = matchup_totals["score"] + matchup_totals["opp_score"]
    top_matchups = matchup_totals.drop_duplicates(subset=["week", "opp_id"]).nlargest(10, "matchup_total")[
        ["team_id", "week_label", "team_name", "score", "opp_name", "opp_score", "matchup_total"]
    ].copy()
    top_matchups[["score", "opp_score", "matchup_total"]] = top_matchups[["score", "opp_score", "matchup_total"]].round(2)
    disp = prep_display(top_matchups, manager_map, show_mgr, show_team,
                        cols=["team_name", "week_label", "score", "opp_name", "opp_score", "matchup_total"],
                        headers=["Team", "Week", "Score", "Opponent", "Opp Score", "Total"])
    st.dataframe(disp, use_container_width=True, hide_index=True)

with tab4:
    st.subheader("Head-to-Head Score Comparison")
    col1, col2 = st.columns(2)
    with col1:
        team_a = st.selectbox("Team A", teams, key="h2h_a")
    with col2:
        team_b = st.selectbox("Team B", [t for t in teams if t != team_a], key="h2h_b")

    matchups_between = df[
        ((df["team_name"] == team_a) & (df["opp_name"] == team_b)) |
        ((df["team_name"] == team_b) & (df["opp_name"] == team_a))
    ]

    if matchups_between.empty:
        st.info("These two teams haven't played each other yet.")
    else:
        a_rows = matchups_between[matchups_between["team_name"] == team_a]
        b_rows = matchups_between[matchups_between["team_name"] == team_b]
        a_wins = (a_rows["outcome"] == "W").sum()
        b_wins = (b_rows["outcome"] == "W").sum()
        lbl_a, lbl_b = label_for(team_a), label_for(team_b)
        col1, col2, col3 = st.columns(3)
        col1.metric(lbl_a, a_wins)
        col2.metric(lbl_b, b_wins)
        col3.metric("Matchups", len(a_rows))

        fig = go.Figure()
        fig.add_trace(go.Bar(name=lbl_a, x=a_rows["week"].astype(str), y=a_rows["score"],
                             marker_color="#3498db"))
        fig.add_trace(go.Bar(name=lbl_b, x=b_rows["week"].astype(str), y=b_rows["score"],
                             marker_color="#e74c3c"))
        fig.update_layout(barmode="group", xaxis_title="Week", yaxis_title="Score",
                          title=f"{lbl_a} vs {lbl_b} — Head to Head")
        st.plotly_chart(fig, use_container_width=True)

    # Full H2H matrix — rows/cols use display labels
    st.subheader("All-Time H2H Record Matrix")
    labels = [label_for(t) for t in teams]
    name_to_label = dict(zip(teams, labels))
    matrix = pd.DataFrame(index=labels, columns=labels, data="-")
    for team, lbl in zip(teams, labels):
        for opp, opp_lbl in zip(teams, labels):
            if team == opp:
                continue
            rows = df[(df["team_name"] == team) & (df["opp_name"] == opp)]
            if not rows.empty:
                w = (rows["outcome"] == "W").sum()
                l = (rows["outcome"] == "L").sum()
                matrix.loc[lbl, opp_lbl] = f"{w}-{l}"
    st.dataframe(matrix, use_container_width=True)
