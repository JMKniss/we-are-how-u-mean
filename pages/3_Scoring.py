import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from data.espn_client import get_matchups_df, invalidate_cache
from config import SEASONS, DEFAULT_SEASON

st.set_page_config(page_title="Scoring", page_icon="📈", layout="wide")
st.title("📈 Scoring Analysis")

season = st.sidebar.selectbox("Season", SEASONS, index=SEASONS.index(DEFAULT_SEASON))
if st.sidebar.button("🔄 Refresh Data"):
    invalidate_cache(season)
    st.cache_data.clear()
    st.rerun()

@st.cache_data(ttl=300)
def load(season):
    return get_matchups_df(season)

with st.spinner("Loading..."):
    df = load(season)

teams = sorted(df["team_name"].unique())

tab1, tab2, tab3, tab4 = st.tabs(["Weekly Trends", "Score Distributions", "Best & Worst", "Head-to-Head Scores"])

with tab1:
    st.subheader("Weekly Scoring Trends")
    selected = st.multiselect("Filter teams", teams, default=teams)
    filtered = df[df["team_name"].isin(selected)]

    fig = go.Figure()
    for team in selected:
        tdf = filtered[filtered["team_name"] == team].sort_values("week")
        fig.add_trace(go.Scatter(
            x=tdf["week"], y=tdf["score"], mode="lines+markers",
            name=team, hovertemplate="Week %{x}: %{y:.2f} pts<extra>" + team + "</extra>",
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

    # Weekly high/low band
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
        fig = px.box(df, x="team_name", y="score", color="team_name",
                     title="Score Distribution by Team",
                     labels={"team_name": "Team", "score": "Points"})
        fig.update_layout(xaxis_tickangle=-30, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = px.histogram(df, x="score", nbins=30, title="Overall Score Distribution",
                           labels={"score": "Points", "count": "Frequency"})
        # Overlay normal distribution
        mu, sigma = df["score"].mean(), df["score"].std()
        x_range = np.linspace(df["score"].min(), df["score"].max(), 100)
        from scipy.stats import norm
        y_norm = norm.pdf(x_range, mu, sigma) * len(df) * (df["score"].max() - df["score"].min()) / 30
        fig.add_trace(go.Scatter(x=x_range, y=y_norm, mode="lines", name="Normal fit",
                                 line=dict(color="red", width=2)))
        st.plotly_chart(fig, use_container_width=True)

    # Per-team stats table
    team_stats = df.groupby("team_name")["score"].agg(
        Mean="mean", Median="median", Std="std", Min="min", Max="max",
        Weeks="count"
    ).round(2).reset_index()
    team_stats.columns = ["Team", "Mean", "Median", "Std Dev", "Min", "Max", "Weeks"]
    st.dataframe(team_stats, use_container_width=True, hide_index=True)

with tab3:
    st.subheader("Season Records")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Top 10 Individual Scores**")
        top_scores = df.nlargest(10, "score")[["week", "team_name", "score", "opp_name", "opp_score", "outcome"]]
        top_scores.columns = ["Week", "Team", "Score", "Opponent", "Opp Score", "Result"]
        top_scores["Score"] = top_scores["Score"].round(2)
        top_scores["Opp Score"] = top_scores["Opp Score"].round(2)
        st.dataframe(top_scores, use_container_width=True, hide_index=True)

    with col2:
        st.markdown("**10 Lowest Individual Scores**")
        low_scores = df.nsmallest(10, "score")[["week", "team_name", "score", "opp_name", "opp_score", "outcome"]]
        low_scores.columns = ["Week", "Team", "Score", "Opponent", "Opp Score", "Result"]
        low_scores["Score"] = low_scores["Score"].round(2)
        low_scores["Opp Score"] = low_scores["Opp Score"].round(2)
        st.dataframe(low_scores, use_container_width=True, hide_index=True)

    st.markdown("**Highest-Scoring Matchups**")
    df_m = df.copy()
    matchup_totals = df_m.merge(
        df_m[["week", "team_id", "score"]].rename(columns={"team_id": "opp_id", "score": "opp_score_check"}),
        on=["week", "opp_id"], how="left"
    )
    matchup_totals["matchup_total"] = matchup_totals["score"] + matchup_totals["opp_score"]
    top_matchups = matchup_totals.drop_duplicates(subset=["week", "opp_id"]).nlargest(10, "matchup_total")[
        ["week", "team_name", "score", "opp_name", "opp_score", "matchup_total"]
    ]
    top_matchups.columns = ["Week", "Team", "Score", "Opponent", "Opp Score", "Total"]
    top_matchups = top_matchups.round(2)
    st.dataframe(top_matchups, use_container_width=True, hide_index=True)

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
        col1, col2, col3 = st.columns(3)
        col1.metric(f"{team_a} Wins", a_wins)
        col2.metric(f"{team_b} Wins", b_wins)
        col3.metric("Matchups", len(a_rows))

        fig = go.Figure()
        fig.add_trace(go.Bar(name=team_a, x=a_rows["week"].astype(str), y=a_rows["score"],
                             marker_color="#3498db"))
        fig.add_trace(go.Bar(name=team_b, x=b_rows["week"].astype(str), y=b_rows["score"],
                             marker_color="#e74c3c"))
        fig.update_layout(barmode="group", xaxis_title="Week", yaxis_title="Score",
                          title=f"{team_a} vs {team_b} — Head to Head")
        st.plotly_chart(fig, use_container_width=True)

    # Full H2H matrix
    st.subheader("All-Time H2H Record Matrix")
    matrix = pd.DataFrame(index=teams, columns=teams, data="-")
    for team in teams:
        for opp in teams:
            if team == opp:
                continue
            rows = df[(df["team_name"] == team) & (df["opp_name"] == opp)]
            if not rows.empty:
                w = (rows["outcome"] == "W").sum()
                l = (rows["outcome"] == "L").sum()
                matrix.loc[team, opp] = f"{w}-{l}"
    st.dataframe(matrix, use_container_width=True)
