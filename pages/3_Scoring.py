import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from data.espn_client import get_matchups_df, get_manager_map
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
    # ── Individual manager trend ───────────────────────────────────────────────
    st.subheader("Individual Manager Trend")

    weekly_avg = df.groupby("week")["score"].mean()
    weekly_med = df.groupby("week")["score"].median()
    all_weeks = weekly_avg.index.values.astype(float)

    LEAGUE_MEDIAN = "— League Median —"
    mgr_to_team = {manager_map.get(tid_by_name.get(t), t): t for t in teams}
    dropdown_options = [LEAGUE_MEDIAN] + sorted(mgr_to_team.keys())
    selected_mgr = st.selectbox("Select manager", dropdown_options, key="indiv_mgr")

    is_median = selected_mgr == LEAGUE_MEDIAN
    if is_median:
        weeks = all_weeks
        scores = weekly_med.values.astype(float)
        line_color = "#8e44ad"
        display_name = "League Median"
    else:
        selected_team = mgr_to_team[selected_mgr]
        tdf = df[df["team_name"] == selected_team].sort_values("week")
        weeks = tdf["week"].values.astype(float)
        scores = tdf["score"].values.astype(float)
        line_color = "#3498db"
        display_name = selected_mgr

    fig3 = go.Figure()

    fig3.add_trace(go.Scatter(
        x=weeks, y=scores, mode="lines+markers",
        name=display_name, line=dict(color=line_color, width=2),
        hovertemplate="Week %{x:.0f}: %{y:.2f} pts<extra></extra>",
    ))
    if not is_median:
        fig3.add_trace(go.Scatter(
            x=all_weeks, y=weekly_avg.values, mode="lines",
            name="League Average", line=dict(dash="dot", color="lightgray", width=1.5),
        ))

    max_week = int(weeks[-1]) if len(weeks) > 0 else int(all_weeks[-1])
    played_weeks = all_weeks[all_weeks <= max_week]

    m_full = m_l5 = None

    # Season-long trendline
    if len(weeks) >= 2:
        m_full, b_full = np.polyfit(weeks, scores, 1)
        fig3.add_trace(go.Scatter(
            x=played_weeks, y=m_full * played_weeks + b_full, mode="lines",
            name="Season trend", line=dict(color=line_color, dash="dash", width=1.5),
        ))

    # Last-5 trendline — only shown from week 6 onward
    if len(weeks) >= 6:
        last5_weeks = weeks[-5:]
        last5_scores = scores[-5:]
        m_l5, b_l5 = np.polyfit(last5_weeks, last5_scores, 1)
        fig3.add_trace(go.Scatter(
            x=last5_weeks, y=m_l5 * last5_weeks + b_l5, mode="lines",
            name="Last 5 trend", line=dict(color="#e67e22", dash="dash", width=2),
        ))

    fig3.update_layout(
        height=420, xaxis_title="Week", yaxis_title="Points",
        hovermode="x unified", xaxis=dict(dtick=1, range=[0.5, max_week + 0.5]),
        title=f"{display_name} — Weekly Scoring with Trendlines",
    )
    st.plotly_chart(fig3, use_container_width=True)

    # Slope metrics below the chart
    if m_full is not None or m_l5 is not None:
        mcols = st.columns(2)
        if m_full is not None:
            mcols[0].metric("Season trend", f"{m_full:+.1f} pts/wk", delta=f"{m_full:.1f}")
        if m_l5 is not None:
            mcols[1].metric("Last 5 trend", f"{m_l5:+.1f} pts/wk", delta=f"{m_l5:.1f}")

    st.divider()

    # ── All teams chart ────────────────────────────────────────────────────────
    st.subheader("Weekly Scoring Trends — All Teams")
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
        Mean="mean", Median="median", Std="std", Min="min", Max="max"
    ).round(2).reset_index()
    # Consistency: 1 is the steadiest week to week, so rank by the smallest
    # spread. It says nothing about scoring well, only about scoring alike.
    team_stats["Consistency"] = team_stats["Std"].rank(method="min").astype(int)
    display = prep_display(team_stats, manager_map, show_mgr, show_team,
                           cols=["team_name", "Mean", "Median", "Min", "Max",
                                 "Std", "Consistency"],
                           headers=["Team", "Mean", "Median", "Min", "Max",
                                    "Std Dev", "Consistency"])
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.caption("Consistency ranks by standard deviation: 1 is the most "
               "predictable week to week, not the highest scoring.")

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
        st.markdown("**Top 5 Individual Scores**")
        top_scores = df_tagged.nlargest(5, "score")[["team_id", "week_label", "team_name", "score", "opp_name", "opp_score", "outcome"]].copy()
        top_scores[["score", "opp_score"]] = top_scores[["score", "opp_score"]].round(2)
        disp = prep_display(top_scores, manager_map, show_mgr, show_team,
                            cols=["team_name", "week_label", "score", "opp_name", "opp_score", "outcome"],
                            headers=["Team", "Week", "Score", "Opponent", "Opp Score", "Result"])
        st.dataframe(disp, use_container_width=True, hide_index=True)

    with col2:
        st.markdown("**5 Lowest Individual Scores**")
        low_scores = df_tagged.nsmallest(5, "score")[["team_id", "week_label", "team_name", "score", "opp_name", "opp_score", "outcome"]].copy()
        low_scores[["score", "opp_score"]] = low_scores[["score", "opp_score"]].round(2)
        disp = prep_display(low_scores, manager_map, show_mgr, show_team,
                            cols=["team_name", "week_label", "score", "opp_name", "opp_score", "outcome"],
                            headers=["Team", "Week", "Score", "Opponent", "Opp Score", "Result"])
        st.dataframe(disp, use_container_width=True, hide_index=True)

    st.markdown("**Top 5 Highest-Scoring Matchups**")
    # Build a canonical pair key (lower team_id first) so each matchup only appears once
    df_tagged["pair_key"] = df_tagged.apply(
        lambda r: (min(r["team_id"], r["opp_id"]), max(r["team_id"], r["opp_id"])), axis=1
    )
    df_tagged["matchup_total"] = df_tagged["score"] + df_tagged["opp_score"]
    top_matchups = (
        df_tagged.sort_values("matchup_total", ascending=False)
        .drop_duplicates(subset=["week", "pair_key"])
        .head(5)
        [["team_id", "week_label", "team_name", "score", "opp_name", "opp_score", "matchup_total"]]
        .copy()
    )
    top_matchups[["score", "opp_score", "matchup_total"]] = top_matchups[["score", "opp_score", "matchup_total"]].round(2)
    disp = prep_display(top_matchups, manager_map, show_mgr, show_team,
                        cols=["team_name", "week_label", "score", "opp_name", "opp_score", "matchup_total"],
                        headers=["Team", "Week", "Score", "Opponent", "Opp Score", "Total"])
    st.dataframe(disp, use_container_width=True, hide_index=True)

with tab4:
    st.subheader("Season H2H Record Matrix")
    st.caption("Each cell shows the **row** manager's W-L record against the **column** manager.")
    mgr_labels = [manager_map.get(tid_by_name.get(t), t) for t in teams]
    matrix = pd.DataFrame(index=mgr_labels, columns=mgr_labels, data="-")
    matrix.index.name = "↓ row vs col →"
    for team, lbl in zip(teams, mgr_labels):
        for opp, opp_lbl in zip(teams, mgr_labels):
            if team == opp:
                continue
            rows = df[(df["team_name"] == team) & (df["opp_name"] == opp)]
            if not rows.empty:
                w = (rows["outcome"] == "W").sum()
                l = (rows["outcome"] == "L").sum()
                matrix.loc[lbl, opp_lbl] = f"{w}-{l}"
    st.dataframe(matrix, use_container_width=True)
