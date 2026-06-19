import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from data.espn_client import get_boxscores_df, invalidate_cache
from analysis.efficiency import lineup_efficiency, top_players, projected_vs_actual
from config import SEASONS, DEFAULT_SEASON

st.set_page_config(page_title="Lineup Efficiency", page_icon="🎯", layout="wide")
st.title("🎯 Lineup Efficiency")
st.caption("How well did each manager set their lineup? Optimal score = best possible lineup from their roster.")

season = st.sidebar.selectbox("Season", SEASONS, index=SEASONS.index(DEFAULT_SEASON))
if st.sidebar.button("🔄 Refresh Data"):
    invalidate_cache(season)
    st.cache_data.clear()
    st.rerun()

@st.cache_data(ttl=300)
def load(season):
    return get_boxscores_df(season)

with st.spinner("Loading player-level data (first load may take a minute)..."):
    box_df = load(season)

if box_df.empty:
    st.warning("No box score data available yet.")
    st.stop()

summary, weekly = lineup_efficiency(box_df)

tab1, tab2, tab3, tab4 = st.tabs(["Season Summary", "Weekly Efficiency", "Top Players", "Projections vs Actual"])

with tab1:
    st.subheader("Season Efficiency Summary")
    display = summary[["team_name", "avg_actual", "avg_optimal", "avg_efficiency",
                        "avg_bench", "avg_left_on_bench", "total_left_on_bench"]].copy()
    display.columns = ["Team", "Avg Actual", "Avg Optimal", "Efficiency %",
                        "Avg Bench Pts", "Avg Left on Bench", "Total Left on Bench"]
    st.dataframe(display, use_container_width=True)

    fig = px.bar(summary.sort_values("avg_efficiency"), x="avg_efficiency", y="team_name",
                 orientation="h", title="Average Lineup Efficiency %",
                 labels={"avg_efficiency": "Efficiency %", "team_name": "Team"},
                 color="avg_efficiency", color_continuous_scale="RdYlGn",
                 range_color=[summary["avg_efficiency"].min() - 2, 100])
    fig.add_vline(x=summary["avg_efficiency"].mean(), line_dash="dash", line_color="gray",
                  annotation_text="League Avg")
    fig.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        fig2 = px.bar(summary.sort_values("total_left_on_bench", ascending=False),
                      x="team_name", y="total_left_on_bench",
                      title="Total Points Left on Bench (Season)",
                      labels={"team_name": "Team", "total_left_on_bench": "Points"},
                      color="total_left_on_bench", color_continuous_scale="Reds")
        fig2.update_layout(xaxis_tickangle=-30, coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

    with col2:
        fig3 = px.scatter(summary, x="avg_actual", y="avg_efficiency",
                          text="team_name", title="Actual Score vs Efficiency",
                          labels={"avg_actual": "Avg Actual Score", "avg_efficiency": "Efficiency %"})
        fig3.update_traces(textposition="top center")
        st.plotly_chart(fig3, use_container_width=True)

with tab2:
    st.subheader("Weekly Efficiency by Team")
    teams = sorted(weekly["team_name"].unique())
    selected_team = st.selectbox("Select Team", ["All Teams"] + teams)

    if selected_team == "All Teams":
        fig = px.line(weekly.sort_values("week"), x="week", y="efficiency_pct",
                      color="team_name", markers=True,
                      title="Lineup Efficiency % by Week",
                      labels={"week": "Week", "efficiency_pct": "Efficiency %", "team_name": "Team"})
        fig.add_hline(y=100, line_dash="dash", line_color="gray", annotation_text="Perfect")
    else:
        tdf = weekly[weekly["team_name"] == selected_team].sort_values("week")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=tdf["week"], y=tdf["actual_score"], name="Actual", marker_color="#3498db"))
        fig.add_trace(go.Bar(x=tdf["week"], y=tdf["optimal_score"], name="Optimal", marker_color="#2ecc71"))
        fig.add_trace(go.Scatter(x=tdf["week"], y=tdf["bench_points"], name="Bench Pts",
                                 mode="lines+markers", line=dict(color="orange")))
        fig.update_layout(barmode="group", title=f"{selected_team} — Actual vs Optimal by Week",
                          xaxis_title="Week", yaxis_title="Points", xaxis=dict(dtick=1))
    st.plotly_chart(fig, use_container_width=True)

    if selected_team != "All Teams":
        tdf = weekly[weekly["team_name"] == selected_team][
            ["week", "actual_score", "optimal_score", "bench_points", "points_left_on_bench", "efficiency_pct"]
        ].round(2)
        tdf.columns = ["Week", "Actual", "Optimal", "Bench Pts", "Left on Bench", "Eff%"]
        st.dataframe(tdf, use_container_width=True, hide_index=True)

with tab3:
    st.subheader("Top Scoring Players")
    positions = ["All"] + sorted(box_df["position"].dropna().unique().tolist())
    col1, col2 = st.columns([1, 3])
    with col1:
        pos_filter = st.selectbox("Position", positions)
        top_n = st.slider("Show top N", 10, 50, 20)
    pos = None if pos_filter == "All" else pos_filter
    top = top_players(box_df, position=pos, top_n=top_n)
    top.index += 1
    st.dataframe(top, use_container_width=True)

with tab4:
    st.subheader("Projected vs Actual Scoring")
    st.caption("Did teams consistently outscore or underperform their ESPN projections?")
    proj_df = projected_vs_actual(box_df)
    display = proj_df[["team_name", "times_beat_proj", "total_weeks", "beat_proj_pct", "avg_proj_diff"]].copy()
    display.columns = ["Team", "Times Beat Proj", "Weeks", "Beat Proj %", "Avg Diff"]
    display["Avg Diff"] = display["Avg Diff"].round(2)
    st.dataframe(display, use_container_width=True, hide_index=True)

    fig = px.bar(proj_df.sort_values("avg_proj_diff"), x="avg_proj_diff", y="team_name",
                 orientation="h", title="Average Points Above/Below ESPN Projection",
                 labels={"avg_proj_diff": "Avg Diff (Actual − Projected)", "team_name": "Team"},
                 color="avg_proj_diff", color_continuous_scale="RdYlGn")
    fig.add_vline(x=0, line_dash="dash", line_color="gray")
    fig.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)
